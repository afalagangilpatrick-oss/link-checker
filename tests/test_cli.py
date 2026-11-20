"""Contract tests for linkcheck/cli.py (SPEC.md). Hermetic: core.fetch is replaced, nothing leaves the machine."""
import csv
import io
import json

import pytest

from linkcheck import cli, core

PAGES = {
    'https://ok.example/a': (200, 'https://ok.example/a', '<title>A</title>'),
    'https://ok.example/moved': (200, 'https://ok.example/new', 'x'),
    'https://old.example/job': (200, 'https://old.example/job', 'This job has expired'),
    'https://gone.example/x': (404, 'https://gone.example/x', ''),
    'https://bot.example/y': (403, 'https://bot.example/y', 'Just a moment...'),
}


def fake_fetch(url, timeout=20):
    if url not in PAGES:
        raise ConnectionError('no route')
    return PAGES[url]


@pytest.fixture(autouse=True)
def no_real_fetch(monkeypatch):
    monkeypatch.setattr(core, 'fetch', fake_fetch)


def test_extract_urls_markdown_bare_angle_and_dedupe():
    text = ('See [Bus](https://ok.example/a) and https://ok.example/a again. '
            'Also <https://gone.example/x>, then https://bot.example/y; done!\n'
            '| [Z](https://www.zip.example/c/Rockingham-County-(NH)/Job/x?jid=1&v=2) |')
    assert cli.extract_urls(text) == [
        'https://ok.example/a', 'https://gone.example/x', 'https://bot.example/y',
        'https://www.zip.example/c/Rockingham-County-(NH)/Job/x?jid=1&v=2']


def test_extract_urls_strips_trailing_punctuation_and_csv():
    text = 'name,url\nA,https://ok.example/a.\nB,"https://old.example/job",\n(see https://gone.example/x)'
    assert cli.extract_urls(text) == ['https://ok.example/a', 'https://old.example/job', 'https://gone.example/x']


def test_extract_urls_http_and_none():
    assert cli.extract_urls('http://plain.example/p') == ['http://plain.example/p']
    assert cli.extract_urls('no links at all, ftp://nope.example') == []


def test_check_all_keeps_order():
    urls = list(PAGES)[::-1]
    res = cli.check_all(urls, workers=3)
    assert [r['url'] for r in res] == urls
    assert {r['url']: r['status'] for r in res} == {
        'https://ok.example/a': 'live', 'https://ok.example/moved': 'redirected', 'https://old.example/job': 'expired',
        'https://gone.example/x': 'dead', 'https://bot.example/y': 'blocked'}


def test_main_default_output_and_exit_1(tmp_path, capsys):
    f = tmp_path / 'links.md'
    f.write_text('\n'.join(f'- {u}' for u in PAGES), encoding='utf-8')
    rc = cli.main([str(f)])
    out = capsys.readouterr().out
    assert rc == 1
    assert 'EXPIRED' in out and 'DEAD' in out and 'BLOCKED' in out and 'LIVE' in out and 'REDIRECTED' in out
    assert '5 links:' in out and '1 live' in out and '1 expired' in out


def test_main_exit_0_when_only_live_redirected_blocked(capsys):
    rc = cli.main(['--url', 'https://ok.example/a', '--url', 'https://bot.example/y', '--url', 'https://ok.example/moved'])
    assert rc == 0


def test_main_error_counts_as_failure(capsys):
    assert cli.main(['--url', 'https://unknown.example/z']) == 1
    assert 'ERROR' in capsys.readouterr().out


def test_main_json(capsys):
    rc = cli.main(['--json', '--url', 'https://gone.example/x', '--url', 'https://ok.example/a'])
    data = json.loads(capsys.readouterr().out)
    assert rc == 1 and [d['status'] for d in data] == ['dead', 'live']
    assert set(data[0]) == {'url', 'status', 'http_code', 'final_url', 'title', 'reason'}


def test_main_csv(capsys):
    cli.main(['--csv', '--url', 'https://ok.example/a'])
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0] == ['url', 'status', 'http_code', 'final_url', 'title', 'reason']
    assert rows[1][:3] == ['https://ok.example/a', 'live', '200']


def test_main_stdin(monkeypatch, capsys):
    monkeypatch.setattr('sys.stdin', io.StringIO('check https://ok.example/a'))
    assert cli.main(['-']) == 0


def test_main_usage_errors(tmp_path, capsys):
    empty = tmp_path / 'e.txt'
    empty.write_text('nothing here', encoding='utf-8')
    assert cli.main([str(empty)]) == 2
    assert cli.main([str(tmp_path / 'missing.txt')]) == 2
    assert cli.main([]) == 2
