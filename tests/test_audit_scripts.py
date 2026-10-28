"""Smoke tests for the existing audit scripts and data-room gate.

These exercise real behavior of the scripts as committed; they do not touch
production paths. Python scripts are loaded by file path because their file
names contain hyphens.
"""

import hashlib
import importlib.util
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SW = ROOT / "security-watch"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SW / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


color_audit = _load("color_audit", "color-audit.py")
shadow_audit = _load("shadow_audit", "shadow-audit.py")


# ---- color-audit.py ----

def test_canonical_hex_expands_short_form() -> None:
    assert color_audit.canonical_hex("#FFF") == ("#ffffff", 255, 255, 255, 1.0)


def test_canonical_hex_with_alpha_becomes_rgba() -> None:
    key, r, g, b, a = color_audit.canonical_hex("#00000080")
    assert key == "rgba(0, 0, 0, 0.502)"
    assert (r, g, b, a) == (0, 0, 0, 0.502)


def test_parse_func_rgb_and_hsl_normalise_to_hex() -> None:
    assert color_audit.parse_func("rgb", "255, 71, 19")[0] == "#ff4713"
    assert color_audit.parse_func("hsl", "0, 100%, 50%")[0] == "#ff0000"
    assert color_audit.parse_func("rgba", "0, 0, 0, 0.5")[0] == "rgba(0, 0, 0, 0.5)"


def test_audit_extracts_colors_with_line_numbers(tmp_path: Path) -> None:
    html = tmp_path / "index.html"
    html.write_text(
        "<html><head><style>\n"
        "/* #123456 in a comment is ignored */\n"
        "a { color: #FF4713; }\n"
        "@media (max-width: 390px) {\n"
        "  b { background: rgb(255, 71, 19); }\n"
        "}\n"
        "</style></head>\n"
        '<body><p style="color: #000">x</p></body></html>\n',
        encoding="utf-8",
    )
    records, nblocks = color_audit.audit(str(html))
    assert nblocks == 1
    keys = [(r["key"], r["line"]) for r in records]
    assert keys == [("#ff4713", 3), ("#ff4713", 5), ("#000000", 8)]
    assert records[1]["selector"].startswith("@media")
    assert records[2]["selector"].startswith("style-attr")


# ---- shadow-audit.py ----

def test_shadow_parse_rules_tracks_media() -> None:
    css = "a{box-shadow:none}@media (min-width:1px){b{box-shadow:0 0 1px #000}}"
    rules = shadow_audit.parse_rules(css)
    assert [(r["selector"], r["media"]) for r in rules] == [
        ("a", None),
        ("b", "@media (min-width:1px)"),
    ]


# ---- data-room-gate.sh ----

def _run_gate(
    tmp_path: Path,
    data_dir: Path,
    allowlist: str | None = "",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a copy of the gate whose sibling allowlist holds `allowlist`.

    The gate resolves its allowlist and its skeleton pattern set next to the
    script, so each test gets its own copies instead of touching the committed
    security-watch files. allowlist=None means the allowlist file exists but is
    unreadable. env entries are merged over os.environ (pattern-set loading).
    """
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir(exist_ok=True)
    script = gate_dir / "data-room-gate.sh"
    shutil.copy(SW / "data-room-gate.sh", script)
    shutil.copy(SW / "gate-patterns-skeleton.txt", gate_dir / "gate-patterns-skeleton.txt")
    al = gate_dir / "gate-allowlist.txt"
    al.write_text(allowlist or "", encoding="utf-8")
    if allowlist is None:
        al.chmod(0)
    return subprocess.run(
        ["bash", str(script), str(data_dir)],
        capture_output=True, text=True, check=False,
        # skeleton runs exit 3 (NON-BINDING) unless explicitly allowed; tests opt in
        env={**os.environ, "GATE_ALLOW_SKELETON": "1", **(env or {})},
    )


def _data(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    data = tmp_path / "data-room"
    data.mkdir(exist_ok=True)
    for name, content in files.items():
        f = data / name
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            f.write_bytes(content)
        else:
            f.write_text(content, encoding="utf-8")
    return data


needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
not_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can read chmod 000 files"
)
CLEAN = "Classification: Public\nhello\n"


@needs_bash
def test_gate_passes_clean_dir(tmp_path: Path) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}))
    assert res.returncode == 0, res.stdout
    assert "结果：PASS" in res.stdout


@needs_bash
def test_gate_fails_on_token(tmp_path: Path) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": "key ghp_" + "x" * 20 + "\n"}))
    assert res.returncode == 1
    assert "GATE FAIL" in res.stdout
    assert "x" * 20 not in res.stdout  # token is masked in output


@needs_bash
def test_gate_fails_on_missing_dir(tmp_path: Path) -> None:
    res = _run_gate(tmp_path, tmp_path / "nope")
    assert res.returncode == 1
    assert "目录不存在" in res.stdout


@needs_bash
@not_root
def test_gate_fails_closed_on_unreadable_allowlist(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": "PLACEHOLDERWORD\n"})
    res = _run_gate(tmp_path, data, allowlist=None)
    assert res.returncode == 1
    assert "不可读" in res.stdout


@needs_bash
def test_gate_blank_allowlist_line_does_not_exempt_everything(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": "PLACEHOLDERWORD\n"})
    res = _run_gate(tmp_path, data, allowlist="foo\n\n   \n")
    assert res.returncode == 1, res.stdout


@needs_bash
def test_gate_allowlist_needs_exact_path_and_line(tmp_path: Path) -> None:
    data = _data(tmp_path, {"notes.txt": "ok\nPLACEHOLDERWORD\n"})
    # a bare file name (old substring semantics) or the wrong line exempts nothing
    assert _run_gate(tmp_path, data, allowlist="notes.txt\n").returncode == 1
    assert _run_gate(tmp_path, data, allowlist="notes.txt:2\n").returncode == 1
    assert _run_gate(tmp_path, data, allowlist="notes.txt:1:PLACEHOLDERWORD\n").returncode == 1
    res = _run_gate(tmp_path, data, allowlist="# reviewed\nnotes.txt:2:PLACEHOLDERWORD\n")
    assert res.returncode == 0, res.stdout


@needs_bash
@pytest.mark.parametrize("name", ["a.md", "b.json", "c.html", "d.csv", "nested/e"])
def test_gate_scans_non_txt_files(tmp_path: Path, name: str) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {name: "PLACEHOLDERWORD\n"}))
    assert res.returncode == 1, res.stdout


@needs_bash
def test_gate_private_key_in_pem_fails(tmp_path: Path) -> None:
    key = "-----BEGIN RSA PRIVATE KEY-----"
    data = _data(tmp_path, {"k.pem": key + "\n"})
    res = _run_gate(tmp_path, data, allowlist="k.pem:1:" + key + "\n")  # not allowlistable
    assert res.returncode == 1
    assert "私钥块" in res.stdout


@needs_bash
def test_gate_fails_on_empty_dir(tmp_path: Path) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {}))
    assert res.returncode == 1
    assert "文件数为 0" in res.stdout


@needs_bash
def test_gate_binary_file_fails_until_reviewed(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": CLEAN, "x.pdf": b"%PDF-1.4\x00\x01binary"})
    res = _run_gate(tmp_path, data)
    assert res.returncode == 1
    assert "x.pdf: [二进制" in res.stdout
    digest = hashlib.sha256((data / "x.pdf").read_bytes()).hexdigest()
    assert _run_gate(tmp_path, data, allowlist="bin:x.pdf:" + digest + "\n").returncode == 0
    # the entry is bound to the file's content: any edit makes it stale
    (data / "x.pdf").write_bytes(b"%PDF-1.4\x00\x02changed")
    assert _run_gate(tmp_path, data, allowlist="bin:x.pdf:" + digest + "\n").returncode == 1


@needs_bash
@not_root
def test_gate_unreadable_file_fails(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": CLEAN, "b.txt": "PLACEHOLDERWORD\n"})
    (data / "b.txt").chmod(0)
    res = _run_gate(tmp_path, data)
    assert res.returncode == 1
    assert "扫描过程出错" in res.stdout


@needs_bash
@pytest.mark.parametrize("line", [
        "github_pat_11ABCDEFG0123456789_abcdefghij",
    "ghs_" + "a" * 20,
    "sk-ant-api03-" + "A" * 12,
])
def test_gate_detection_variants(tmp_path: Path, line: str) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": line + "\n"}))
    assert res.returncode == 1, res.stdout


@needs_bash
@pytest.mark.parametrize("line", [
    "launch 1955-11",
    "launch 1955/11",
    "launch 1955.11",
    "launch 1955年11月",
    "launch Nov 1955",
    "launch November 1955",
    "Classification: PLACEHOLDERWORD",
])
def test_gate_skeleton_detection_variants(tmp_path: Path, line: str) -> None:
    # The committed pattern set is a synthetic skeleton (two-tier form): these
    # variants exercise the same shapes the deployment-side full set enforces.
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": line + "\n"}))
    assert res.returncode == 1, res.stdout
    assert "非约束性" in res.stdout


def _full_pattern_set(tmp_path: Path) -> tuple[Path, str]:
    """Build a test-local full pattern set from the skeleton.

    Rules 1 and 2 are swapped for test-local synthetic values, so the loader
    and fingerprint paths run end to end without any production pattern.
    """
    text = (SW / "gate-patterns-skeleton.txt").read_text(encoding="utf-8")
    lines = []
    for ln in text.splitlines():
        if ln.startswith("1.pattern "):
            ln = ("1.pattern 2031[-/.][[:space:]]*0?7|2031[[:space:]]*年"
                  "[[:space:]]*0?7[[:space:]]*月|jul(y)?\\.?[[:space:]]*2031")
        elif ln.startswith("2.pattern "):
            ln = "2.pattern TESTSTOPWORD"
        lines.append(ln)
    pf = tmp_path / "patterns-full.txt"
    pf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return pf, hashlib.sha256(pf.read_bytes()).hexdigest()


@needs_bash
@pytest.mark.parametrize("line", [
    "launch 2031-07",
    "launch 2031/07",
    "launch 2031.7",
    "launch 2031年7月",
    "launch Jul 2031",
    "launch July 2031",
    "Classification: TESTSTOPWORD",
])
def test_gate_full_set_detection_variants(tmp_path: Path, line: str) -> None:
    pf, fp = _full_pattern_set(tmp_path)
    env = {"GATE_PATTERN_FILE": str(pf), "GATE_PATTERN_SHA256": fp}
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": line + "\n"}), env=env)
    assert res.returncode == 1, res.stdout
    assert "指纹验真通过" in res.stdout


@needs_bash
def test_gate_full_set_clean_dir_passes(tmp_path: Path) -> None:
    pf, fp = _full_pattern_set(tmp_path)
    env = {"GATE_PATTERN_FILE": str(pf), "GATE_PATTERN_SHA256": fp}
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}), env=env)
    assert res.returncode == 0, res.stdout
    assert "结果：PASS" in res.stdout


@needs_bash
def test_gate_full_set_fingerprint_via_file(tmp_path: Path) -> None:
    pf, fp = _full_pattern_set(tmp_path)
    fp_file = tmp_path / "patterns.sha256"
    fp_file.write_text(fp + "\n", encoding="utf-8")
    env = {"GATE_PATTERN_FILE": str(pf), "GATE_PATTERN_FP_FILE": str(fp_file)}
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}), env=env)
    assert res.returncode == 0, res.stdout
    assert "指纹验真通过" in res.stdout


@needs_bash
def test_gate_full_set_wrong_fingerprint_fails_closed(tmp_path: Path) -> None:
    pf, _fp = _full_pattern_set(tmp_path)
    env = {"GATE_PATTERN_FILE": str(pf), "GATE_PATTERN_SHA256": "0" * 64}
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}), env=env)
    assert res.returncode == 1
    assert "指纹不符" in res.stdout


@needs_bash
def test_gate_full_set_without_fingerprint_fails_closed(tmp_path: Path) -> None:
    pf, _fp = _full_pattern_set(tmp_path)
    env = {"GATE_PATTERN_FILE": str(pf)}
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}), env=env)
    assert res.returncode == 1
    assert "未提供登记指纹" in res.stdout


@needs_bash
def test_gate_pattern_file_missing_fails_closed(tmp_path: Path) -> None:
    env = {"GATE_PATTERN_FILE": str(tmp_path / "nope.txt"),
           "GATE_PATTERN_SHA256": "0" * 64}
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}), env=env)
    assert res.returncode == 1
    assert "模式集缺失或不可读" in res.stdout


@needs_bash
def test_gate_reports_location_not_content(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": "db password=Hunter2SuperSecretValue\nPLACEHOLDERWORD plan\n"})
    res = _run_gate(tmp_path, data)
    assert res.returncode == 1
    assert "a.txt:1" in res.stdout and "a.txt:2" in res.stdout
    assert "Hunter2SuperSecretValue" not in res.stdout
    assert "plan" not in res.stdout


# ---- color-audit.py edge cases ----

def test_parse_func_clamps_out_of_range_components() -> None:
    assert color_audit.parse_func("rgb", "300, -5, 19")[0] == "#ff0013"
    assert color_audit.parse_func("rgba", "0, 0, 0, 1.5")[0] == "#000000"


def test_color_audit_json_flag_without_path_is_usage_error(tmp_path: Path) -> None:
    html = tmp_path / "index.html"
    html.write_text("<style>a{color:#fff}</style>", encoding="utf-8")
    res = subprocess.run(
        ["python3", str(SW / "color-audit.py"), str(html), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 1
    assert "Traceback" not in res.stderr
# ---- data-room-gate.sh fail-closed regressions (issue #6) ----

def _run_gate_copy(
    tmp_path: Path, allowlist: str | None, files: dict[str, str]
) -> subprocess.CompletedProcess:
    """Run a scratch copy of the gate whose allowlist sits beside the script."""
    base = tmp_path / ("run-" + uuid.uuid4().hex[:8])
    gate_dir = base / "gate"
    gate_dir.mkdir(parents=True)
    shutil.copy(SW / "data-room-gate.sh", gate_dir / "data-room-gate.sh")
    shutil.copy(SW / "gate-patterns-skeleton.txt", gate_dir / "gate-patterns-skeleton.txt")
    if allowlist is not None:
        (gate_dir / "gate-allowlist.txt").write_text(allowlist, encoding="utf-8")
    data = base / "data-room"
    data.mkdir()
    for name, text in files.items():
        (data / name).write_text(text, encoding="utf-8")
    env = {**os.environ, "TMPDIR": str(base), "GATE_ALLOW_SKELETON": "1"}
    return subprocess.run(
        ["bash", str(gate_dir / "data-room-gate.sh"), str(data)],
        capture_output=True, text=True, env=env, check=False,
    )


@needs_bash
def test_gate_fails_when_allowlist_missing(tmp_path: Path) -> None:
    res = _run_gate_copy(tmp_path, None, {"a.txt": "hello\n"})
    assert res.returncode == 1
    assert "allowlist" in res.stdout


@needs_bash
def test_gate_fails_when_no_txt_files(tmp_path: Path) -> None:
    # issue #5: non-.txt files are scanned now, so the token itself is caught
    res = _run_gate_copy(tmp_path, "", {"secret.md": "ghp_" + "y" * 30 + "\n"})
    assert res.returncode == 1
    assert "命中疑似密钥 token" in res.stdout


@needs_bash
def test_gate_blank_allowlist_lines_do_not_suppress(tmp_path: Path) -> None:
    res = _run_gate_copy(
        tmp_path, "\n   \n# comment\n", {"a.txt": "key ghp_" + "x" * 30 + "\n"}
    )
    assert res.returncode == 1
    assert "GATE FAIL" in res.stdout


@needs_bash
def test_gate_substring_allowlist_entry_does_not_suppress(tmp_path: Path) -> None:
    res = _run_gate_copy(tmp_path, "t\n", {"a.txt": "key ghp_" + "x" * 30 + "\n"})
    assert res.returncode == 1
    assert "GATE FAIL" in res.stdout


@needs_bash
def test_gate_exact_allowlist_entry_suppresses_only_its_instance(
    tmp_path: Path,
) -> None:
    line = "key ghp_" + "x" * 30
    entry = "a.txt:1:" + line + "\n"
    res = _run_gate_copy(tmp_path, entry, {"a.txt": line + "\n"})
    assert res.returncode == 0, res.stdout
    assert "结果：PASS" in res.stdout
    res2 = _run_gate_copy(
        tmp_path, entry, {"a.txt": line + "\n", "b.txt": line + "\n"}
    )
    assert res2.returncode == 1
    assert "b.txt" in res2.stdout


@needs_bash
def test_gate_redacts_password_value(tmp_path: Path) -> None:
    secret = "Sup3rSecretValue"
    res = _run_gate_copy(tmp_path, "", {"a.txt": "db password = " + secret + "\n"})
    assert res.returncode == 0, res.stdout
    assert "GATE WARN" in res.stdout
    assert secret not in res.stdout
    assert secret not in res.stderr


# ---- skeleton runs must never read as a release pass (issue #5 re-check) ----

@needs_bash
def test_gate_skeleton_run_is_non_binding_not_pass(tmp_path: Path) -> None:
    # without GATE_PATTERN_FILE the date/keyword rules are synthetic placeholders,
    # so a clean-looking result must not exit 0 and be taken for a release pass
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}),
                    env={"GATE_ALLOW_SKELETON": "0"})
    assert res.returncode == 3, res.stdout
    assert "NON-BINDING" in res.stdout
    assert "结果：PASS" not in res.stdout


@needs_bash
def test_gate_skeleton_run_still_fails_on_real_rules(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": "key ghp_" + "x" * 20 + "\n"})
    res = _run_gate(tmp_path, data, env={"GATE_ALLOW_SKELETON": "0"})
    assert res.returncode == 1, res.stdout

# ---- qa-gates/homepage-200-check.sh (gate 2) ----

QA = ROOT / "qa-gates"
needs_curl = pytest.mark.skipif(shutil.which("curl") is None, reason="curl not available")


@pytest.fixture
def http_server():
    """Local server answering GET /<code> with that HTTP status."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            code = int(self.path.strip("/") or "200")
            self.send_response(code)
            if 300 <= code < 400:
                self.send_header("Location", "/200")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def _run_gate2(url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1",
           "HOMEPAGE_CHECK_TIMEOUT": "5"}
    return subprocess.run(
        ["bash", str(QA / "homepage-200-check.sh"), url],
        capture_output=True, text=True, env=env, check=False,
    )


@needs_bash
@needs_curl
def test_gate2_passes_on_200(http_server: str) -> None:
    res = _run_gate2(http_server + "/200")
    assert res.returncode == 0, res.stdout
    assert "[PASS]" in res.stdout


@needs_bash
@needs_curl
@pytest.mark.parametrize("code", [301, 404, 500, 503])
def test_gate2_fails_on_non_200(http_server: str, code: int) -> None:
    res = _run_gate2("%s/%d" % (http_server, code))
    assert res.returncode == 1, res.stdout
    assert "HTTP %d" % code in res.stdout


@needs_bash
@needs_curl
def test_gate2_fails_when_unreachable() -> None:
    import socket

    with socket.socket() as s:  # grab a free port, then close it: nothing listens there
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    res = _run_gate2("http://127.0.0.1:%d/" % port)
    assert res.returncode == 1, res.stdout
    assert "请求失败" in res.stdout


@needs_bash
def test_gate_fails_on_symlink(tmp_path: Path) -> None:
    # grep -r does not follow links and find -type f does not count them, yet a
    # publish step may copy the target: a link must not slip through unscanned
    outside = tmp_path / "outside.txt"
    outside.write_text("key ghp_" + "x" * 20 + "\n", encoding="utf-8")
    data = _data(tmp_path, {"a.txt": CLEAN})
    (data / "link.txt").symlink_to(outside)
    res = _run_gate(tmp_path, data)
    assert res.returncode == 1, res.stdout
    assert "符号链接" in res.stdout and "link.txt" in res.stdout


# ---- touch-target-check.sh route-table config ----

QA = ROOT / "qa-gates"


def _run_touch_target(tmp_path: Path, *, with_routes_file: bool,
                      env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a copy of gate 3 with a stub python that reports the routes it saw.

    The stub drains the embedded Python from stdin and prints the effective
    TOUCH_TARGET_ROUTES, so no browser is needed to test the config chain.
    """
    gate_dir = tmp_path / "gate3"
    gate_dir.mkdir(exist_ok=True)
    script = gate_dir / "touch-target-check.sh"
    shutil.copy(QA / "touch-target-check.sh", script)
    if with_routes_file:
        shutil.copy(QA / "touch-target-routes.txt", gate_dir / "touch-target-routes.txt")
    stub = gate_dir / "stub-python"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "cat > /dev/null\n"
        "printf 'SAW_ROUTES=%s\\n' \"${TOUCH_TARGET_ROUTES-<unset>}\"\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    run_env = {k: v for k, v in os.environ.items() if k != "TOUCH_TARGET_ROUTES"}
    run_env["TOUCH_TARGET_PYTHON"] = str(stub)
    run_env.update(env or {})
    return subprocess.run(
        ["bash", str(script), "https://example.invalid/"],
        capture_output=True, text=True, check=False, env=run_env,
    )


@needs_bash
def test_gate3_routes_fall_back_to_config_file(tmp_path: Path) -> None:
    res = _run_touch_target(tmp_path, with_routes_file=True)
    assert "source=file" in res.stderr
    assert "SAW_ROUTES=/ /business/ /data-room/ /company/ /accessibility/ /contact/" in res.stdout


@needs_bash
def test_gate3_routes_env_overrides_config_file(tmp_path: Path) -> None:
    res = _run_touch_target(tmp_path, with_routes_file=True,
                            env={"TOUCH_TARGET_ROUTES": "/ /company/"})
    assert "source=env" in res.stderr
    assert "SAW_ROUTES=/ /company/" in res.stdout


@needs_bash
def test_gate3_routes_default_without_env_or_file(tmp_path: Path) -> None:
    res = _run_touch_target(tmp_path, with_routes_file=False)
    assert "source=default" in res.stderr
    assert "SAW_ROUTES=<unset>" in res.stdout
