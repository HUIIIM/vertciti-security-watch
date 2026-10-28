# vertciti security-watch

vertciti.com 生产发布前运行的三道发布门禁脚本（敏感信息扫描、首页 200、390px 触控目标），给负责发布 vertciti.com 的维护者使用；任一门禁 FAIL 即停止发布。

| | |
|---|---|
| 状态 | 内部工具，维护中；尚无带版本号的发布（无 git tag）。CI 在 push 到 main 和 PR 时运行 ruff、pytest、`py_compile`、shellcheck；另有 CodeQL、dependency-review、gitleaks、Scorecard |
| 部署 | 不部署：在发布流水线或维护者本机运行。需要 bash、Python 3（CI 用 3.13）；门禁 3 需要 Playwright＋Chromium。脚本默认路径绑定维护者本机目录 |
| 在线演示 | 不适用 |
| 接口 | 命令行（bash 门禁脚本 · 只读 Python 审计脚本），以退出码表示通过/失败 |
| 许可证 | 专有，保留所有权利，VERTCITY LLC（[LICENSE](LICENSE)，法务裁定文本） |
| 语言 | 简体中文（安全、许可证段落附英文） |
| 联系 | 安全漏洞：[.github/SECURITY.md](.github/SECURITY.md) · 产品：[vertciti.com](https://vertciti.com) |

演示录屏（示意演示：门禁 1 通过 → 门禁 3 通过 → 混入假密钥后 FAIL 停发；该 GIF 与截图为合成示意图、非真实运行录制，真实录屏待重录）、架构图和门禁运行截图在
[docs/assets](docs/assets)；仓库已公开，演示图以链接形式给出、不内嵌。演示用的是假密钥（`ghp_fake…`），不含任何真实凭证。

## 概览

vertciti.com 每次生产发布前要过三道门禁，全部脚本化：敏感信息扫描、首页返回 200、390px 视口下的触控目标尺寸。
三道门禁是发布流水线的硬门，不是建议：脚本 FAIL 时 exit 1，发布必须停下，没有"这次先过"的开关。
误报在 allowlist 里登记，而不是放宽扫描器。产品一页纸见 [docs/PRODUCT.md](docs/PRODUCT.md)。

## 能力一览

| # | 门禁 / 工具 | 脚本 | 判定 |
|---|---|---|---|
| 1 | 敏感信息扫描 | `security-watch/data-room-gate.sh [目录]` | 扫描目录内全部文件（不限 .txt）。FAIL：私钥 / `ghp_` 等 token / 规则 2 停发字样 / 规则 1 封存日期及其各种写法 / 无法按文本扫描的文件（二进制、不可读）/ 目录为空。WARN（人工复核）：口令赋值、邮箱地址。命中默认脱敏输出（`路径:行号` + 掩码/指纹），不回显明文 |
| 2 | 首页可访问 | `qa-gates/homepage-200-check.sh [URL]` | 站点自身返回的状态码非 200（含重定向、4xx/5xx、连接失败、超时）即 FAIL |
| 3 | 触控目标 | `qa-gates/touch-target-check.sh [URL]` | headless 渲染后量取所有可见可交互元素的 boundingBox，390px 视口下宽或高 < 44px 即 FAIL（WCAG 2.5.8）；纯文本内联链接豁免但留痕。页面返回非 2xx、出现 JS 报错或某条路由量不到任何可交互元素时也 FAIL；所有路由渲染出相同布局时 FAIL（路由表与站点不符，实际只测了一页），真实路由可经 `TOUCH_TARGET_ROUTES` 指定；环境变量未设时读脚本同目录的 `touch-target-routes.txt`（发布管线定版表，2026-10-27 按线上 sitemap 与首页链接面核定为 `/ /business/ /data-room/ /company/ /accessibility/ /contact/`），运行日志以 `[routes] source=` 标明实际生效来源 |
| — | 颜色审计 | `security-watch/color-audit.py` | 只读：提取首页内联 CSS 与 `style=` 中的全部色值并统计 |
| — | box-shadow 审计 | `security-watch/shadow-audit.py` | 只读：列出首页每条 box-shadow 声明的选择器、行号与取值 |
| — | allowlist | `security-watch/gate-allowlist.txt` | 门禁 1 的误报在这里登记：按 `文件:行号:精确内容`（或 `fp:` 指纹）逐实例登记，二进制文件以 `bin:路径:sha256` 登记，子串匹配已废止；部署侧登记为准，仓内文件只有格式说明；审计产物归档在 `security-watch/archive/` |

## 快速开始

```bash
cd vertciti-security-watch
bash security-watch/data-room-gate.sh --help        # 看门禁 1 的 FAIL/WARN 规则
bash security-watch/data-room-gate.sh ./data-room   # 骨架运行：无 FAIL 时 exit 3（NON-BINDING），不是放行
# 发布运行：GATE_PATTERN_FILE=<部署侧全量模式集> GATE_PATTERN_SHA256=<登记指纹> bash security-watch/data-room-gate.sh ./data-room
```

```bash
bash qa-gates/touch-target-check.sh https://vertciti.com/  # 门禁 3：390px 触控目标
bash qa-gates/homepage-200-check.sh https://vertciti.com/  # 门禁 2：首页 200
```

开发检查：

```bash
pip install --require-hashes -r requirements-dev.txt   # 与 CI 同一份哈希锁定的工具版本
ruff check .          # lint（规则见 ruff.toml）
python3 -m pytest -q  # 冒烟测试
```

CI 配置在 `.github/workflows/ci.yml`（ruff＋pytest、`py_compile`、shellcheck），gitleaks 密钥扫描在
`.github/workflows/gitleaks.yml`。

## 架构

```
vertciti-security-watch/
├── security-watch/   # 门禁 1（data-room-gate.sh）、allowlist、只读审计脚本与归档
├── qa-gates/         # 门禁 3（touch-target-check.sh，Playwright + Chromium）
├── tests/            # 审计脚本冒烟测试
└── docs/             # PRODUCT.md 与 assets
```

每道门禁是独立脚本，以退出码向发布流水线报告结果；门禁 2 为 `qa-gates/homepage-200-check.sh`（此前只是文档里一条 `curl -sI … | head -1`，退出码恒为 0）。架构图见
[docs/assets/architecture.png](docs/assets/architecture.png)。

## 安全与合规

- 门禁脚本只做它声明的事：扫描、断言、报告。不自动改生产，不动防火墙。
- 审计脚本只读：不修改输入文件，也不向外推送结果。
- 发现安全问题请勿开公开 issue，按 [.github/SECURITY.md](.github/SECURITY.md) 的流程私下报告。
  Please do not open a public issue for vulnerabilities; follow [.github/SECURITY.md](.github/SECURITY.md).

## 现状与边界

内部工具，维护中，尚无带版本号的发布；变更记录见 [CHANGELOG.md](CHANGELOG.md)。

已知限制：
- 门禁 1 为双层形态（GC-20261027-002）：仓内 `gate-patterns-skeleton.txt` 只是结构骨架（真合成模式），不是完整门禁；具约束力的发布运行装载部署侧私有全量模式集并先验 sha256 指纹，不符或缺失即 fail-closed 停发、不回退骨架判定。未装载全量模式集的骨架运行在无 FAIL 时以 exit 3（NON-BINDING）结束，不会以 0 被流水线当作放行；本地调试/测试可设 `GATE_ALLOW_SKELETON=1` 恢复 0。
  A skeleton run (no full pattern set loaded) never exits 0: without a FAIL it ends with exit 3 (NON-BINDING); `GATE_ALLOW_SKELETON=1` restores exit 0 for local/test use only.
  Gate 1 is two-tier: the in-repo pattern file is a synthetic skeleton, not the complete gate; binding release runs load the deployment-side full pattern set and verify its registered sha256 fingerprint first, failing closed on any mismatch.
- `data-room-gate.sh` 的 allowlist 按脚本同目录相对解析、随脚本分发；缺失/不可读时 fail-closed 停发，
  不再静默跳过检查（早期固定机器专属绝对路径、不可达时假过 PASS 的问题已修复）。条目为精确匹配
  （`文件:行号:精确内容` 或 `fp:` 指纹），子串匹配已废止；可扫描文件数为 0 时 FAIL（2026-10-26，issue #6）。
  The allowlist resolves relative to the script's own directory and ships with it; a missing or
  unreadable allowlist fails closed instead of silently skipping checks. Entries match exactly
  (`file:line:exact content` or `fp:` fingerprints); substring matching was abolished, and zero
  scannable files fails instead of passing vacuously (2026-10-26, issue #6).
- 门禁 1 扫描全部文件（不限 .txt），但不解析 PDF/DOCX 等二进制文件：这类文件一律 FAIL，人工复核后以
  `bin:<相对路径>:<sha256(文件)>` 登记放行，文件变化后条目失效（issue #5）。
  Gate 1 scans every file but does not parse binaries (PDF/DOCX/…): they fail until reviewed and
  allowlisted as `bin:<path>:<sha256>`, an entry that goes stale when the file changes (issue #5).
- 审计脚本与门禁 3 的解释器/目标路径经环境变量显式指定（无内置默认）；门禁 3 的浏览器默认 `/opt/meta-chromium/chrome`，可经 `TOUCH_TARGET_CHROME` 覆盖。

更多见 [docs/PRODUCT.md](docs/PRODUCT.md)。

## 文档 · 支持 · 许可证

[产品一页纸](docs/PRODUCT.md) · [更新记录](CHANGELOG.md) · [security-watch 说明](security-watch/README.md) ·
[贡献说明](.github/CONTRIBUTING.md)

本仓库为 vertciti 内部工程，暂不接受外部 PR；发现问题请走内部渠道。

**许可证 / License**：专有许可（非开源），保留所有权利，详见 [LICENSE](LICENSE)。权利人 VERTCITY LLC，
文本经法务裁定。
Proprietary, all rights reserved — see [LICENSE](LICENSE). Rights holder: VERTCITY LLC; the text is the
legally reviewed version.

---

由 [vertciti](https://vertciti.com) 构建。vertciti 为 Miao 构建运营人生的个人 AI 基础设施。
