"""Browser regression tests for gate 3 (qa-gates/touch-target-check.sh).

These run the real gate against local fixture pages in a real Chromium, so
they need a browser: set TOUCH_TARGET_CHROME to a Chrome/Chromium binary and
have the playwright Python package installed. Without either, every test here
is skipped (the rest of the suite does not need a browser).
"""

import http.server
import importlib.util
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "qa-gates" / "touch-target-check.sh"
CHROME = os.environ.get("TOUCH_TARGET_CHROME", "")

AVAILABLE = bool(CHROME and os.access(CHROME, os.X_OK)
                 and importlib.util.find_spec("playwright") and shutil.which("bash"))
# CI sets GATE3_BROWSER_REQUIRED=1: there a missing browser must fail the job,
# never turn every test into a silent skip and a green run.
REQUIRED = os.environ.get("GATE3_BROWSER_REQUIRED") == "1"

pytestmark = pytest.mark.skipif(
    not AVAILABLE and not REQUIRED,
    reason="needs TOUCH_TARGET_CHROME (a Chrome/Chromium binary) and playwright",
)


def test_browser_is_available() -> None:
    assert AVAILABLE, ("gate 3 browser tests required but unavailable: TOUCH_TARGET_CHROME=%r, "
                       "playwright importable=%s" % (CHROME, bool(importlib.util.find_spec("playwright"))))

HITS: list[str] = []
BTN = '<button style="width:60px;height:60px">%s</button>'
SMALL = '<button style="width:20px;height:20px">small</button>'

# A page that really routes by #page=<name>&lang=<lang>: each route renders a
# different number of buttons, so every route has a distinct layout.
HASH_PAGE = """<html><body><div id=r></div><script>
function draw() {
  var m = /page=(\\w+)&lang=(\\w+)/.exec(location.hash) || [0, 'home', 'zh'];
  var n = ({home: 1, catalog: 2}[m[1]] || 3) + (m[2] == 'en' ? 2 : 0);
  var h = '';
  for (var i = 0; i < n; i++) h += '<button style="width:60px;height:60px">b' + i + '</button>';
  document.getElementById('r').innerHTML = h + EXTRA;
}
var EXTRA = '%s';
window.addEventListener('hashchange', draw); draw();
</script>%s</body></html>"""


def _hash_page(extra: str = "", tail: str = "") -> str:
    return HASH_PAGE % (extra, tail)


def _gate(target: str, routes: str, allow: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "TOUCH_TARGET_PYTHON": sys.executable,
           "TOUCH_TARGET_CHROME": CHROME, "TOUCH_TARGET_ROUTES": routes,
           "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1",
           "QA_EGRESS_ALLOW_HOSTS": allow}
    return subprocess.run(["bash", str(GATE), target], capture_output=True, text=True,
                          env=env, check=False, timeout=300)


def _file(tmp_path: Path, html: str) -> str:
    page = tmp_path / "index.html"
    page.write_text(html, encoding="utf-8")
    return page.as_uri()


@pytest.fixture
def site(tmp_path: Path):
    """Local HTTP server: /, /b/ are pages; /500 answers HTTP 500; else 404.

    /redir-nav and /redir-img answer 302 to the same server under the name
    "localhost" (not exempted in tests); /img-page/ embeds /redir-img. Every
    request's Host header is appended to HITS.
    """
    for sub, label in (("", "home"), ("b", "b")):
        d = tmp_path / "site" / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            "<html><body>%s%s</body></html>" % (BTN % label, BTN % (label + "2") * len(sub)),
            encoding="utf-8")
    root = tmp_path / "site"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a: object, **kw: object) -> None:
            super().__init__(*a, directory=str(root), **kw)

        def do_GET(self) -> None:
            HITS.append("%s %s" % (self.headers.get("Host"), self.path))
            port = self.server.server_address[1]
            if self.path in ("/redir-nav", "/redir-img"):
                self.send_response(302)
                self.send_header("Location", "http://localhost:%d/b/" % port)
                self.end_headers()
                return
            if self.path == "/img-page/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(("<html><body>%s<img src=/redir-img></body></html>"
                                  % (BTN % "img")).encode())
                return
            if self.path.startswith("/500"):
                self.send_response(500)
                self.end_headers()
                self.wfile.write((BTN % "err").encode())
                return
            super().do_GET()

        def log_message(self, *args: object) -> None:
            pass

    HITS.clear()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def test_passes_hash_routed_page(tmp_path: Path) -> None:
    res = _gate(_file(tmp_path, _hash_page()), "home catalog")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "RESULT: [PASS]" in res.stdout


def test_fails_small_touch_target(tmp_path: Path) -> None:
    res = _gate(_file(tmp_path, _hash_page(extra=SMALL)), "home catalog")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "touch target < 44x44" in res.stdout and "20.0x20.0" in res.stdout


def test_inline_and_off_page_links_are_not_violations(tmp_path: Path) -> None:
    extra = ('<p>text <a href=#x>inline</a> text</p>'
             '<a href=#main style="position:absolute;left:-9999px;'
             'display:block;width:20px;height:20px">skip</a>')
    res = _gate(_file(tmp_path, _hash_page(extra=extra)), "home catalog")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "[EXEMPT]" in res.stdout  # inline link is listed, not counted


def test_fails_when_routes_render_identical_layouts(tmp_path: Path) -> None:
    # a static page ignores #page= routing: the gate would measure one page N times
    res = _gate(_file(tmp_path, "<html><body>%s</body></html>" % (BTN % "x")), "home catalog")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "identical interactive layout" in res.stdout


def test_fails_on_blank_page(tmp_path: Path) -> None:
    res = _gate(_file(tmp_path, "<html><body><p>nothing to tap</p></body></html>"), "home")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "0 interactive elements" in res.stdout


def test_fails_on_page_js_error(tmp_path: Path) -> None:
    res = _gate(_file(tmp_path, _hash_page(tail="<script>null.boom</script>")), "home catalog")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "JS error" in res.stdout


def test_passes_path_routes_over_http(site: str) -> None:
    res = _gate(site + "/", "/ /b/", allow="127.0.0.1")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "total checked=" in res.stdout


def test_fails_on_http_404_route(site: str) -> None:
    res = _gate(site + "/", "/ /missing/", allow="127.0.0.1")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "HTTP 404" in res.stdout


def test_fails_on_http_500(site: str) -> None:
    res = _gate(site + "/500", "home", allow="127.0.0.1")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "HTTP 500" in res.stdout


# ---- SEC-A2: every outbound hop is address-checked ----

def test_blocks_loopback_target_without_exemption(site: str) -> None:
    res = _gate(site + "/", "/ /b/")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "egress blocked (SEC-A2)" in res.stdout and "non-public" in res.stdout


def test_blocks_private_subresource_from_file_page(tmp_path: Path, site: str) -> None:
    # a page under test must not be able to make the gate fetch internal addresses
    tail = '<img src="%s/b/">' % site
    res = _gate(_file(tmp_path, _hash_page(tail=tail)), "home catalog")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "egress blocked (SEC-A2)" in res.stdout and "127.0.0.1" in res.stdout


def test_blocks_metadata_address_subresource(tmp_path: Path) -> None:
    tail = '<img src="http://169.254.169.254/latest/meta-data/">'
    res = _gate(_file(tmp_path, _hash_page(tail=tail)), "home catalog")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "169.254.169.254" in res.stdout and "non-public" in res.stdout


def test_exemption_is_logged(site: str) -> None:
    res = _gate(site + "/", "/ /b/", allow="127.0.0.1")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "[egress] 127.0.0.1 exempted" in res.stderr


def test_navigation_redirect_fails_and_is_not_followed(site: str) -> None:
    res = _gate(site + "/", "/redir-nav", allow="127.0.0.1")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "navigation redirected (HTTP 302" in res.stdout
    assert not [h for h in HITS if h.startswith("localhost")], HITS


def test_subresource_redirect_to_blocked_host_never_connects(site: str) -> None:
    # Playwright routes only the first hop of a redirect chain; the gate must still
    # check the hop to "localhost" before any request reaches it
    res = _gate(site + "/", "/img-page/ /b/", allow="127.0.0.1")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "egress blocked (SEC-A2): redirect" in res.stdout
    assert not [h for h in HITS if h.startswith("localhost")], HITS
