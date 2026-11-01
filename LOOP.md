# Loop state — vertciti-security-watch

Updated: 2026-11-01 (loop bootstrap). Facts here are the standing state;
when one changes, the PR that changes it updates this file.

## Direction channel

- Tasks: GitHub Issues labeled `jarvis-task` in this repo.
- Reviews and verdicts: PR comments only.
- Merge owner: Jarvis. External Claude opens PRs from `claude/*` branches.

## Decisions in force

- License disposition (owner ruling, 2026-10-31): proprietary, kept.
- All GitHub Actions references were SHA-pinned in the SEC-11 sweep.

## Acceptance rules

- CI green on the current head before merge; dependency-group updates
  read diff-first.
