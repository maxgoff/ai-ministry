"""Code-execution grounding skill — sandboxed.

For computational/quantitative queries, an LLM writes a short, self-contained
Python snippet; we run it in a hardened subprocess and feed its stdout back as
a grounded fact for the council.

SECURITY: the executed code is LLM-authored *from a user query* — treat it as
untrusted. Defense-in-depth:
  - separate `python -I -S` process (isolated, no site, ignores PYTHON* env)
  - scrubbed environment (no API keys reachable) + a throwaway temp cwd
  - POSIX rlimits (CPU, address space, file size) applied in the child
  - own process group + wall-clock timeout with SIGKILL on the whole group
  - best-effort static reject of obvious escape attempts before running
This is NOT a true sandbox — strong isolation needs a container/nsjail, which
is out of scope. Set grounding_stage.skills.code_exec.enabled=false to turn it
off entirely if that residual risk is unacceptable.
"""

import asyncio
import os
import re
import resource
import signal
import sys
import tempfile
from typing import Any, Dict, Optional, Set

from .base import GroundingSkill
from ..openrouter import query_model

_CODEGEN_PROMPT = """You write a single self-contained Python 3 script that answers the user's question by COMPUTATION.

Rules:
- Standard library only. No network access, no file I/O, no installing packages.
- Print the result clearly with a short label using print().
- Keep it short and deterministic. No input(). No infinite loops.
- Output ONLY the Python code — no markdown fences, no commentary.

User question:
{query}
"""

# Substrings that get a snippet rejected outright (best-effort, defense-in-depth
# behind the subprocess isolation — not the sole protection).
_BANNED = (
    "import os", "import sys", "import subprocess", "import socket", "import shutil",
    "import multiprocessing", "import threading", "import ctypes", "import importlib",
    "import urllib", "import requests", "import http", "import pathlib", "import glob",
    "__import__", "eval(", "exec(", "compile(", "open(", "globals(",
    "os.", "sys.", "subprocess", "socket", "shutil", "pickle", "marshal",
)

_CODE_FENCE = re.compile(r"^```(?:python)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _CODE_FENCE.sub("", text).strip()


def _is_safe(code: str) -> bool:
    low = code.lower()
    return bool(code) and not any(tok in low for tok in _BANNED)


def _limits(cpu_seconds: int, mem_bytes: int, fsize_bytes: int):
    """Return a preexec_fn that isolates the child into its own process group
    and applies resource limits. Each limit is best-effort (RLIMIT_AS is not
    reliably enforced on macOS) so a single unsupported limit can't abort the run."""

    def _apply():
        os.setsid()
        for res, lim in (
            (resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds)),
            (resource.RLIMIT_AS, (mem_bytes, mem_bytes)),
            (resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes)),
        ):
            try:
                resource.setrlimit(res, lim)
            except (ValueError, OSError):
                pass

    return _apply


class CodeExecSkill(GroundingSkill):
    id = "code_exec"
    label = "Code Execution"

    def applies(self, query: str, llm_skills: Set[str]) -> bool:
        return "code_exec" in llm_skills

    async def _run_code(self, code: str) -> Dict[str, Any]:
        c = self.config
        timeout = float(c.get("timeout", 8))
        mem_mb = int(c.get("mem_limit_mb", 256))
        max_out = int(c.get("max_output_chars", 4000))

        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": tmp,
                "TMPDIR": tmp,
                "PYTHONPATH": "",
                "PYTHONDONTWRITEBYTECODE": "1",
                "LC_ALL": "C.UTF-8",
            }
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-I", "-S", "-c", code,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tmp,
                    env=env,
                    preexec_fn=_limits(int(timeout) + 1, mem_mb * 1024 * 1024, 1024 * 1024),
                )
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"spawn failed: {e}", "stdout": "", "stderr": ""}

            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                return {"ok": False, "error": f"timed out after {timeout}s", "stdout": "", "stderr": ""}

            stdout = (out or b"").decode("utf-8", "replace")[:max_out]
            stderr = (err or b"").decode("utf-8", "replace")[:1000]
            ok = proc.returncode == 0 and bool(stdout.strip())
            return {
                "ok": ok,
                "error": "" if proc.returncode == 0 else f"exit {proc.returncode}",
                "stdout": stdout,
                "stderr": stderr,
            }

    async def ground(self, query: str) -> Optional[Dict[str, Any]]:
        c = self.config
        model = c.get("codegen_model", "google/gemini-2.5-flash")
        resp = await query_model(
            model,
            [{"role": "user", "content": _CODEGEN_PROMPT.format(query=query)}],
            timeout=float(c.get("codegen_timeout", 60)),
            max_retries=1,
        )
        if not resp or not resp.get("content"):
            return None

        code = _strip_fences(resp["content"])
        if not _is_safe(code):
            print("[code_exec] snippet rejected by static safety check")
            return None

        result = await self._run_code(code)
        if not result["ok"]:
            print(f"[code_exec] execution failed: {result.get('error')} "
                  f"{result.get('stderr', '')[:200]}")
            return None

        return {
            "key_facts": f"Computed result:\n```\n{result['stdout'].strip()}\n```",
            "summary": f"Executed Python:\n```python\n{code}\n```",
            "citations": [],
            "search_queries": [],
            "source": self.id,
            "label": self.label,
            "model": f"code_exec ({model})",
        }
