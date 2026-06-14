"""URL-reader grounding skill — deterministic, no LLM or API key.

When the query contains one or more URLs, fetch each and extract readable text
so the council is grounded in the actual page content rather than the models'
recollection of it. Fires whenever a URL is present (it ignores the classifier).
"""

import asyncio
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Set

import httpx

from .base import GroundingSkill

# Conservative URL matcher; trailing punctuation is trimmed in extract_urls.
_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
_SKIP_TAGS = {"script", "style", "noscript", "head", "svg", "template"}


class _TextExtractor(HTMLParser):
    """Strip tags to visible text, capturing <title> and skipping script/style."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: List[str] = []
        self._skip = 0
        self._in_title = False
        self.title: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        self._chunks.append(text)

    def text(self) -> str:
        return " ".join(self._chunks)


def extract_urls(query: str, limit: int) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for m in _URL_RE.finditer(query):
        u = m.group(0).rstrip(".,);]'\"")
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= limit:
            break
    return out


class UrlReaderSkill(GroundingSkill):
    id = "url_reader"
    label = "Page Content"

    def applies(self, query: str, llm_skills: Set[str]) -> bool:
        return bool(_URL_RE.search(query))

    async def _fetch(self, client: httpx.AsyncClient, url: str, max_chars: int) -> Dict[str, Any]:
        try:
            r = await client.get(url, follow_redirects=True)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "html" in ctype or not ctype:
                p = _TextExtractor()
                p.feed(r.text)
                text, title = p.text(), (p.title or url)
            else:
                text, title = r.text, url
            text = re.sub(r"\s+", " ", text).strip()[:max_chars]
            return {"url": url, "title": title, "text": text}
        except Exception as e:  # noqa: BLE001 — report unreadable URLs, don't crash grounding
            return {"url": url, "title": url, "text": "", "error": str(e)}

    async def ground(self, query: str) -> Optional[Dict[str, Any]]:
        c = self.config
        max_urls = int(c.get("max_urls", 3))
        max_chars = int(c.get("max_chars", 6000))
        timeout = float(c.get("timeout", 30))

        urls = extract_urls(query, max_urls)
        if not urls:
            return None

        headers = {"User-Agent": "Mozilla/5.0 (compatible; AI-Ministry URL reader)"}
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            pages = await asyncio.gather(*(self._fetch(client, u, max_chars) for u in urls))

        facts: List[str] = []
        citations: List[Dict[str, str]] = []
        readable = 0
        for p in pages:
            citations.append({"url": p["url"], "title": p["title"]})
            if p["text"]:
                readable += 1
                facts.append(f"- **{p['title']}** ({p['url']}): {p['text']}")
            else:
                facts.append(f"- Could not read {p['url']} ({p.get('error', 'no content')})")

        if not readable:
            return None

        return {
            "key_facts": "\n".join(facts),
            "summary": "",
            "citations": citations,
            "search_queries": [],
            "source": self.id,
            "label": self.label,
            "model": "url_reader",
        }
