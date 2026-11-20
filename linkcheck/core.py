"""Fetching and classifying one link (SPEC.md). Standard library only."""
from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from typing import Callable, Optional, Tuple
from urllib.parse import urlparse

STATUSES = ("live", "redirected", "expired", "blocked", "dead", "error")

BLOCK_MARKERS = (
    "just a moment",
    "security check",
    "not a robot",
    "captcha",
    "verify you are human",
    "authenticating",
    "request could not be satisfied",
    "access denied",
    "performing security verification",
)

EXPIRED_MARKERS = (
    "this job has expired",
    "job has expired",
    "no longer available",
    "no longer accepting applications",
    "position has been filled",
    "job not found",
    "page not found",
    "this posting has closed",
    "posting is closed",
    "this job has closed",
    "job has closed",
    "this job is closed",
    "job is no longer open",
)


def _strip_script_style_noscript_template_comments(text: str) -> str:
    # Remove script/style/noscript/template blocks and HTML comments.
    text = re.sub(r"(?is)<(script|style|noscript|template)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?is)<!--.*?-->", "", text)
    return text


def visible_text(body: str) -> str:
    if not body:
        return ""
    s = _strip_script_style_noscript_template_comments(body)
    # Remove all tags
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_title(body: str) -> str:
    if not body:
        return ""
    m = re.search(r"(?is)<title\b[^>]*>(.*?)</title>", body)
    if not m:
        return ""
    t = html.unescape(m.group(1))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > 120:
        t = t[:120]
    return t


def _norm_host_path(u: str) -> Tuple[str, str]:
    try:
        p = urlparse(u)
        host = (p.netloc or "").lower()
        path = p.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return host, path
    except Exception:
        return "", ""


def classify(code: int, url: str, final_url: str, body: str) -> Tuple[str, str]:
    # Rule 1: blocked
    if code in (401, 403, 429, 503):
        vt = visible_text(body).lower()
        for mk in BLOCK_MARKERS:
            if mk in vt:
                return ("blocked", mk)
        # If not matched by markers, treat as dead per test cases (403 Forbidden -> dead)
        # fall through to rule 2
    # Rule 2: dead (code >= 400)
    if code >= 400:
        return ("dead", f"HTTP {code}")
    # Rule 3: expired (code < 400) -- check visible text markers
    vt = visible_text(body).lower()
    for mk in EXPIRED_MARKERS:
        if mk in vt:
            return ("expired", mk)
    # Rule 4: redirected (host or path differs, ignore trailing slash, scheme, query)
    h1, p1 = _norm_host_path(url)
    h2, p2 = _norm_host_path(final_url)
    if h1 != h2 or p1 != p2:
        return ("redirected", f"-> {final_url}")
    # Rule 5: live
    return ("live", f"HTTP {code}")


FetchFunc = Callable[[str, int], Tuple[int, str, str]]


def fetch(url: str, timeout: int = 20) -> Tuple[int, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = int(getattr(resp, "status", 200))
            final_url = resp.geturl() or url
            raw = resp.read(2 * 1024 * 1024)  # 2 MB
            body = raw.decode("utf-8", errors="ignore")
            return code, final_url, body
    except urllib.error.HTTPError as e:
        code = int(getattr(e, "code", 0) or 0)
        final_url = getattr(e, "url", None) or url
        try:
            raw = e.read(2 * 1024 * 1024)
        except Exception:
            raw = b""
        body = raw.decode("utf-8", errors="ignore") if raw else ""
        return code, final_url, body
    except Exception:
        raise


def check_url(
    url: str,
    fetch: Optional[FetchFunc] = None,
    timeout: int = 20,
) -> dict:
    if fetch is None:
        fetch = globals()["fetch"]
    try:
        code, final_url, body = fetch(url, timeout)
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        if len(reason) > 200:
            reason = reason[:200]
        return {
            "url": url,
            "status": "error",
            "http_code": 0,
            "final_url": url,
            "title": "",
            "reason": reason,
        }
    title = extract_title(body)
    status, reason = classify(code, url, final_url, body)
    return {
        "url": url,
        "status": status,
        "http_code": code,
        "final_url": final_url,
        "title": title,
        "reason": reason,
    }
