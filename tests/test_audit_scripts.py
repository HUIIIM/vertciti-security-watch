"""Smoke tests for the existing audit scripts and data-room gate.

These exercise real behavior of the scripts as committed; they do not touch
production paths. Python scripts are loaded by file path because their file
names contain hyphens.
"""

import hashlib
import importlib.util
import json
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
    skeleton_text: str | None = None,
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
    if skeleton_text is not None:
        (gate_dir / "gate-patterns-skeleton.txt").write_text(skeleton_text, encoding="utf-8")
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
    assert res.returncode == 4, res.stdout  # WARN-only exits 4, distinct from PASS
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
                      env: dict[str, str] | None = None,
                      url: str = "https://example.invalid/") -> subprocess.CompletedProcess:
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
        ["bash", str(script), url],
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
# ---- gate 1 machine-readable run record (GATE_JSON_OUT, #6 OPS-2) ----

def _record(tmp_path: Path, data: Path, **kw: str) -> tuple:
    out = tmp_path / "record.json"
    res = _run_gate(tmp_path, data, env={"GATE_JSON_OUT": str(out), **kw})
    return res, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


@needs_bash
def test_gate_record_clean_run(tmp_path: Path) -> None:
    res, rec = _record(tmp_path, _data(tmp_path, {"a.txt": CLEAN, "b/c.md": "ok\n"}))
    assert res.returncode == 0, res.stdout + res.stderr
    assert rec["schema"] == "vertciti-data-room-gate/1"
    assert rec["result"] == "PASS" and rec["exit_code"] == 0
    assert rec["files_scanned"] == 2 and len(rec["files_manifest_sha256"]) == 64
    assert rec["pattern_set"]["mode"] == "skeleton" and rec["findings"] == []
    assert len(rec["allowlist_sha256"]) == 64 and len(rec["script_sha256"]) == 64


@needs_bash
def test_gate_record_lists_locations_never_content(tmp_path: Path) -> None:
    token = "ghp_" + "q" * 24
    data = _data(tmp_path, {"a.txt": "ok\nkey " + token + "\n",
                            "x.bin": b"\x00\x01binary"})
    res, rec = _record(tmp_path, data)
    assert res.returncode == 1
    assert rec["result"] == "FAIL" and rec["exit_code"] == 1
    assert {"rule": "rule4", "severity": "fail", "path": "a.txt", "line": 2} in rec["findings"]
    assert {"rule": "binary", "severity": "fail", "path": "x.bin", "line": None} in rec["findings"]
    assert token not in (tmp_path / "record.json").read_text(encoding="utf-8")


@needs_bash
def test_gate_record_skeleton_non_binding(tmp_path: Path) -> None:
    res, rec = _record(tmp_path, _data(tmp_path, {"a.txt": CLEAN}), GATE_ALLOW_SKELETON="0")
    assert res.returncode == 3
    assert rec["result"] == "NON-BINDING" and rec["exit_code"] == 3


@needs_bash
def test_gate_record_written_on_early_fail_closed_exit(tmp_path: Path) -> None:
    res, rec = _record(tmp_path, _data(tmp_path, {}))  # empty dir exits early
    assert res.returncode == 1
    assert rec["result"] == "FAIL" and rec["files_scanned"] == 0


@needs_bash
def test_gate_record_requested_but_unwritable_fails(tmp_path: Path) -> None:
    out = tmp_path / "no-such-dir" / "record.json"
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}),
                    env={"GATE_JSON_OUT": str(out)})
    assert res.returncode == 1, res.stdout + res.stderr
    assert "运行记录写入失败" in res.stderr


@needs_bash
def test_gate_without_record_env_writes_nothing(tmp_path: Path) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN}))
    assert res.returncode == 0
    assert not list(tmp_path.glob("*.json"))


@needs_bash
def test_gate3_routes_file_not_applied_to_file_url(tmp_path: Path) -> None:
    # the file lists live-site paths; on a file:// target "/business/" would
    # resolve to file:///business/ (filesystem root), so hash routes stay
    res = _run_touch_target(tmp_path, with_routes_file=True,
                            url="file:///srv/deploy-prod-root/index.html")
    assert "source=default" in res.stderr
    assert "SAW_ROUTES=<unset>" in res.stdout

# ---- shadow-audit.py --expect (opt-in declaration-count check) ----

def _shadow(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    html = tmp_path / "i.html"
    html.write_text("<style>a{box-shadow:none}b{box-shadow:0 0 1px #000}</style>",
                    encoding="utf-8")
    return subprocess.run(["python3", str(SW / "shadow-audit.py"), str(html), *extra],
                          capture_output=True, text=True, check=False)


def test_shadow_no_expect_no_warning(tmp_path: Path) -> None:
    res = _shadow(tmp_path)
    assert res.returncode == 0 and "WARN" not in res.stderr


def test_shadow_expect_match_and_mismatch(tmp_path: Path) -> None:
    assert _shadow(tmp_path, "--expect", "2").returncode == 0
    res = _shadow(tmp_path, "--expect", "71")
    assert res.returncode == 1 and "2 != expected 71" in res.stderr
    assert _shadow(tmp_path, "--expect", "x").returncode == 2


# ---- gate 1 batch 1 (scorecard #6 §3.1 F/L/K/I/J, §3.3, §3.4) ----

def _synthetic_tokens() -> dict[str, str]:
    """Clearly synthetic token-shaped values, assembled at runtime."""
    return {
        "openai": "sk-proj-" + "SYNTHETIC" * 3,
        "gitlab": "glpat-" + "SYNTHETIC0123456789ab",
        "npm": "npm_" + "SYNTHETICSYNTHETICSYNTHETICSYNTHETIC",
        "jwt": "eyJ" + "SYNTHETICHDR" + ".eyJ" + "SYNTHETICBODY" + ".SYNTHETICSIGNATURE",
        "aws_secret": "aws_secret_access_key = " + "SYNTHETIC/" * 4,
        "stripe_test": "sk_test_" + "SYNTHETIC0123",
        "twilio": "SK" + "0123456789abcdef" * 2,
        "sendgrid": "SG." + "SYNTHETICSYNTHETIC" + "." + "SYNTHETICSYNTHETIC",
        "slack_hook": "https://hooks.slack.com/services/T0SYNTH01/B0SYNTH01/" + "SYNTHETIC" * 3,
        "pg_url": "postgres://svcuser:SynthPass9@db.example.com/app",
    }


@needs_bash
@pytest.mark.parametrize("kind", sorted(_synthetic_tokens()))
def test_gate_rule4_covers_token_type(tmp_path: Path, kind: str) -> None:
    line = "value: " + _synthetic_tokens()[kind]
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": "ok\n" + line + "\n"}))
    assert res.returncode == 1, (kind, res.stdout)
    assert "疑似密钥 token" in res.stdout, (kind, res.stdout)


@needs_bash
def test_gate_rule4_combined_fixture_all_types_are_findings(tmp_path: Path) -> None:
    toks = _synthetic_tokens()
    body = "\n".join("line %d %s" % (i, v) for i, v in enumerate(toks.values()))
    res, rec = _record(tmp_path, _data(tmp_path, {"a.txt": body + "\n"}))
    assert res.returncode == 1, res.stdout
    rule4_lines = {f["line"] for f in rec["findings"] if f["rule"] == "rule4"}
    assert rule4_lines == set(range(1, len(toks) + 1))


@needs_bash
@pytest.mark.parametrize("line", [
    "see sk-learn and sk-proj for docs",
    "SKU 12345 and SK1234",
    "the SG. prefix is a sendgrid thing",
    "npm_config_cache is an env var",
    "eyJ is how base64 json starts",
    "set aws_secret_access_key in your environment",
    "connect via postgres://db.example.com/app",
    "see https://hooks.slack.com/ for webhook docs",
    "sk_test mode",
    "glpat tokens are created in settings",
])
def test_gate_rule4_no_false_positive_on_prose(tmp_path: Path, line: str) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN + line + "\n"}))
    assert res.returncode == 0, res.stdout


@needs_bash
@pytest.mark.parametrize("url", [
    "postgres://admin:Zebra9Pass@db.example.com/app",
    "https://admin:Zebra9Pass@api.example.com/x",   # not a rule-4 scheme: rule 6 path only
    "https://admin:p!ss9Zebra@api.example.com/x",   # password char outside the email charset
])
def test_gate_mask_never_leaks_credential_chars(tmp_path: Path, url: str) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": "dsn " + url + "\n"}))
    out = res.stdout
    assert "Z****" not in out and "Zebra9" not in out and "p!ss9" not in out
    assert "s9Zebra" not in out and "9Zebra@" not in out and "s****@" not in out
    assert "a.txt:1:" in out


@needs_bash
def test_gate_genuine_email_mask_keeps_first_char(tmp_path: Path) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": "contact jane.doe@example.com\n"}))
    assert "j****@example.com" in res.stdout
    assert "jane.doe" not in res.stdout


@needs_bash
def test_gate_warn_only_exits_4_and_pass_stays_0(tmp_path: Path) -> None:
    res, rec = _record(tmp_path, _data(tmp_path, {"a.txt": "db password = Sup3rSecretValue\n"}))
    assert res.returncode == 4, res.stdout
    assert rec["result"] == "WARN" and rec["exit_code"] == 4
    clean = tmp_path / "clean-room"
    clean.mkdir()
    (clean / "b.txt").write_text(CLEAN, encoding="utf-8")
    assert _run_gate(tmp_path, clean).returncode == 0


@needs_bash
def test_gate_exit_code_contract_documented(tmp_path: Path) -> None:
    res = subprocess.run(["bash", str(SW / "data-room-gate.sh"), "--help"],
                         capture_output=True, text=True, check=False)
    assert "exit 4" in res.stdout and "WARN" in res.stdout
    assert "exit 4" in (SW / "data-room-gate.sh").read_text(encoding="utf-8")


@needs_bash
def test_gate_fail_beats_warn_and_skeleton_stays_3(tmp_path: Path) -> None:
    both = "db password = Sup3rSecretValue\nkey ghp_" + "x" * 20 + "\n"
    assert _run_gate(tmp_path, _data(tmp_path, {"a.txt": both})).returncode == 1
    warn = tmp_path / "warn-room"
    warn.mkdir()
    (warn / "c.txt").write_text("db password = Sup3rSecretValue\n", encoding="utf-8")
    assert _run_gate(tmp_path, warn, env={"GATE_ALLOW_SKELETON": "0"}).returncode == 3
    assert _run_gate(tmp_path, tmp_path / "nope").returncode == 1
    res = subprocess.run(["bash", str(SW / "data-room-gate.sh")], capture_output=True,
                         text=True, check=False, env={**os.environ, "DATA_ROOM_DIR": ""})
    assert res.returncode == 2


@needs_bash
def test_gate_record_path_and_line_exact_when_content_looks_like_grep_output(
        tmp_path: Path) -> None:
    res, rec = _record(tmp_path, _data(tmp_path, {"x.txt": "ref:2:PLACEHOLDERWORD\n"}))
    assert res.returncode == 1
    assert rec["findings"] == [{"rule": "rule2", "severity": "fail", "path": "x.txt", "line": 1}]


@needs_bash
def test_gate_record_path_with_colon_digits_and_allowlist_still_exact(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a:7:b.txt": "ok\nPLACEHOLDERWORD\n"})
    res, rec = _record(tmp_path, data)
    assert rec["findings"] == [{"rule": "rule2", "severity": "fail", "path": "a:7:b.txt", "line": 2}]
    ok = _run_gate(tmp_path, data, allowlist="a:7:b.txt:2:PLACEHOLDERWORD\n")
    assert ok.returncode == 0, ok.stdout


def _skeleton_lines() -> list[str]:
    return (SW / "gate-patterns-skeleton.txt").read_text(encoding="utf-8").splitlines()


def _run_with_pattern_text(tmp_path: Path, text: str, mode: str) -> subprocess.CompletedProcess:
    data = _data(tmp_path, {"a.txt": CLEAN})
    if mode == "skeleton":
        return _run_gate(tmp_path, data, skeleton_text=text)
    pf = tmp_path / "patterns-bad.txt"
    pf.write_text(text, encoding="utf-8")
    env = {"GATE_PATTERN_FILE": str(pf),
           "GATE_PATTERN_SHA256": hashlib.sha256(pf.read_bytes()).hexdigest()}
    return _run_gate(tmp_path, data, env=env)


def _mutations() -> dict[str, str]:
    base = _skeleton_lines()
    rule1 = next(i for i, ln in enumerate(base) if ln.startswith("1.pattern "))
    bare = list(base)
    bare[rule1] = "1.pattern"
    blank = list(base)
    blank[rule1] = "1.pattern    "
    no_exclude = [ln for ln in base if not ln.startswith("5.exclude")]
    no_rule6 = [ln for ln in base if not ln.startswith("6.pattern")]
    return {"bare-key-line": "\n".join(bare) + "\n",
            "only-1.pattern": "1.pattern\n",
            "blank-value": "\n".join(blank) + "\n",
            "duplicate-rule": "\n".join(base + ["4.pattern zzzz"]) + "\n",
            "unknown-rule": "\n".join(base + ["9.pattern zzzz"]) + "\n",
            "missing-exclude": "\n".join(no_exclude) + "\n",
            "missing-rule6": "\n".join(no_rule6) + "\n",
            "misspelled-field": "\n".join(base + ["1.pattrn zzzz"]) + "\n"}


@needs_bash
@pytest.mark.parametrize("mode", ["full", "skeleton"])
@pytest.mark.parametrize("name", sorted(_mutations()))
def test_gate_pattern_set_is_strict_fail_closed(tmp_path: Path, mode: str, name: str) -> None:
    res = _run_with_pattern_text(tmp_path, _mutations()[name], mode)
    assert res.returncode == 1, (name, mode, res.stdout)
    assert "模式集" in res.stdout


@needs_bash
def test_gate_pattern_set_valid_full_still_passes(tmp_path: Path) -> None:
    res = _run_with_pattern_text(tmp_path, "\n".join(_skeleton_lines()) + "\n", "full")
    assert res.returncode == 0, res.stdout


@needs_bash
def test_gate_record_has_run_id_and_gate_version(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": CLEAN})
    _, rec1 = _record(tmp_path, data)
    _, rec2 = _record(tmp_path, data)
    assert uuid.UUID(rec1["run_id"]).version == 4
    assert rec1["run_id"] != rec2["run_id"]
    assert rec1["gate_version"] and rec1["gate_version"] == rec2["gate_version"]
    assert rec1["gate_version"] in (SW / "data-room-gate.sh").read_text(encoding="utf-8")


def _fp_from(out: str) -> str:
    import re

    m = re.search(r"fp=([0-9a-f]+)\]", out)
    assert m, out
    return m.group(1)


@needs_bash
def test_gate_fingerprint_is_full_sha256_by_default(tmp_path: Path) -> None:
    content = "launch Nov 1955"
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": content + "\n"}))
    assert _fp_from(res.stdout) == hashlib.sha256(content.encode()).hexdigest()


@needs_bash
def test_gate_fingerprint_is_hmac_when_key_set(tmp_path: Path) -> None:
    import hmac

    content = "launch Nov 1955"
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": content + "\n"}),
                    env={"GATE_FP_KEY": "synthetic-test-key"})
    want = hmac.new(b"synthetic-test-key", content.encode(), hashlib.sha256).hexdigest()
    assert _fp_from(res.stdout) == want


@needs_bash
def test_gate_allowlist_fp_entry_uses_same_function_as_emitted_fp(tmp_path: Path) -> None:
    import hmac

    content = "launch Nov 1955"
    data = _data(tmp_path, {"a.txt": content + "\n"})
    subject = ("a.txt:1:" + content).encode()
    plain = "fp:" + hashlib.sha256(subject).hexdigest() + "\n"
    keyed = "fp:" + hmac.new(b"k1", subject, hashlib.sha256).hexdigest() + "\n"
    assert _run_gate(tmp_path, data, allowlist=plain).returncode == 0
    assert _run_gate(tmp_path, data, allowlist=keyed).returncode == 1
    # with a key set, only the keyed entry exempts; the offline-computable one must not
    assert _run_gate(tmp_path, data, allowlist=plain, env={"GATE_FP_KEY": "k1"}).returncode == 1
    assert _run_gate(tmp_path, data, allowlist=keyed, env={"GATE_FP_KEY": "k1"}).returncode == 0


# ---- rule 4: inline credentials in any URL scheme (#6 §1 L residual) ----

@needs_bash
@pytest.mark.parametrize("url", [
    "https://admin:Zebra9Pass@api.example.com/x",
    "http://svc:Zebra9Pass@10.0.0.5:8080/",
    "ftp://ops:Zebra9Pass@files.example.com/",
    "smtp://mailer:Zebra9Pass@smtp.example.com:587",
    "https://:ghostTokenValue9@registry.example.com/",   # token-only userinfo
    "git+https://bot:Zebra9Pass@git.example.com/org/repo.git",
    "postgres://svcuser:SynthPass9@db.example.com/app",  # database schemes still covered
])
def test_gate_rule4_flags_credentials_in_any_url_scheme(tmp_path: Path, url: str) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": "dsn " + url + "\n"}))
    assert res.returncode == 1, (url, res.stdout)
    assert "疑似密钥 token" in res.stdout and "Zebra9" not in res.stdout and "ghostToken" not in res.stdout


@needs_bash
@pytest.mark.parametrize("line", [
    "see https://example.com:8443/path for docs",
    "clone ssh://git@git.example.com:22/org/repo.git",
    "open https://user@example.com/ to sign in",
    "write to mailto:ops:team@example.com",
])
def test_gate_rule4_url_userinfo_no_false_positive(tmp_path: Path, line: str) -> None:
    # host:port, user-without-password and mailto: are not inline credentials.
    # (Some of these still WARN under rule 6 as e-mail-shaped strings: that is
    # rule 6's existing behaviour, so only rule 4 is asserted here.)
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": CLEAN + line + "\n"}))
    assert res.returncode != 1 and "疑似密钥 token" not in res.stdout, (line, res.stdout)


@needs_bash
def test_gate_rule4_documented_url_placeholder_fails_closed(tmp_path: Path) -> None:
    # a placeholder like scheme://user:password@host is indistinguishable from a real
    # credential: it fails closed and is cleared by an exact allowlist entry
    line = "format: https://user:password@host/path"
    data = _data(tmp_path, {"a.txt": line + "\n"})
    assert _run_gate(tmp_path, data).returncode == 1
    assert _run_gate(tmp_path, data, allowlist="a.txt:1:%s\n" % line).returncode == 0
