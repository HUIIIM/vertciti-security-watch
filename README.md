[![CI](https://github.com/HUIIIM/vertciti-security-watch/actions/workflows/ci.yml/badge.svg)](https://github.com/HUIIIM/vertciti-security-watch/actions/workflows/ci.yml)
[![Secret scan](https://github.com/HUIIIM/vertciti-security-watch/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/HUIIIM/vertciti-security-watch/actions/workflows/gitleaks.yml)

# vertciti-security-watch

Continuous security monitoring and release gates for vertciti.com.

## The three release gates

Every vertciti.com production release must pass all three gates. Any FAIL
stops the release.

| # | Gate | Command |
|---|------|---------|
| 1 | Data-room sensitive-info scan — restricted date/classified wording, private keys, and tokens are FAIL; password assignments and email addresses are WARN (human review) | `bash security-watch/data-room-gate.sh [dir]` |
| 2 | Homepage serves HTTP 200 after deploy | `curl -sI https://vertciti.com/` |
| 3 | 390px touch-target check (WCAG 2.5.8; targets under 44px are flagged) | `bash qa-gates/touch-target-check.sh [url]` |

## What's here

- `security-watch/data-room-gate.sh` — gate 1 scanner (default target: the
  production `data-room/` directory)
- `security-watch/gate-allowlist.txt` — allowlist for gate 1 false positives
  (register them here instead of weakening the scanner)
- `security-watch/color-audit.py`, `security-watch/shadow-audit.py` —
  color-contrast and shadow-DOM probe audits
- `security-watch/archive/` — historical audit artifacts, kept separate
  from the live scripts
- `qa-gates/touch-target-check.sh` — gate 3 mobile touch-target check

## Running the checks

```bash
bash security-watch/data-room-gate.sh
bash qa-gates/touch-target-check.sh https://vertciti.com/
```

## CI / security

- CI (`.github/workflows/ci.yml`): shellcheck and `bash -n` on scripts,
  `py_compile` on Python, plus the gitleaks secret scan.
- See [.github/SECURITY.md](.github/SECURITY.md) and
  [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).
