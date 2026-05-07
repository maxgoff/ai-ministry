"""Model ID taxonomy: parse provider/model strings into (family, tier, version).

Used by the discovery + generation policy to group models and decide which are
'current generation' vs superseded.

A parse is a best-effort heuristic over known providers. Anything we don't
recognize is classified as family='other' and is exempt from auto-eviction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple


# Tuple of integers for comparable major.minor.patch ordering.
# Empty tuple () sorts lowest — used when no version found.
VersionTuple = Tuple[int, ...]


@dataclass(frozen=True)
class ParsedModel:
    """Result of parsing a model identifier."""
    provider: str          # e.g. "anthropic", "openai", "google", "xai", "moonshot", "nvidia", "deepseek", "meta-llama"
    family: str            # e.g. "claude", "gpt", "gemini", "grok", "kimi", "deepseek", "llama", "qwen", "other"
    tier: str              # e.g. "opus", "sonnet", "haiku", "pro", "flash", "mini", "reasoning", ""
    version: VersionTuple  # e.g. (4, 6) for claude-opus-4.6
    raw: str               # original model id

    @property
    def major(self) -> int:
        return self.version[0] if self.version else 0


# Family detection — first match wins.
# Patterns are matched against the bare model name (after provider/ prefix is split off).
_FAMILY_PATTERNS = [
    ("claude",   re.compile(r"\bclaude\b", re.I)),
    ("gpt",      re.compile(r"\bgpt\b|\bgpt-", re.I)),
    ("gemini",   re.compile(r"\bgemini\b", re.I)),
    ("grok",     re.compile(r"\bgrok\b", re.I)),
    ("kimi",     re.compile(r"\bkimi\b", re.I)),
    ("deepseek", re.compile(r"\bdeepseek\b", re.I)),
    ("llama",    re.compile(r"\bllama\b", re.I)),
    ("qwen",     re.compile(r"\bqwen\b", re.I)),
    ("mistral",  re.compile(r"\bmistral\b", re.I)),
]

# Tier detection — first match wins.
# Order matters: more specific patterns must come before general ones.
# `non-X` variants must precede `X` so the negative form wins on substring.
_TIER_PATTERNS = [
    ("opus",          re.compile(r"\bopus\b", re.I)),
    ("sonnet",        re.compile(r"\bsonnet\b", re.I)),
    ("haiku",         re.compile(r"\bhaiku\b", re.I)),
    ("flash-lite",    re.compile(r"\bflash-?lite\b", re.I)),
    ("flash",         re.compile(r"\bflash\b", re.I)),
    ("pro",           re.compile(r"\bpro\b", re.I)),
    ("ultra",         re.compile(r"\bultra\b", re.I)),
    ("nano",          re.compile(r"\bnano\b", re.I)),
    ("mini",          re.compile(r"\bmini\b", re.I)),
    ("maverick",      re.compile(r"\bmaverick\b", re.I)),
    ("scout",         re.compile(r"\bscout\b", re.I)),
    ("non-reasoning", re.compile(r"\bnon-reasoning\b", re.I)),
    ("reasoning",     re.compile(r"\breasoning\b", re.I)),
    ("non-thinking",  re.compile(r"\bnon-thinking\b", re.I)),
    ("thinking",      re.compile(r"\bthinking\b", re.I)),
    ("non-fast",      re.compile(r"\bnon-fast\b", re.I)),
    ("instant",       re.compile(r"\binstant\b", re.I)),
    ("fast",          re.compile(r"\bfast\b", re.I)),
    ("instruct",      re.compile(r"\binstruct\b", re.I)),
    ("chat",          re.compile(r"\bchat\b", re.I)),
]

# Version extraction — capture the first number-like sequence with optional decimal/dash parts.
# Examples we want to match:
#   claude-opus-4.6      -> (4, 6)
#   claude-haiku-4-5-20251001 -> (4, 5) — date suffix not part of version
#   gpt-5.2              -> (5, 2)
#   gpt-4o               -> (4,)
#   gpt-4.1              -> (4, 1)
#   gemini-3.1-pro       -> (3, 1)
#   gemini-3-pro         -> (3,)
#   grok-4.20-0309       -> (4, 20)
#   grok-4-1-fast        -> (4, 1)
#   kimi-k2.5            -> (2, 5)
#   kimi-k2              -> (2,)
#   deepseek-v3.2        -> (3, 2)
#   llama-4-maverick     -> (4,)
#   llama-3.3-70b        -> (3, 3)
_VERSION_PATTERNS = [
    # Family-anchored patterns (preferred — more accurate)
    re.compile(r"claude-(?:opus|sonnet|haiku)?-?(\d+(?:[.\-]\d+)*?)(?:-\d{6,}|$|[^0-9.\-])", re.I),
    re.compile(r"gpt-(\d+(?:\.\d+)?)", re.I),
    re.compile(r"gemini-(\d+(?:\.\d+)?)", re.I),
    re.compile(r"grok-(\d+(?:[.\-]\d+)?)", re.I),
    re.compile(r"kimi-k(\d+(?:\.\d+)?)", re.I),
    re.compile(r"deepseek-v?(\d+(?:\.\d+)?)", re.I),
    re.compile(r"llama-(\d+(?:\.\d+)?)", re.I),
    re.compile(r"qwen-?(\d+(?:\.\d+)?)", re.I),
]


def _split_provider(model_id: str) -> Tuple[str, str]:
    """Split a 'provider/name' string. If no slash, provider='' and name=full string."""
    if "/" in model_id:
        provider, _, name = model_id.partition("/")
        return provider.lower(), name
    return "", model_id


def _detect_family(name: str) -> str:
    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(name):
            return family
    return "other"


def _detect_tier(name: str) -> str:
    for tier, pattern in _TIER_PATTERNS:
        if pattern.search(name):
            return tier
    return ""


def _parse_version_str(raw: str) -> VersionTuple:
    """Convert '4.6' or '4-1' or '4.20' into a tuple of ints."""
    parts = re.split(r"[.\-]", raw)
    out = []
    for p in parts:
        if p.isdigit():
            out.append(int(p))
        else:
            break  # stop at first non-numeric chunk
    return tuple(out)


# Date suffixes embedded in model IDs (e.g. `-2025-10-06`, `-20251001`).
# Stripped before version parsing so dates don't get mistaken for versions.
_DATE_SUFFIX_RE = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{6,})(?=$|-)")


def _strip_dates(name: str) -> str:
    """Remove date-like suffixes anywhere in the name."""
    return _DATE_SUFFIX_RE.sub("", name)


def _detect_version(name: str, family: str) -> VersionTuple:
    """Try to extract a version tuple. Falls back to () if nothing matches."""
    cleaned = _strip_dates(name)
    for pattern in _VERSION_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            return _parse_version_str(m.group(1))
    # Generic fallback: first standalone number sequence in the cleaned name
    m = re.search(r"\b(\d+(?:[.\-]\d+)*)\b", cleaned)
    if m:
        return _parse_version_str(m.group(1))
    return ()


def parse_model(model_id: str) -> ParsedModel:
    """
    Parse a 'provider/model' identifier into structured metadata.

    Args:
        model_id: e.g. "anthropic/claude-opus-4.6", "openai/gpt-5.2",
                  "xai/grok-4-1-fast-reasoning"

    Returns:
        ParsedModel with provider/family/tier/version.
        Unknown identifiers get family='other' and are exempt from eviction.
    """
    provider, name = _split_provider(model_id)
    family = _detect_family(name)
    tier = _detect_tier(name)
    version = _detect_version(name, family) if family != "other" else ()

    return ParsedModel(
        provider=provider,
        family=family,
        tier=tier,
        version=version,
        raw=model_id,
    )


def is_evictable(parsed: ParsedModel) -> bool:
    """
    Whether a model is eligible for being superseded.

    Models with family='other' or no detected version are pinned — they stay
    in the registry across refreshes since we can't reason about their generation.
    """
    return parsed.family != "other" and bool(parsed.version)
