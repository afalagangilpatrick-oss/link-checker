"""Command line interface for linkcheck (SPEC.md). Standard library only."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, List, Optional, Sequence

from . import core


def _clean_url(url: str) -> str:
    """Strip trailing punctuation and unbalanced trailing ) or ] per SPEC."""
    if not url:
        return url
    # Repeatedly strip trailing punctuation chars
    trailing_punct = set(".,;:!?'\"")
    changed = True
    while changed and url:
        changed = False
        # strip trailing punctuation
        while url and url[-1] in trailing_punct:
            url = url[:-1]
            changed = True
        # strip unbalanced trailing ) or ]
        if url and url[-1] == ")":
            # balanced if count of '(' in url >= count of ')'
            if url.count("(") < url.count(")"):
                url = url[:-1]
                changed = True
        if url and url[-1] == "]":
            if url.count("[") < url.count("]"):
                url = url[:-1]
                changed = True
    return url


def extract_urls(text: str) -> list[str]:
    """Return every http:// or https:// link in first-seen order, no duplicates."""
    if not text:
        return []
    seen = set()
    out: list[str] = []

    def add(u: str) -> None:
        u = _clean_url(u)
        if not u:
            return
        if u not in seen:
            seen.add(u)
            out.append(u)

    i = 0
    n = len(text)
    while i < n:
        # look for http:// or https://
        if text.startswith("https://", i) or text.startswith("http://", i):
            # extract candidate run: stop at whitespace or angle/quote chars that delimit
            j = i
            while j < n and not text[j].isspace() and text[j] not in '<>"\'':
                j += 1
            cand = text[i:j]
            add(cand)
            i = j
        else:
            i += 1
    return out


def check_all(
    urls: list[str],
    fetch: Optional[Callable] = None,
    workers: int = 8,
) -> list[dict]:
    """Run core.check_url for each URL, results in the same order as urls."""
    if not urls:
        return []
    # core.check_url signature: (url, fetch=None, timeout=20) but spec for check_all
    # doesn't take timeout; default 20 is fine. We must respect injected fetch if any.
    def run(u: str) -> dict:
        if fetch is None:
            return core.check_url(u)
        return core.check_url(u, fetch=fetch)

    with ThreadPoolExecutor(max_workers=max(1, int(workers or 1))) as ex:
        results = list(ex.map(run, urls))
    return results


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        raise IOError(f"cannot read {path}: {e}") from e


def _format_default(results: list[dict]) -> str:
    lines = []
    for r in results:
        status = str(r.get("status", "")).upper()
        code = r.get("http_code", 0)
        url = r.get("url", "")
        reason = r.get("reason", "")
        lines.append(f"{status}  {code}  {url}  {reason}")
    # summary: "N links: X live, Y redirected, ..." listing every status with a count
    counts = {s: 0 for s in core.STATUSES}
    for r in results:
        st = r.get("status")
        if st in counts:
            counts[st] += 1
        else:
            counts[st] = counts.get(st, 0) + 1
    n = len(results)
    parts = [f"{counts[s]} {s}" for s in core.STATUSES]
    lines.append(f"{n} links: " + ", ".join(parts))
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="linkcheck", add_help=True)
    parser.add_argument("files", nargs="*", help="Files to read (- for stdin)")
    parser.add_argument("--url", action="append", dest="urls", default=[])
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--csv", action="store_true", dest="as_csv")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=20)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse prints error/help; exit code 2 for usage errors
        code = e.code
        if code is None:
            return 2
        if isinstance(code, int):
            return 2 if code != 0 else 0
        return 2

    # Gather URLs
    collected: list[str] = []
    # from --url
    for u in (args.urls or []):
        collected.append(u)
    # from files/stdin
    texts: list[str] = []
    for path in args.files:
        try:
            texts.append(_read_input(path))
        except Exception:
            return 2
    for t in texts:
        collected.extend(extract_urls(t))

    # Deduplicate preserving order (and also normalize? --url given as-is but tests expect these exact urls)
    seen = set()
    urls: list[str] = []
    for u in collected:
        if u not in seen:
            seen.add(u)
            urls.append(u)

    if not urls:
        return 2

    # run checks
    # Need to honor --timeout; core.check_url takes timeout as third arg but
    # check_all signature in spec is (urls, fetch=None, workers=8). To pass timeout
    # we wrap: call core.check_url with timeout. But tests inject fetch via monkeypatching core.fetch
    # and call check_all without timeout. For main, pass timeout through.
    def run_with_timeout(url: str) -> dict:
        # lookup module-level fetch at call time as core.check_url does
        return core.check_url(url, fetch=None, timeout=args.timeout)

    if not urls:
        return 2
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers or 1))) as ex:
        results = list(ex.map(run_with_timeout, urls))

    # output
    if args.as_json:
        print(json.dumps(results))
    elif args.as_csv:
        buf = io.StringIO()
        fieldnames = ["url", "status", "http_code", "final_url", "title", "reason"]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
        sys.stdout.write(buf.getvalue())
    else:
        sys.stdout.write(_format_default(results))

    # exit code: 0 when every link is live, redirected or blocked; 1 when any expired, dead or error
    for r in results:
        if r.get("status") in ("expired", "dead", "error"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
