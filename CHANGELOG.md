# Changelog

本文件记录本仓库的重要变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。
本仓库尚未发布带版本号的正式版本（无 git tag），以下全部归入 Unreleased，条目来自 `git log`。

All notable changes to this project are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). No tagged release exists
yet, so everything is listed under Unreleased, derived from `git log`.

## [Unreleased]

### Added
- 产品一页纸 `docs/PRODUCT.md` 与本 CHANGELOG / product one-pager and this changelog (2026-10-22).
- README 增加状态说明、`## 安全 / Security`、`## 许可证 / License` 双语章节 / README status line and bilingual security and license sections (2026-10-22).
- `tests/test_audit_scripts.py`：8 个 pytest 冒烟测试，覆盖 color-audit、shadow-audit、data-room-gate / 8 pytest smoke tests (2026-10-22).
- CI `test` job：ruff（规则见 `ruff.toml`）+ pytest，在 pull_request 与 push 到 main 时运行 / CI job running ruff and pytest (2026-10-22).
- 工程基线：CODEOWNERS、`.editorconfig`，各 workflow 设置最小权限与 `timeout-minutes` / engineering baseline (2026-10-22, `cc1f563`).
- README v1.0：hero 图、demo GIF、架构图、截图、徽章、30 秒 quickstart (2026-10-02, `9ca0319`).
- README 补全门禁说明 / README documents the gates (2026-09-27, `cabb9d9`).
- Issue/PR 模板、SECURITY.md、CONTRIBUTING.md、README 徽章 / issue and PR templates, SECURITY.md, CONTRIBUTING.md (2026-09-27, `5215eb1`).
- AGENTS.md、Copilot 指令、Dependabot、CI、CodeQL、gitleaks、Scorecard、dependency-review、pre-commit (2026-09-27, `661bc55`).
- 初始导入：data-room 门禁、触控目标门禁、color-audit / shadow-audit 脚本与 2026-09-27 审计归档 / initial import of gate and audit scripts (2026-09-27, `8d8bc42`).

### Changed
- `security-watch/color-audit.py`：为通过 ruff 做的等价改写（拆分 import 与分号语句、重命名变量 `l`、闭包显式绑定循环变量），行为不变 / behavior-preserving lint fixes (2026-10-22).
- GitHub Actions 升级到最新主版本 / GitHub Actions upgraded to latest major versions (2026-09-27, `6b61814`).

### Fixed
- gitleaks workflow 增加 `pull-requests: read` 权限 / gitleaks workflow gains `pull-requests: read` (2026-10-22).
