# vertciti-security-watch

Security watch tooling for the vertciti fleet (scanning, gates, drift
watching). Public repository, proprietary license: all rights reserved,
Copyright (c) 2026 VERTCITY LLC. "Public" means visible as a showcase
surface; it does not grant code-reuse rights.

## How work happens here

- Direction arrives in-repo: GitHub Issues labeled `jarvis-task`, PR
  review comments, and `CLAUDE.md` / `LOOP.md`. Read both at session start.
- External Claude works on `claude/*` branches and opens PRs; it never
  merges its own PRs. Jarvis reviews and merges.
- Review verdicts exist only as PR comments.

## Working rules

- This is a security surface: read the full diff of any dependency or
  workflow change before it merges; no rubber-stamping.
- Findings are reported with file and line evidence; a scanner claim
  without a readable source location is not a finding.
- Private vulnerability reporting is enabled on this repo.
