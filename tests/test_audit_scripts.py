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

def _run_gate(home: Path, data_dir: Path) -> subprocess.CompletedProcess:
    # The gate resolves its allowlist relative to the script's own directory.
    (home / "workspace/vertcity/security-watch").mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        ["bash", str(SW / "data-room-gate.sh"), str(data_dir)],
        capture_output=True, text=True, env=env, check=False,
    )


needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


@needs_bash
def test_gate_passes_clean_dir(tmp_path: Path) -> None:
    data = tmp_path / "data-room"
    data.mkdir()
    (data / "a.txt").write_text("Classification: Public\nhello\n", encoding="utf-8")
    res = _run_gate(tmp_path / "home", data)
    assert res.returncode == 0, res.stdout
    assert "结果：PASS" in res.stdout


@needs_bash
def test_gate_fails_on_token(tmp_path: Path) -> None:
    data = tmp_path / "data-room"
    data.mkdir()
    (data / "a.txt").write_text("key ghp_" + "x" * 20 + "\n", encoding="utf-8")
    res = _run_gate(tmp_path / "home", data)
    assert res.returncode == 1
    assert "GATE FAIL" in res.stdout
    assert "x" * 20 not in res.stdout  # token is masked in output


@needs_bash
def test_gate_fails_on_missing_dir(tmp_path: Path) -> None:
    res = _run_gate(tmp_path / "home", tmp_path / "nope")
    assert res.returncode == 1
    assert "目录不存在" in res.stdout
