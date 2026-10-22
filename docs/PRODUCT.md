# vertciti security-watch — 产品一页纸 / Product one-pager

> 状态 / Status：active（内部工具 / internal tool）· 版本 / Version：未发布正式版本（无 git tag）/ no tagged release · 更新 / Updated：2026-10-22
> 所属 / Part of：[vertciti](https://vertciti.com) — 一家公司，一个人生。

## 一句话 / One line
vertciti 维护者在 vertciti.com 发布前运行这组脚本，对 data-room 敏感信息、首页可访问性和 390px 触控目标做门禁检查，任一 FAIL 即停发。
The vertciti maintainer runs these scripts before a vertciti.com release to gate on data-room secrets, homepage availability and 390px touch targets; any FAIL stops the release.

## 解决什么问题 / Problem
- 痛点 / Pain：官网发布前需要确认公开的 data-room 不含私钥、token、绝密字样或 `2027-02` 相关内容，且移动端触控目标不小于 44px。发布频率与历史事故代价：未确认（TBD）。
  Before publishing, the public data-room must not contain private keys, tokens, classified markers or `2027-02` content, and mobile touch targets must be at least 44px. Release frequency and cost of past incidents: TBD.
- 现在的替代做法 / Current alternative：人工逐文件检查或依赖通用扫描器；本仓库把规则写成脚本，FAIL 时 exit 1。是否优于其他做法：未确认（TBD），无对比数据。
  Manual review or generic scanners; this repo encodes the rules as scripts that exit 1 on FAIL. No comparison data exists.

## 给谁 / For whom
- 首要用户 / Primary user：vertciti 官网维护者（Miao）及在其工作区运行的 agent。
- 不是给谁 / Not for：外部用户或通用 CI 场景——脚本默认路径绑定维护者本机目录结构（见"已知限制"）。
  External users or generic CI use; default paths are tied to the maintainer's local layout (see limitations).

## 怎么用（三步）/ How to use
1. 门禁 1 / Gate 1：`bash security-watch/data-room-gate.sh [目录]` — 扫描 `*.txt`，FAIL 时 exit 1。
2. 门禁 2 / Gate 2：`curl -sI https://vertciti.com/ | head -1` — 期望 HTTP 200。
3. 门禁 3 / Gate 3：`bash qa-gates/touch-target-check.sh [URL]` — 390px 视口下可交互元素宽高均需 ≥ 44px；依赖 `~/workspace/.qa-venv`（playwright）与 `/opt/meta-chromium/chrome`。

另有两个只读审计脚本 / Two read-only audit scripts：`security-watch/color-audit.py <index.html> [--json out.json]`（色值统计与聚类）、`security-watch/shadow-audit.py [--json PATH] [--table]`（box-shadow 逐项清单）。

## 为什么是我们（差异化）/ Differentiation
| 维度 / Dimension | 本仓库 / This repo | 常见替代 / Common alternative |
|---|---|---|
| 规则来源 / Rules | 针对 vertciti data-room 的定制规则（如 `2027-02` 硬红线） / custom rules for the vertciti data-room | 通用密钥规则 / generic secret patterns |
| 误报处理 / False positives | 在 allowlist 文件登记，不改扫描规则 / registered in an allowlist file | 视工具而定 / tool-dependent |
| 与其他方案的效果对比 / Measured comparison | 未确认（TBD） | 未确认（TBD） |

## 证据 / Evidence
- 测试 / Tests：`tests/test_audit_scripts.py` 共 8 个 pytest 用例（2026-10-22 本地运行 8 passed），覆盖 color-audit 归一化与提取、shadow-audit 规则解析、data-room-gate 的 PASS / token FAIL / 目录不存在 FAIL。CI：`.github/workflows/ci.yml` 的 `test` job（pytest + ruff）。
  8 pytest cases, run locally on 2026-10-22: 8 passed.
- 真实运行 / Real runs：`docs/assets/demo.gif`、`docs/assets/screenshot-gate.png`；`security-watch/archive/color-audit-2026-09-27.json`（一次 color-audit 的归档输出）。
- 不能证明的 / Not proven：门禁 3（touch-target-check.sh）与 shadow-audit.py 依赖本机文件与浏览器环境，测试未覆盖其端到端运行；生产发布流水线是否强制调用这些脚本，本仓库内无法验证。
  Gate 3 and shadow-audit.py depend on local files/browser and are not covered end-to-end; whether the production pipeline enforces these gates is not verifiable from this repo.

## 边界与风险 / Scope and risks
- 不做 / Does not：不自动修改生产文件、不改防火墙、不向外推送（见 README"诚实约定"）。
- 已知限制 / Known limitations：
  - `data-room-gate.sh` 的 allowlist 路径固定为 `$HOME/workspace/vertcity/security-watch/gate-allowlist.txt`，不是本仓库的 `security-watch/gate-allowlist.txt`。若该目录不存在，`grep -f` 报错，FAIL/WARN 检查（`2027-02`、绝密字样、token、口令、邮箱）会被跳过并输出 PASS（2026-10-22 本地复现）。私钥块检查不受影响。
    The allowlist path is fixed to `$HOME/workspace/vertcity/...`; if that directory is missing, most checks are silently skipped and the gate reports PASS (reproduced locally 2026-10-22). The private-key check is unaffected.
  - 只扫描 `*.txt` 文件 / Only `*.txt` files are scanned.
  - `shadow-audit.py` 输入路径硬编码为 `/home/hatch/workspace/vertcity/deploy-prod-root/index.html`，无命令行参数可改。
  - `touch-target-check.sh` 默认目标与依赖路径绑定维护者本机。
- 安全与隐私 / Security & privacy：脚本只读本地文件并输出到 stdout（命中的 token 只输出前缀如 `ghp_****`，其余打码 / matched tokens print only their prefix）；不存储、不上传数据。漏洞报告见 [`.github/SECURITY.md`](../.github/SECURITY.md)。

## 与其他 vertciti 产品的组合 / With other vertciti products
- 与 vertciti.com 官网发布流程：作为发布前门禁。具体集成方式在本仓库内未定义——未确认（TBD）。

## 路线图 / Roadmap
| 阶段 / Stage | 内容 / Content | 退出标准 / Exit criteria |
|---|---|---|
| Now | CI 运行 pytest + ruff + shellcheck + gitleaks | CI 全绿 / CI green |
| Next | 未确认（TBD）— 候选：修复 allowlist 缺失时放行的问题 / candidate: fix fail-open on missing allowlist | 未确认（TBD） |
| Later | 未确认（TBD） | 未确认（TBD） |

## 衡量指标 / Metrics
- 北极星 / North star：未确认（TBD）
- 护栏 / Guardrails：未确认（TBD）
