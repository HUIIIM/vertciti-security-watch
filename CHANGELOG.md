# Changelog

本文件记录本仓库的重要变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。
本仓库尚未发布带版本号的正式版本（无 git tag），以下全部归入 Unreleased，条目来自 `git log`。

All notable changes to this project are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). No tagged release exists
yet, so everything is listed under Unreleased, derived from `git log`.

## [Unreleased]

### Security
- 门禁 1 `data-room-gate.sh` 覆盖面补强，见独立评估 #5（在 #6 的 fail-closed / 精确 allowlist / 脱敏输出之上）/ gate 1 coverage fixes (assessment #5, on top of #6):
  扫描全部文件而非只扫 `*.txt`；二进制文件改为 FAIL，人工复核后以 `bin:<相对路径>:<sha256>` 登记放行；
  不再按 "classification" 整行豁免绝密字样；增加 `2027/02`、`2027年2月`、`Feb 2027` 等写法与
  `github_pat_`、`ghs_/ghu_/ghr_`、`sk-ant-`、`AIza` token。
- 门禁 3 `touch-target-check.sh`：页面非 2xx、JS 报错或路由量不到任何可交互元素时 FAIL（原来空白页/错误页也报 PASS）；
  浏览器路径可经 `TOUCH_TARGET_CHROME` 覆盖 / gate 3 fails on non-2xx, JS errors and empty routes.

### Fixed
- `color-audit.py`：`--json` 缺少路径时给出用法提示而非 IndexError；越界色值分量按 CSS 规则钳位 / usage error and component clamping.

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
- `security-watch/data-room-gate.sh`（issue #6）：门禁 1 改 fail-closed——`set -o pipefail`，逐检查区分 grep 退出码（≥2 为扫描出错即 FAIL）；allowlist 缺失即 FAIL（不再自动建空文件），空行/注释行剔除；可扫描 `.txt` 文件数为 0 即 FAIL，禁止真空通过 / gate 1 made fail-closed: pipefail, grep exit codes distinguished, missing allowlist fails, zero scannable files fails (2026-10-26).
- `security-watch/data-room-gate.sh`（issue #6）：allowlist 改精确匹配——条目 `文件:行号:精确内容` 或 `fp:<sha256>` 指纹，废止整行子串匹配（空行/短条目曾可放行一切）；部署侧旧条目已迁移（1 条有现行实例者转精确条目，1 条无实例者失效待重登记）/ allowlist switched to exact file:line:content or fingerprint entries, substring matching abolished (2026-10-26).
- `security-watch/data-room-gate.sh`（issue #6）：命中输出默认脱敏——只出文件:行号与掩码/指纹，口令、连接串、token 明文零出 stdout；原文输出须显式 `GATE_SHOW_CONTENT=1`（仅限本机人工复核）/ hit output redacted by default, plaintext only behind explicit GATE_SHOW_CONTENT=1 (2026-10-26).
- README 与 `docs/PRODUCT.md`：演示 GIF/截图的「本机真实运行 / Real runs」措辞改为「示意 / illustrative」——素材为合成示意图、非真实运行录制，真实录屏待重录 / demo assets re-labelled illustrative pending real re-recording (2026-10-26).
- `tests/test_audit_scripts.py`：新增 6 个门禁 fail-closed 回归用例（issue #6），共 14 个 / six new fail-closed regression tests, 14 total (2026-10-26).
- `security-watch/data-room-gate.sh`：目标目录参数化（位置参数/环境变量 `DATA_ROOM_DIR`、无内置默认），allowlist 改脚本同目录相对解析＋不可读 fail-closed，消除固定机器专属绝对路径与已退役检出路径默认；`qa-gates/touch-target-check.sh` 解释器改经 `TOUCH_TARGET_PYTHON` 指定 / gate target parameterized, allowlist script-relative with fail-closed guard, touch-target interpreter via env var (2026-10-26).
- gitleaks workflow 增加 `pull-requests: read` 权限 / gitleaks workflow gains `pull-requests: read` (2026-10-22).
