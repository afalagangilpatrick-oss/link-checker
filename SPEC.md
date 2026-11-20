# linkcheck: check that web links actually work and are still active

A small Python 3 tool (standard library only) that takes links (from a text, markdown or CSV file, or typed in) and reports for each one
whether it works and is still current. Built for checking job-listing, grant and resource links, where a page can load fine but say
"this job has expired", or a site can show a bot check instead of the page.

## Package layout
- `linkcheck/__init__.py` (empty or a docstring)
- `linkcheck/core.py`: fetching and classifying one link (each module 8 KB or less)
- `linkcheck/cli.py`: pulling links out of files and the command line
- run as `python3 -m linkcheck.cli FILE [FILE ...]` (a FILE of `-` means standard input)

## linkcheck/core.py
- `STATUSES = ('live', 'redirected', 'expired', 'blocked', 'dead', 'error')`
- `fetch(url, timeout=20) -> (code: int, final_url: str, body: str)`: the default fetcher. urllib.request with a normal desktop browser
  User-Agent, follows redirects, reads at most 2 MB of the body, decodes as UTF-8 with errors ignored. On an HTTP error status it still returns
  `(code, url, body_of_error_page)`. It raises on timeouts and connection failures.
- `visible_text(body) -> str`: the page text a person would see: remove `<script>`, `<style>`, `<noscript>` and `<template>` elements with
  their contents and HTML comments, then all tags; unescape HTML entities; collapse whitespace. The `<title>` text stays (it is visible in the tab).
  Markers below are matched against `visible_text(body)` only, case-insensitive. Sites keep words like "no longer available" inside scripts
  for messages they are not showing, so matching the raw HTML gives false alarms.
- `classify(code, url, final_url, body) -> (status, reason)`, a pure function. Rules, applied in this order:
  1. **blocked**: `code` is 401, 403, 429 or 503 AND the body (case-insensitive) contains one of BLOCK_MARKERS:
     `just a moment`, `security check`, `not a robot`, `captcha`, `verify you are human`, `authenticating`, `request could not be satisfied`,
     `access denied`, `performing security verification`. Reason names the marker found.
  2. **dead**: `code` >= 400 (any other error status). Reason is `HTTP <code>`.
  3. **expired**: `code` < 400 AND the body contains one of EXPIRED_MARKERS: `this job has expired`, `job has expired`, `no longer available`,
     `no longer accepting applications`, `position has been filled`, `job not found`, `page not found`, `this posting has closed`,
     `posting is closed`. Reason names the marker found.
  4. **redirected**: `code` < 400 and `final_url` differs from `url` in host or path (ignore a trailing slash, the scheme, and the query string).
     Reason is `-> <final_url>`.
  5. **live**: everything else. Reason is `HTTP <code>`.
- `extract_title(body) -> str`: text of the first `<title>` element, HTML entities unescaped, whitespace collapsed, at most 120 characters, `''` if none.
- `check_url(url, fetch=None, timeout=20) -> dict` with keys `url`, `status`, `http_code`, `final_url`, `title`, `reason`.
  `fetch=None` means the module-level `fetch`, looked up at call time. If fetching raises, `status='error'`, `http_code=0`, `final_url=url`,
  `title=''`, `reason` = the exception class name plus message (at most 200 characters). Never raises.

## linkcheck/cli.py
- `extract_urls(text) -> list[str]`: every `http://` or `https://` link in the text, in first-seen order, no duplicates. Handles markdown links
  `[label](https://...)` (also with `)` inside the URL as in `Rockingham-County-(NH)`), angle-bracket links `<https://...>`, bare links, and CSV cells.
  Trailing `.`, `,`, `;`, `:`, `!`, `?`, `'`, `"` and an unbalanced trailing `)` or `]` are removed.
- `check_all(urls, fetch=None, workers=8) -> list[dict]`: runs `core.check_url` for each URL (a thread pool of `workers`), results in the same order as `urls`.
- `main(argv=None) -> int`:
  - positional FILE arguments (`-` = standard input); `--url URL` (repeatable) adds single links; `--json` prints one JSON array;
    `--csv` prints CSV with header `url,status,http_code,final_url,title,reason`; default prints one line per link:
    `STATUS  CODE  URL  reason` (status upper-case), then a summary line `N links: X live, Y redirected, ...` listing every status with a count.
  - `--workers N` (default 8), `--timeout S` (default 20).
  - Exit code: 0 when every link is live, redirected or blocked; 1 when any link is expired, dead or error; 2 for a usage error (no links found,
    unreadable file, bad option).
- The tests never fetch real pages: everything goes through an injected `fetch` callable.
