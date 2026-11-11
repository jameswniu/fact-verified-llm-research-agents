"""Gemini Developer API client and a small web fetcher.

REST against generativelanguage.googleapis.com with an API key only (GEMINI_API_KEY).
Vertex AI and google-cloud-aiplatform are deliberately not used. Standard library only.
"""
from __future__ import annotations

import base64
import html
import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MODEL = os.environ.get("RESEARCH_MODEL", "gemini-flash-latest")
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
ROOT = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class MissingAPIKeyError(RuntimeError):
    """GEMINI_API_KEY is not set."""


class LLMError(RuntimeError):
    """The Gemini API failed after retries, or rejected the request."""


class AuthError(MissingAPIKeyError, LLMError):
    """GEMINI_API_KEY is set but the API rejected it (wrong, revoked or restricted key)."""


class BudgetExceeded(RuntimeError):
    """The run's time budget ran out before the call could be made."""


class BadPDFError(ValueError):
    """A user-supplied PDF is missing, too large, or not a PDF."""


def load_env(path: Path | None = None) -> None:
    """Read KEY=VALUE lines from the repo .env without overriding the real environment."""
    try:
        for line in (path or ROOT / ".env").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def get_api_key() -> str:
    load_env()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise MissingAPIKeyError(
            "GEMINI_API_KEY is not set. Export it, or put GEMINI_API_KEY=<key> in a local .env file "
            "(a Gemini Developer API key; Vertex AI is not used)."
        )
    return key


class Usage:
    """Thread-safe token and call counters for one run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.searches = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def add(self, meta: dict, searches: int = 0) -> None:
        with self._lock:
            self.calls += 1
            self.searches += searches
            self.tokens_in += int(meta.get("promptTokenCount", 0) or 0)
            self.tokens_out += int(meta.get("candidatesTokenCount", 0) or 0) + int(meta.get("thoughtsTokenCount", 0) or 0)


@dataclass
class Reply:
    text: str
    chunks: list[dict] = field(default_factory=list)    # grounding sources: {"uri", "title"}
    supports: list[dict] = field(default_factory=list)  # {"text", "end", "chunks": [index]}
    queries: list[str] = field(default_factory=list)
    finish: str = ""


class Gemini:
    def __init__(self, usage: Usage | None = None, deadline: float | None = None, model: str = MODEL) -> None:
        self.key = get_api_key()
        self.usage = usage or Usage()
        self.deadline = deadline
        self.model = model
        self.trace = None  # optional callable(name, **fields), the debug trail for every model call

    def _trace(self, name: str, **fields) -> None:
        if self.trace:
            try:
                self.trace(name, **fields)
            except Exception:  # noqa: BLE001 - tracing must never break a call
                pass

    def remaining(self) -> float:
        return float("inf") if self.deadline is None else self.deadline - time.time()

    def generate(self, prompt: str, *, system: str | None = None, parts: list[dict] | None = None,
                 json_mode: bool = False, grounded: bool = False, thinking: str = "off",
                 temperature: float = 0.2, timeout: float = 90.0, retries: int = 4,
                 deadline: float | None = None, label: str = "") -> Reply:
        """One generateContent call. thinking is 'off' or 'default'. Grounded calls use Google Search
        and cannot be combined with JSON mode, so ask for JSON in the prompt and use parse_json.
        deadline (epoch seconds) overrides the client's deadline for this call."""
        deadline = self.deadline if deadline is None else deadline
        cfg: dict = {"temperature": temperature}
        if json_mode and not grounded:
            cfg["responseMimeType"] = "application/json"
        if thinking == "off":
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
        body: dict = {"contents": [{"role": "user", "parts": [*(parts or []), {"text": prompt}]}],
                      "generationConfig": cfg}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if grounded:
            body["tools"] = [{"google_search": {}}]
        last: Exception = LLMError("no attempt made")
        for attempt in range(retries + 1):
            left = float("inf") if deadline is None else deadline - time.time()
            if left <= 2:
                raise BudgetExceeded("time budget exhausted")
            delay = min(20.0, 2 ** attempt + random.random())
            t_call = time.time()
            self._trace("model_call_start", label=label, grounded=grounded, attempt=attempt + 1)
            try:
                data = self._post(body, min(timeout, left))
                reply = self._parse(data)
                meta = data.get("usageMetadata") or {}
                self.usage.add(meta, searches=len(reply.queries))
                self._trace("model_call_end", label=label, seconds=round(time.time() - t_call, 2), attempt=attempt + 1,
                            tokens_in=int(meta.get("promptTokenCount", 0) or 0),
                            tokens_out=int(meta.get("candidatesTokenCount", 0) or 0) + int(meta.get("thoughtsTokenCount", 0) or 0),
                            searches=len(reply.queries), sources=len(reply.chunks), ok=bool(reply.text.strip()))
                if reply.text.strip():
                    return reply
                block = (data.get("promptFeedback") or {}).get("blockReason")
                if block:
                    raise LLMError(f"prompt blocked by Gemini: {block}")
                last = LLMError(f"empty response (finish={reply.finish or 'unknown'})")
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:400]
                self._trace("model_call_error", label=label, seconds=round(time.time() - t_call, 2), attempt=attempt + 1,
                            error=f"HTTP {e.code}")
                if e.code == 400 and "thinking" in msg.lower() and "thinkingConfig" in cfg:
                    del cfg["thinkingConfig"]
                    continue
                if e.code in (401, 403) or "API_KEY_INVALID" in msg or "API key not valid" in msg:
                    raise AuthError(f"Gemini API rejected GEMINI_API_KEY (HTTP {e.code}): {msg[:200]}") from None
                if e.code not in (429, 500, 502, 503, 504):
                    raise LLMError(f"Gemini API error HTTP {e.code}: {msg}") from None
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if retry_after and retry_after.isdigit():
                    delay = min(30.0, float(retry_after))
                last = LLMError(f"Gemini API HTTP {e.code}: {msg}")
            except (urllib.error.URLError, OSError) as e:
                self._trace("model_call_error", label=label, seconds=round(time.time() - t_call, 2), attempt=attempt + 1,
                            error=f"network {type(e).__name__}")
                last = LLMError(f"network error: {e}")
            time.sleep(max(0.0, min(delay, (float("inf") if deadline is None else deadline - time.time()) - 2)))
        raise last

    def json(self, prompt: str, **kw):
        """Ungrounded JSON-mode call, parsed. One re-ask on malformed JSON."""
        for _ in range(2):
            text = self.generate(prompt, json_mode=True, **kw).text
            try:
                return parse_json(text)
            except ValueError:
                prompt += "\n\nReturn ONLY valid JSON, nothing else."
        raise LLMError("model did not return valid JSON")

    def _post(self, body: dict, timeout: float) -> dict:
        req = urllib.request.Request(
            f"{API_ROOT}/{self.model}:generateContent", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        with urllib.request.urlopen(req, timeout=max(5.0, timeout)) as r:
            return json.loads(r.read())

    @staticmethod
    def _parse(data: dict) -> Reply:
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        gm = cand.get("groundingMetadata") or {}
        chunks = [{"uri": (c.get("web") or {}).get("uri", ""), "title": (c.get("web") or {}).get("title", "")}
                  for c in gm.get("groundingChunks") or []]
        supports = [{"text": (s.get("segment") or {}).get("text", ""), "end": (s.get("segment") or {}).get("endIndex", 0),
                     "chunks": s.get("groundingChunkIndices") or []} for s in gm.get("groundingSupports") or []]
        return Reply(text=text, chunks=chunks, supports=supports,
                     queries=list(gm.get("webSearchQueries") or []), finish=str(cand.get("finishReason", "")))


def parse_json(text: str):
    """Tolerant JSON parse: strips code fences, then takes the first decodable object or array."""
    t = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", t):
        try:
            return dec.raw_decode(t[m.start():])[0]
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON found")


def annotate(reply: Reply) -> str:
    """Return the grounded text with [n] markers after each supported segment (n = source index + 1)."""
    text = reply.text
    inserts: list[tuple[int, str]] = []
    for s in reply.supports:
        seg = s["text"]
        pos = text.find(seg) if seg else -1
        if pos >= 0 and s["chunks"]:
            inserts.append((pos + len(seg), "".join(f"[{i + 1}]" for i in sorted(set(s["chunks"])))))
    for end, marks in sorted(inserts, reverse=True):
        text = text[:end] + marks + text[end:]
    return text


def pdf_part(path: str | Path) -> dict:
    """Validate a local PDF and return it as a Gemini inline-data part."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise BadPDFError(f"{p.name}: file not found")
    data = p.read_bytes()
    if len(data) > 14_000_000:  # base64 adds a third and Gemini's inline request limit is 20 MB
        raise BadPDFError(f"{p.name}: larger than 14 MB")
    if b"%PDF-" not in data[:1024]:
        raise BadPDFError(f"{p.name}: not a PDF (no %PDF header)")
    if b"%%EOF" not in data[-2048:]:
        raise BadPDFError(f"{p.name}: truncated or damaged (no end-of-file marker)")
    if b"/Encrypt" in data[:8192] or b"/Encrypt" in data[-8192:]:
        raise BadPDFError(f"{p.name}: encrypted or password protected")
    return {"inlineData": {"mimeType": "application/pdf", "data": base64.b64encode(data).decode()}}


_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_DROP = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1>|<!-{2}.*?-{2}>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def resolve_redirect(url: str, timeout: float = 6.0) -> str:
    """Follow one redirect hop without downloading the target. Search grounding links redirect to the real page."""
    opener = urllib.request.build_opener(_NoRedirect)
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.geturl()
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and loc:
                return urllib.parse.urljoin(url, loc)
            if e.code == 429:
                time.sleep(1 + attempt)
                continue
            return url
        except Exception:  # noqa: BLE001 - best effort
            time.sleep(0.5)
    return url


def fetch_page(url: str, timeout: float = 10.0, max_bytes: int = 600_000) -> dict:
    """GET a page, following redirects. Returns url (final), ok, status, text (visible text), meta
    (author, date, site) and error. Never raises."""
    out = {"url": url, "ok": False, "status": None, "text": "", "meta": {}, "error": ""}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.5"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out.update(url=r.geturl(), status=r.status, ok=True)
            ctype = r.headers.get("Content-Type", "").lower()
            raw = r.read(2_500_000 if "pdf" in ctype else max_bytes)
            charset = re.search(r"charset=([\w-]+)", ctype)
    except urllib.error.HTTPError as e:
        out.update(url=e.geturl() or url, status=e.code, error=f"HTTP {e.code}")
        return out
    except Exception as e:  # noqa: BLE001 - fetching is best effort
        out["error"] = str(e)[:120]
        return out
    if raw[:5] == b"%PDF-":  # read the first pages with poppler's pdftotext when it is installed
        exe = shutil.which("pdftotext")
        if not exe:
            out["error"] = "PDF (pdftotext is not installed to read it)"
            return out
        try:
            p = subprocess.run([exe, "-l", "15", "-q", "-", "-"], input=raw, capture_output=True, timeout=25)
            out["text"] = re.sub(r"\s+", " ", p.stdout.decode("utf-8", "replace")).strip()
        except Exception as e:  # noqa: BLE001 - best effort
            out["error"] = f"PDF text extraction failed ({type(e).__name__})"
            return out
        out["ok"] = bool(out["text"])
        out["error"] = "" if out["ok"] else "PDF has no extractable text"
        return out
    if "html" not in ctype and "text" not in ctype:
        out["error"] = f"non-text content ({ctype.split(';')[0] or 'unknown'})"
        return out
    page = raw.decode(charset.group(1) if charset else "utf-8", "replace")
    meta: dict[str, str] = {}
    for tag in _META.findall(page):
        a = {k.lower(): (v1 or v2) for k, v1, v2 in _ATTR.findall(tag)}
        name = (a.get("name") or a.get("property") or a.get("itemprop") or "").lower()
        if name and a.get("content"):
            meta.setdefault(name, html.unescape(a["content"]).strip())
    date = (meta.get("article:published_time") or meta.get("citation_publication_date") or meta.get("datepublished")
            or meta.get("date") or meta.get("dc.date"))
    if not date:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', page)
        date = m.group(1) if m else ""
    out["meta"] = {
        "author": meta.get("author") or meta.get("citation_author") or meta.get("article:author") or "",
        "date": (date or "")[:25],
        "site": meta.get("og:site_name") or meta.get("citation_publisher") or meta.get("application-name") or "",
    }
    out["text"] = re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", _DROP.sub(" ", page)))).strip()
    return out
