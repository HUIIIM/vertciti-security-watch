"""scripts/ivv_verdict.py: the ivv/verdict status decision (SOTA VER-3)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ivv_verdict.py"
HEAD = "a5e1994ff30d517f8d4cbfa56eddd05285fef0c7"


def _mod():
    spec = importlib.util.spec_from_file_location("ivv_verdict", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _c(body: str, *, who: str = "reviewer", assoc: str = "OWNER",
       at: str = "2026-11-28T00:00:00Z") -> dict:
    return {"body": body, "user": {"login": who}, "author_association": assoc,
            "updated_at": at, "html_url": "https://example.invalid/c/" + at}


def _verdict(word: str, sha: str = HEAD[:7], sota: str = "1.3", extra: str = "") -> str:
    return ("### 独立评估 · SOTA v%s · %s\n\n判定：**%s**%s\n\n| 条款 | 判 |\n|---|---|\n"
            % (sota, sha, word, extra))


def decide(comments: list[dict], **kw: object) -> dict:
    return _mod().decide(comments, HEAD, "author", **kw)


@pytest.mark.parametrize("word,state", [("PASS", "success"), ("FAIL", "failure"),
                                        ("N/A", "pending")])
def test_verdict_word_maps_to_state(word: str, state: str) -> None:
    assert decide([_c(_verdict(word))])["state"] == state


def test_gloss_after_the_machine_word_is_fine() -> None:
    body = _verdict("PASS", extra="（合；复核者与施工席同属一账号，显名注记）")
    assert decide([_c(body)])["state"] == "success"


@pytest.mark.parametrize("body", [
    "### 独立评估 · SOTA v1.3 · a5e1994\n\n判定：**合**\n",       # #38/#39 wording
    "Verdict: PASS — merge.\n\nScope check: ...",                  # #41: no IVV header
    "LGTM, PASS",                                                  # no header at all
    "判定：PASS\n### 独立评估 · SOTA v1.3 · a5e1994\n",            # header not first
])
def test_non_machine_readable_verdicts_stay_pending(body: str) -> None:
    assert decide([_c(body)])["state"] == "pending"


def test_header_without_machine_word_says_so() -> None:
    res = decide([_c("### 独立评估 · SOTA v1.3 · a5e1994\n\n判定：**合**\n")])
    assert "no machine-readable verdict line" in res["description"]


def test_verdict_on_an_older_commit_does_not_carry_over() -> None:
    res = decide([_c(_verdict("PASS", sha="0272207"))])
    assert res["state"] == "pending" and "head is a5e1994" in res["description"]


def test_full_and_short_sha_both_match() -> None:
    assert decide([_c(_verdict("PASS", sha=HEAD))])["state"] == "success"
    assert decide([_c(_verdict("PASS", sha=HEAD[:10].upper()))])["state"] == "success"


def test_stale_rubric_version_is_refused() -> None:
    res = decide([_c(_verdict("PASS", sota="1.1"))])
    assert res["state"] == "pending" and "SOTA v1.1 < v1.3" in res["description"]
    assert decide([_c(_verdict("PASS", sota="1.10"))])["state"] == "success"
    assert decide([_c(_verdict("PASS", sota="2.0"))])["state"] == "success"


@pytest.mark.parametrize("assoc", ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", None])
def test_untrusted_commenter_cannot_pass_a_pr(assoc: object) -> None:
    res = decide([_c(_verdict("PASS"), who="stranger", assoc=assoc)])
    assert res["state"] == "pending" and "not from a trusted reviewer" in res["description"]


@pytest.mark.parametrize("assoc", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_trusted_associations(assoc: str) -> None:
    assert decide([_c(_verdict("PASS"), assoc=assoc)])["state"] == "success"


def test_latest_qualifying_verdict_wins() -> None:
    first = _c(_verdict("PASS"), at="2026-11-28T01:00:00Z")
    later = _c(_verdict("FAIL"), at="2026-11-28T02:00:00Z")
    assert decide([later, first])["state"] == "failure"
    assert decide([first, _c(_verdict("PASS"), at="2026-11-28T03:00:00Z"), later])["state"] == "success"


def test_untrusted_later_comment_does_not_override_a_trusted_fail() -> None:
    fail = _c(_verdict("FAIL"), at="2026-11-28T01:00:00Z")
    forged = _c(_verdict("PASS"), who="stranger", assoc="NONE", at="2026-11-28T02:00:00Z")
    assert decide([fail, forged])["state"] == "failure"


def test_distinct_author_lever() -> None:
    same = [_c(_verdict("PASS"), who="author")]
    assert decide(same)["state"] == "success"
    res = decide(same, distinct_author=True)
    assert res["state"] == "pending" and "PR author" in res["description"]
    assert decide([_c(_verdict("PASS"), who="other")], distinct_author=True)["state"] == "success"


def test_alternate_header_spelling() -> None:
    body = "### Independent assessment | SOTA v1.3 | `%s`\n\nVerdict: PASS (merge)\n" % HEAD[:7]
    assert decide([_c(body)])["state"] == "success"


def test_cli_emits_status_payload() -> None:
    comments = [_c(_verdict("PASS"))]
    res = subprocess.run([sys.executable, "-I", str(SCRIPT), HEAD, "author"],
                         input=json.dumps(comments), capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["context"] == "ivv/verdict" and out["state"] == "success" and out["target_url"]
    res = subprocess.run([sys.executable, "-I", str(SCRIPT), HEAD, "author"],
                         input="[]", capture_output=True, text=True, check=False)
    out = json.loads(res.stdout)
    assert out["state"] == "pending" and "target_url" not in out  # API rejects ""


def test_cli_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    comments = json.dumps([_c(_verdict("PASS", sota="1.3"), assoc="CONTRIBUTOR")])
    env = {"IVV_MIN_SOTA": "1.4", "IVV_TRUSTED_ASSOCIATIONS": "CONTRIBUTOR", "PATH": ""}
    res = subprocess.run([sys.executable, "-I", str(SCRIPT), HEAD, "author"], input=comments,
                         capture_output=True, text=True, check=False, env=env)
    assert "SOTA v1.3 < v1.4" in json.loads(res.stdout)["description"]
