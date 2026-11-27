#!/usr/bin/env python3
"""Append-only, hash-chained log of gate run records, and the SLO check on it (OPS-2, #25).

Each gate writes one JSON run record (GATE_JSON_OUT). The release pipeline (or the
scheduled monitor) appends a summary of every record to one JSONL log:

    run-log.py append <LOG> <RECORD.json>...   add records (refuses a broken chain)
    run-log.py verify <LOG>                    exit 0 if the hash chain is intact
    run-log.py slo <LOG> [--window-days 30] [--fresh-hours 26]
                         [--gates "data-room homepage-200 touch-target"]
                         [--target 0.99] [--now ISO8601]

Every log line carries prev_sha256 (sha256 of the previous line, 64 zeros for the
first) and record_sha256 (sha256 of the record file as written). Editing, removing
or reordering any line breaks the chain from that point on; `verify` and `slo`
both report it. The log holds summaries only: no findings, page text or secrets.

SLOs (docs/SLO.md):
    SLO-1 verdict rate: share of runs in the window that ended with a binding
          verdict (PASS / FAIL / WARN), target >= 99 %. USAGE, ERROR and gate 1's
          NON-BINDING (skeleton pattern set) count against it.
    SLO-2 freshness: every expected gate has a run that finished within the last
          --fresh-hours hours, target 100 %.
A breach, a broken chain or an unreadable log prints [ALERT] lines and exits 1;
whoever runs `slo` (the scheduled monitor) turns that exit code into the alert.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import sys

GENESIS = "0" * 64
VERDICTS = {"PASS", "FAIL", "WARN"}
SUMMARY_KEYS = ("gate", "run_id", "trace_id", "finished_at", "result", "exit_code", "gate_version")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_chain(path: str) -> tuple[list[dict], str | None]:
    """Parse the log; return (entries, error-or-None). Stops at the first bad line."""
    entries: list[dict] = []
    prev = GENESIS
    if not os.path.exists(path):
        return entries, None
    with open(path, "rb") as f:
        for n, raw in enumerate(f.read().splitlines(), 1):
            try:
                entry = json.loads(raw)
            except ValueError:
                return entries, "line %d is not JSON" % n
            if not isinstance(entry, dict) or entry.get("prev_sha256") != prev:
                return entries, "hash chain broken at line %d" % n
            entries.append(entry)
            prev = _sha(raw)
    return entries, None


def append(log: str, records: list[str]) -> int:
    with open(log, "ab+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        entries, err = read_chain(log)
        if err:
            print("[ALERT] refusing to append: %s (%s)" % (err, log), file=sys.stderr)
            return 1
        f.seek(0)
        lines = f.read().splitlines()
        prev = _sha(lines[-1]) if lines else GENESIS
        for path in records:
            with open(path, "rb") as r:
                data = r.read()
            rec = json.loads(data)
            entry = {k: rec.get(k) for k in SUMMARY_KEYS}
            entry["gate"] = entry["gate"] or "data-room"  # gate 1 records before trace_id/gate
            entry["record_sha256"] = _sha(data)
            entry["prev_sha256"] = prev
            line = json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()
            f.write(line + b"\n")
            prev = _sha(line)
    return 0


def _parse_time(s: str) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def slo(log: str, window_days: float, fresh_hours: float, gates: list[str],
        target: float, now: dt.datetime) -> int:
    entries, err = read_chain(log)
    alerts: list[str] = []
    if not os.path.exists(log):
        alerts.append("run log %s does not exist" % log)
    if err:
        alerts.append("run log integrity: %s; SLOs computed over the intact prefix only" % err)
    since = now - dt.timedelta(days=window_days)
    window = [e for e in entries if (t := _parse_time(e.get("finished_at"))) and t >= since]
    good = sum(1 for e in window if e.get("result") in VERDICTS)
    if window:
        rate = good / len(window)
        print("[SLO-1] verdict rate %.2f%% (%d/%d runs, %g days), target %.2f%%"
              % (rate * 100, good, len(window), window_days, target * 100))
        if rate < target:
            alerts.append("SLO-1 breached: verdict rate %.2f%% < %.2f%%" % (rate * 100, target * 100))
    else:
        print("[SLO-1] no runs in the last %g days" % window_days)
        alerts.append("SLO-1 has no data: no runs in the last %g days" % window_days)
    for gate in gates:
        times = [t for e in entries if e.get("gate") == gate
                 and (t := _parse_time(e.get("finished_at")))]
        last = max(times) if times else None
        age = (now - last).total_seconds() / 3600 if last else None
        print("[SLO-2] %s last run %s" % (gate, "%.1f h ago" % age if age is not None else "never"))
        if age is None or age > fresh_hours:
            alerts.append("SLO-2 breached: %s has no run in the last %g h" % (gate, fresh_hours))
    for a in alerts:
        print("[ALERT] " + a)
    return 1 if alerts else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append")
    a.add_argument("log")
    a.add_argument("records", nargs="+")
    v = sub.add_parser("verify")
    v.add_argument("log")
    s = sub.add_parser("slo")
    s.add_argument("log")
    s.add_argument("--window-days", type=float, default=30)
    s.add_argument("--fresh-hours", type=float, default=26)
    s.add_argument("--gates", default="data-room homepage-200 touch-target")
    s.add_argument("--target", type=float, default=0.99)
    s.add_argument("--now", default="")
    args = ap.parse_args(argv[1:])
    if args.cmd == "append":
        return append(args.log, args.records)
    if args.cmd == "verify":
        entries, err = read_chain(args.log)
        if err:
            print("[ALERT] %s" % err)
            return 1
        print("chain intact: %d entries" % len(entries))
        return 0
    now = _parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    if now is None:
        print("bad --now", file=sys.stderr)
        return 2
    return slo(args.log, args.window_days, args.fresh_hours, args.gates.split(), args.target, now)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
