#!/usr/bin/env python3
"""Machine-readable IVV verdict for a PR head (SOTA VER-3; #6).

Reads a PR's comments (GitHub REST JSON list on stdin) and decides the
`ivv/verdict` commit status for the PR's current head:

    python3 ivv_verdict.py <HEAD_SHA> <PR_AUTHOR> < comments.json
    -> one JSON line: {"state", "description", "target_url"}

A comment counts as a verdict only if all of these hold:
  1. its first non-blank line is the IVV header
         ### 独立评估 · SOTA v<major>.<minor> · <sha>
     (the separators may be "·" or "|"); "独立评估" may also be written
     "Independent assessment";
  2. <sha> (7-40 hex) is a prefix of the PR's current head: a verdict on an
     older commit does not carry over to new code;
  3. the SOTA version is at least IVV_MIN_SOTA (default 1.3, the rubric in force);
  4. it has a verdict line  判定: PASS|FAIL|N/A  or  Verdict: PASS|FAIL|N/A
     (full- or half-width colon, optional ** bold; a gloss may follow), so a
     machine can read it ("合" / "不合" alone are not machine-readable);
  5. its author's association with the repo is OWNER, MEMBER or COLLABORATOR
     (IVV_TRUSTED_ASSOCIATIONS): on a public repo anyone can comment, and a
     stranger's "PASS" must not count;
  6. with IVV_REQUIRE_DISTINCT_AUTHOR=1, its author differs from the PR author.

The latest qualifying comment (by updated_at) decides:
    PASS -> success, FAIL -> failure, N/A or none -> pending.
An overall N/A is not a pass: N/A belongs to individual clauses, and a gate that
an N/A could satisfy would be one any PR could talk its way past.

The script never executes or interpolates comment text; it only matches it.
"""

from __future__ import annotations

import json
import os
import re
import sys

HEADER = re.compile(
    r"^#{2,4}\s*(?:独立评估|Independent assessment)\s*[·|]\s*SOTA\s*v(\d+)\.(\d+)\s*[·|]\s*`?([0-9a-fA-F]{7,40})`?\s*$")
VERDICT = re.compile(r"^\s*(?:判定|Verdict)\s*[:：]\s*\**\s*(PASS|FAIL|N/A)\b", re.MULTILINE)
STATES = {"PASS": "success", "FAIL": "failure", "N/A": "pending"}
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")


def _version(s: str) -> tuple[int, int]:
    major, _, minor = s.partition(".")
    return int(major), int(minor or 0)


def parse_comment(body: str) -> tuple[tuple[int, int], str, str | None] | None:
    """(sota_version, sha, verdict) for a body that opens with the IVV header, else None.

    verdict is None when the header is there but no machine-readable verdict line is.
    """
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    if not lines:
        return None
    m = HEADER.match(lines[0])
    if not m:
        return None
    v = VERDICT.search(body)
    return (int(m.group(1)), int(m.group(2))), m.group(3).lower(), v.group(1) if v else None


def decide(comments: list[dict], head_sha: str, pr_author: str,
           min_sota: tuple[int, int] = (1, 3), distinct_author: bool = False,
           trusted: tuple[str, ...] = TRUSTED) -> dict:
    head = head_sha.lower()
    best = None
    stale = []
    for c in comments:
        parsed = parse_comment(c.get("body", ""))
        if not parsed:
            continue
        version, sha, verdict = parsed
        author = (c.get("user") or {}).get("login", "")
        if c.get("author_association") not in trusted:
            stale.append("verdict by %s (%s) is not from a trusted reviewer"
                         % (author, c.get("author_association")))
            continue
        if verdict is None:
            stale.append("IVV header on %s but no machine-readable verdict line "
                         "(write 判定: PASS or 判定: FAIL)" % sha[:7])
            continue
        if not head.startswith(sha):
            stale.append("verdict on %s, head is %s" % (sha[:7], head[:7]))
            continue
        if version < min_sota:
            stale.append("verdict cites SOTA v%d.%d < v%d.%d" % (version + min_sota))
            continue
        if distinct_author and author == pr_author:
            stale.append("verdict author is the PR author")
            continue
        key = c.get("updated_at") or c.get("created_at") or ""
        if best is None or key >= best[0]:
            best = (key, verdict, c.get("html_url", ""), author)
    if best is None:
        why = "; ".join(dict.fromkeys(stale)) if stale else "no IVV verdict for this head"
        return {"state": "pending", "description": ("awaiting IVV verdict: " + why)[:140],
                "target_url": ""}
    _, verdict, url, author = best
    desc = {"PASS": "IVV verdict PASS on %s by %s",
            "FAIL": "IVV verdict FAIL on %s by %s",
            "N/A": "overall N/A on %s by %s is not a pass; needs PASS"}[verdict] % (head[:7], author)
    return {"state": STATES[verdict], "description": desc[:140], "target_url": url}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.split("\n\n", 2)[1], file=sys.stderr)
        return 2
    comments = json.load(sys.stdin)
    min_sota = _version(os.environ.get("IVV_MIN_SOTA", "1.3"))
    distinct = os.environ.get("IVV_REQUIRE_DISTINCT_AUTHOR") == "1"
    trusted = tuple(os.environ.get("IVV_TRUSTED_ASSOCIATIONS", " ".join(TRUSTED)).split())
    result = decide(comments, argv[1], argv[2], min_sota, distinct, trusted)
    result["context"] = "ivv/verdict"
    if not result["target_url"]:
        del result["target_url"]  # the statuses API rejects an empty URL
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
