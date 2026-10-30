# Changelog

本文件记录本仓库的重要变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。
本仓库尚未发布带版本号的正式版本（无 git tag），以下全部归入 Unreleased，条目来自 `git log`。

All notable changes to this project are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). No tagged release exists
yet, so everything is listed under Unreleased, derived from `git log`.

## [Unreleased]

### Security
- 门禁 3：`touch-target-routes.txt`（站点真实路径）只用于 http(s) 目标。此前它也作用于 `file://` 目标（README 的无参数模式：测生产 `index.html`），`/business/` 被解析成 `file:///business/`（文件系统根目录），该模式先"测"了根目录列表再崩溃退出；现 `file://` 目标沿用内置 hash 路由，若经环境变量强行给 `file://` 指定路径路由则明确 FAIL / gate 3 applies the routes file to http(s) targets only.
- 门禁 1 机器可读运行记录：设 `GATE_JSON_OUT=<路径>` 时，每次运行（含中途 fail-closed 退出）结束都写 JSON——结果与退出码、模式集形态与 sha256、allowlist 与脚本 sha256、被扫文件清单指纹（相对路径 + 文件 sha256）、每条命中的规则/级别/相对路径/行号，**不含命中内容**；要求了记录却写不出即 exit 1（#6 OPS-2、§4c-1）/ gate 1 writes an optional machine-readable run record (locations only, never content).
- 门禁 1：数据目录内的符号链接改为 FAIL。`grep -r` 不跟随、`find -type f` 不计数，链接目标却可能随发布带出（#6 复现 G2）/ gate 1 fails on symlinks.
- 门禁 3：完全移出页面的元素（如 `left:-9999px` 的跳转链接）不再误报为触控违规（#6 §2.2）/ gate 3 ignores fully off-page elements.
- 门禁 2 落成脚本 `qa-gates/homepage-200-check.sh`：取站点自身状态码（`curl -w '%{http_code}'`，不跟随重定向），非 200 / 连接失败 / 超时即 exit 1。此前只是文档里的 `curl -sI … | head -1`，退出码恒为 0，且在代理后读到的是代理的 CONNECT 200（#6 ARCH-6）/ gate 2 is now a real script.
- 门禁 3 覆盖面自检：所有路由渲染出完全相同的可交互布局即 FAIL——#6 实测线上站点用真实路径导航、不认 `#page=` 路由，门禁实际是把首页测了 14 遍；新增 `TOUCH_TARGET_ROUTES` 指定真实路由（以 `/` 开头按路径访问）/ gate 3 fails when every route renders the same page; real routes via TOUCH_TARGET_ROUTES.
- 门禁 3 路由表落入配置：新增 `qa-gates/touch-target-routes.txt` 为发布管线定版表（2026-10-27 按线上 sitemap 65 条与首页链接面核定：`/ /business/ /data-room/ /company/ /accessibility/ /contact/`，逐条 200 且布局互异）；脚本在环境变量未设时自动读该文件（环境变量优先），并以 `[routes] source=` 日志标明生效来源，缺文件才回落内建 hash 路由 / gate 3 route table now ships as a config file the script reads when the env var is unset (env still wins), with the source logged per run.
- 所有 GitHub Actions 改为按完整 commit SHA 固定（版本号留在行尾注释，供 Dependabot 更新；scorecard-action 顺带升到 v2.5.0，取代 #4），见独立评估 #5 P2-5 / all GitHub Actions pinned to full commit SHAs (assessment #5).
- CI 测试工具改为按哈希锁定安装：`requirements-dev.in` → `pip-compile --generate-hashes` → `requirements-dev.txt`，CI 用 `pip install --require-hashes`；Dependabot 的 pip 生态此前指向 `/` 却没有任何清单，现在有了（#6 SEC-A5）/ CI test tools installed from a hash-locked requirements-dev.txt.
- `.github/SECURITY.md` 给出实际的私下报告渠道（GitHub private vulnerability reporting，已启用）；原文只写"直接邮件联系维护者"却没有地址（#5 P2-7）/ SECURITY.md now names a working private reporting channel.
- 门禁 1 骨架运行不再以 PASS/exit 0 结束（独立评估 #5 复核发现的新失效开放）：未设 `GATE_PATTERN_FILE` 时规则 1/2 是合成占位，真实封存内容不会命中，原先却照常 exit 0；按 README 快速开始原样运行即可复现。现无 FAIL 时 exit 3（NON-BINDING），`GATE_ALLOW_SKELETON=1` 仅供本地/测试恢复 0 / skeleton runs exit 3 instead of passing.
- 门禁 1 模式集双层化（GC-20261027-002）：六规则模式串移出脚本本体——仓内只留结构骨架 `gate-patterns-skeleton.txt`（真合成模式、非完整门禁），全量模式集存部署侧私有面，约束性运行前验 sha256 指纹、不符 fail-closed；判据内容不变。受保护字面量（规则 1 日期全变体、规则 2 三词）全仓归零（含注释、测试、fixtures 与文档）/ gate 1 pattern set split into two tiers (in-repo synthetic skeleton + deployment-side full set, sha256 fingerprint verified before binding runs, fail-closed on mismatch); detection criteria unchanged.
- 门禁 1 `data-room-gate.sh` 覆盖面补强，见独立评估 #5（在 #6 的 fail-closed / 精确 allowlist / 脱敏输出之上）/ gate 1 coverage fixes (assessment #5, on top of #6):
  扫描全部文件而非只扫 `*.txt`；二进制文件改为 FAIL，人工复核后以 `bin:<相对路径>:<sha256>` 登记放行；
  不再按 "classification" 整行豁免规则 2 字样；规则 1 增加多种日期写法（分隔符/中文年月/英文月份名变体）与
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
