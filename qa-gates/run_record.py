"""Machine-readable run record for gates 2 and 3 (SOTA OPS-2).

Same contract as gate 1's GATE_JSON_OUT record: when GATE_JSON_OUT is set, every
run (early exits included) ends by writing one JSON object there, and a gate
that cannot write the record it was asked for exits 1 (fail-closed).

Fields shared by all gates (gate 1 writes the same core fields):
    schema, gate, gate_version, run_id (UUIDv4), trace_id, started_at,
    finished_at, duration_ms, result, exit_code, script_sha256
trace_id is GATE_TRACE_ID when the pipeline sets one (so the three gates of one
release share it), else the run_id. Gate-specific fields come from a JSON
"detail" file the gate wrote; they never contain page content or secrets.

CLI:
    python3 run_record.py write <OUT> <GATE> <EXIT_CODE> <SCRIPT> [DETAIL_JSON]
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
import uuid

SCHEMA = "vertciti-qa-gate/1"
GATE_VERSION = "1.0.0"
RESULTS = {0: "PASS", 1: "FAIL", 2: "USAGE"}


def _sha(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(timespec="milliseconds")


def build(gate: str, rc: int, script: str, detail: dict | None = None) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    try:
        started = float(os.environ.get("GATE_STARTED_AT", "")) / 1000.0
    except ValueError:
        started = now
    run_id = str(uuid.uuid4())
    record = {
        "schema": SCHEMA,
        "gate": gate,
        "gate_version": GATE_VERSION,
        "run_id": run_id,
        "trace_id": os.environ.get("GATE_TRACE_ID") or run_id,
        "started_at": _iso(started),
        "finished_at": _iso(now),
        "duration_ms": max(0, int(round((now - started) * 1000))),
        "result": RESULTS.get(rc, "ERROR"),
        "exit_code": rc,
        "script_sha256": _sha(script),
    }
    for key, value in (detail or {}).items():
        record.setdefault(key, value)  # core fields cannot be overridden by a gate
    return record


def write(out: str, gate: str, rc: int, script: str, detail_path: str | None = None) -> dict:
    detail = None
    if detail_path and os.path.exists(detail_path):
        with open(detail_path, encoding="utf-8") as f:
            detail = json.load(f)
    record = build(gate, rc, script, detail)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return record


def main(argv: list[str]) -> int:
    if len(argv) in (6, 7) and argv[1] == "write":
        try:
            write(argv[2], argv[3], int(argv[4]), argv[5], argv[6] if len(argv) == 7 else None)
        except (OSError, ValueError) as exc:
            print("run record not written: %s" % exc, file=sys.stderr)
            return 1
        return 0
    print(__doc__.split("CLI:", 1)[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
