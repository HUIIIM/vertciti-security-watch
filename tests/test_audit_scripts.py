"""Smoke tests for the existing audit scripts and data-room gate.

These exercise real behavior of the scripts as committed; they do not touch
production paths. Python scripts are loaded by file path because their file
names contain hyphens.
"""

import importlib.util
import os
import shutil
import subprocess
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
    tmp_path: Path, data_dir: Path, allowlist: str | None = ""
) -> subprocess.CompletedProcess:
    """Run a copy of the gate whose sibling allowlist holds `allowlist`.

    The gate resolves its allowlist next to the script, so each test gets its own
    copy instead of touching the committed security-watch/gate-allowlist.txt.
    allowlist=None means the allowlist file exists but is unreadable.
    """
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir(exist_ok=True)
    script = gate_dir / "data-room-gate.sh"
    shutil.copy(SW / "data-room-gate.sh", script)
    al = gate_dir / "gate-allowlist.txt"
    al.write_text(allowlist or "", encoding="utf-8")
    if allowlist is None:
        al.chmod(0)
    return subprocess.run(
        ["bash", str(script), str(data_dir)],
        capture_output=True, text=True, check=False,
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
    data = _data(tmp_path, {"a.txt": "TOP SECRET\n"})
    res = _run_gate(tmp_path, data, allowlist=None)
    assert res.returncode == 1
    assert "allowlist 不可读" in res.stdout


@needs_bash
def test_gate_blank_allowlist_line_does_not_exempt_everything(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": "TOP SECRET\n"})
    res = _run_gate(tmp_path, data, allowlist="foo\n\n   \n")
    assert res.returncode == 1, res.stdout


@needs_bash
def test_gate_allowlist_needs_exact_path_and_line(tmp_path: Path) -> None:
    data = _data(tmp_path, {"notes.txt": "ok\nTOP SECRET\n"})
    # a bare file name (old substring semantics) or the wrong line exempts nothing
    assert _run_gate(tmp_path, data, allowlist="notes.txt\n").returncode == 1
    assert _run_gate(tmp_path, data, allowlist="notes.txt:1\n").returncode == 1
    res = _run_gate(tmp_path, data, allowlist="# reviewed\nnotes.txt:2\n")
    assert res.returncode == 0, res.stdout


@needs_bash
@pytest.mark.parametrize("name", ["a.md", "b.json", "c.html", "d.csv", "nested/e"])
def test_gate_scans_non_txt_files(tmp_path: Path, name: str) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {name: "TOP SECRET\n"}))
    assert res.returncode == 1, res.stdout


@needs_bash
def test_gate_private_key_in_pem_fails(tmp_path: Path) -> None:
    data = _data(tmp_path, {"k.pem": "-----BEGIN RSA PRIVATE KEY-----\n"})
    res = _run_gate(tmp_path, data, allowlist="k.pem:*\n")  # not allowlistable
    assert res.returncode == 1
    assert "私钥块" in res.stdout


@needs_bash
def test_gate_fails_on_empty_dir(tmp_path: Path) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {}))
    assert res.returncode == 1
    assert "扫描文件数：0" in res.stdout


@needs_bash
def test_gate_binary_file_fails_until_reviewed(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": CLEAN, "x.pdf": b"%PDF-1.4\x00\x01binary"})
    res = _run_gate(tmp_path, data)
    assert res.returncode == 1
    assert "x.pdf:二进制" in res.stdout
    assert _run_gate(tmp_path, data, allowlist="x.pdf:*\n").returncode == 0


@needs_bash
@not_root
def test_gate_unreadable_file_fails(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": CLEAN, "b.txt": "TOP SECRET\n"})
    (data / "b.txt").chmod(0)
    res = _run_gate(tmp_path, data)
    assert res.returncode == 1
    assert "b.txt:不可读" in res.stdout


@needs_bash
@pytest.mark.parametrize("line", [
    "Classification: TOP SECRET",
    "launch 2027-02",
    "launch 2027/02",
    "launch 2027.2",
    "launch 2027年2月",
    "launch Feb 2027",
    "launch February 2027",
    "github_pat_11ABCDEFG0123456789_abcdefghij",
    "ghs_" + "a" * 20,
    "sk-ant-api03-" + "A" * 12,
])
def test_gate_detection_variants(tmp_path: Path, line: str) -> None:
    res = _run_gate(tmp_path, _data(tmp_path, {"a.txt": line + "\n"}))
    assert res.returncode == 1, res.stdout


@needs_bash
def test_gate_reports_location_not_content(tmp_path: Path) -> None:
    data = _data(tmp_path, {"a.txt": "db password=Hunter2SuperSecretValue\nTOP SECRET plan\n"})
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
