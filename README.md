# linkcheck

Check that web links actually work and are still current. Built for job-listing, grant and
resource links, where a page can load fine but say "this job has expired", or a site shows a
bot check instead of the page. Python 3, standard library only.

```bash
python3 -m linkcheck.cli links.md            # links from a text, markdown or CSV file
python3 -m linkcheck.cli --url https://example.com/job/123
python3 -m linkcheck.cli links.md --json     # or --csv
cat links.txt | python3 -m linkcheck.cli -
```

Each link gets one status:

| Status | Meaning |
|---|---|
| `live` | loads and looks current |
| `redirected` | ends up at a different page |
| `expired` | loads, but the visible text says the posting is closed / no longer available |
| `blocked` | a bot check (Cloudflare etc.); open it yourself |
| `dead` | HTTP error |
| `error` | timeout or connection failure |

Expiry markers are matched against the page's *visible* text only (scripts, styles and comments
removed), which avoids false alarms from hidden strings. Full behaviour: [SPEC.md](SPEC.md).

Tests: `python3 -m pytest -q`

License: MIT.
