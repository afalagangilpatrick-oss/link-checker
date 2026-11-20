"""Contract tests for linkcheck/core.py (SPEC.md). Hermetic: every fetch is injected, nothing leaves the machine."""
import pytest

from linkcheck import core


def fake(code, final=None, body=''):
    def f(url, timeout=20):
        return code, final or url, body
    return f


def test_statuses_constant():
    assert core.STATUSES == ('live', 'redirected', 'expired', 'blocked', 'dead', 'error')


@pytest.mark.parametrize('code,body,status', [
    (200, '<title>Job</title>Apply now', 'live'),
    (200, 'Sorry, this job has expired on Indeed', 'expired'),
    (200, 'This position has been FILLED', 'expired'),
    (200, 'The page you requested: Page Not Found', 'expired'),
    (403, '<title>Just a moment...</title>', 'blocked'),
    (403, 'Security Check - Indeed.com', 'blocked'),
    (401, 'Authenticating...', 'blocked'),
    (403, 'ERROR: The request could not be satisfied', 'blocked'),
    (429, 'Please verify you are human', 'blocked'),
    (403, 'Forbidden', 'dead'),
    (404, 'Not Found', 'dead'),
    (410, '', 'dead'),
    (500, 'oops', 'dead'),
    (503, 'Service Unavailable', 'dead'),
])
def test_classify_rules(code, body, status):
    st, reason = core.classify(code, 'https://a.example/x', 'https://a.example/x', body)
    assert st == status
    assert isinstance(reason, str) and reason


def test_classify_blocked_beats_dead_and_names_marker():
    st, reason = core.classify(403, 'https://a.example/x', 'https://a.example/x', 'Performing security verification')
    assert st == 'blocked' and 'security verification' in reason.lower()


def test_classify_dead_reason_has_code():
    assert core.classify(404, 'https://a.example/x', 'https://a.example/x', '')[1] == 'HTTP 404'


def test_expired_only_when_page_loaded():
    # An error page that happens to say "no longer available" is dead, not expired.
    assert core.classify(404, 'https://a.example/x', 'https://a.example/x', 'no longer available')[0] == 'dead'


def test_redirect_rules():
    u = 'https://a.example/jobs/view/123'
    assert core.classify(200, u, 'https://a.example/jobs/search/', 'ok')[0] == 'redirected'
    assert core.classify(200, u, 'https://b.example/jobs/view/123', 'ok')[0] == 'redirected'
    # trailing slash, scheme and query string do not count as a redirect
    assert core.classify(200, u, 'https://a.example/jobs/view/123/', 'ok')[0] == 'live'
    assert core.classify(200, u, 'http://a.example/jobs/view/123?ref=x', 'ok')[0] == 'live'
    st, reason = core.classify(200, u, 'https://a.example/other', 'ok')
    assert reason == '-> https://a.example/other'


def test_expired_beats_redirect():
    assert core.classify(200, 'https://a.example/a', 'https://a.example/b', 'This job has expired')[0] == 'expired'


def test_markers_in_scripts_do_not_count():
    body = ('<html><head><title>Client Service Rep</title><script>var t={"msg":"This job is no longer available or has expired"};'
            '</script><style>.x:after{content:"page not found"}</style></head><body><!-- job has expired -->Apply now</body></html>')
    assert core.classify(200, 'https://a.example/v', 'https://a.example/v', body)[0] == 'live'
    blocked = '<html><head><title>Just a moment...</title><script>x()</script></head><body></body></html>'
    assert core.classify(403, 'https://a.example/v', 'https://a.example/v', blocked)[0] == 'blocked'


def test_visible_text():
    body = '<p>Hello&nbsp;<b>there</b></p><script>hidden_words()</script><noscript>nojs</noscript><template>tpl</template>'
    text = core.visible_text(body)
    assert 'Hello' in text and 'there' in text
    assert 'hidden_words' not in text and 'nojs' not in text and 'tpl' not in text
    assert core.visible_text('<title>T</title>  a \n\n b') == 'T a b'


def test_extract_title():
    assert core.extract_title('<html><head><title>\n  Nurse &amp; Aide  \n</title></head>') == 'Nurse & Aide'
    assert core.extract_title('<TITLE>Upper</TITLE>') == 'Upper'
    assert core.extract_title('no title here') == ''
    assert len(core.extract_title('<title>' + 'x' * 500 + '</title>')) == 120


def test_check_url_shape_and_values():
    r = core.check_url('https://a.example/j', fetch=fake(200, body='<title>Bus Driver</title>'))
    assert set(r) == {'url', 'status', 'http_code', 'final_url', 'title', 'reason'}
    assert r['status'] == 'live' and r['http_code'] == 200 and r['title'] == 'Bus Driver' and r['final_url'] == 'https://a.example/j'


def test_check_url_never_raises():
    def boom(url, timeout=20):
        raise TimeoutError('timed out after 20s')
    r = core.check_url('https://a.example/j', fetch=boom)
    assert r['status'] == 'error' and r['http_code'] == 0 and r['final_url'] == 'https://a.example/j'
    assert 'TimeoutError' in r['reason'] and len(r['reason']) <= 200


def test_check_url_uses_module_fetch_at_call_time(monkeypatch):
    monkeypatch.setattr(core, 'fetch', fake(404))
    assert core.check_url('https://a.example/j')['status'] == 'dead'


def test_check_url_passes_timeout():
    seen = {}

    def f(url, timeout=20):
        seen['t'] = timeout
        return 200, url, ''
    core.check_url('https://a.example/j', fetch=f, timeout=7)
    assert seen['t'] == 7
