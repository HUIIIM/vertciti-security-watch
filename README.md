![vertciti security-watch](docs/assets/hero.png)

[![CI](https://github.com/HUIIIM/vertciti-security-watch/actions/workflows/ci.yml/badge.svg)](https://github.com/HUIIIM/vertciti-security-watch/actions/workflows/ci.yml)
[![Secret scan](https://github.com/HUIIIM/vertciti-security-watch/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/HUIIIM/vertciti-security-watch/actions/workflows/gitleaks.yml)
[![license](https://img.shields.io/badge/license-proprietary-lightgrey)](LICENSE)

**vertciti.com 每次生产发布前必跑的三道门禁**——敏感信息扫描、首页 200、
390px 触控目标，全部脚本化；任一 FAIL 即停发，没有例外。

![demo](docs/assets/demo.gif)

> demo GIF 为本机真实运行：门禁 1 通过 → 门禁 3 通过 → 混入假密钥后 FAIL
> 停发。演示用假密钥（`ghp_fake…`），不含任何真实凭证。

## 30 秒 quickstart

```bash
cd vertciti-security-watch
bash security-watch/data-room-gate.sh --help   # 看门禁 1 的 FAIL/WARN 规则
bash security-watch/data-room-gate.sh ./data-room   # 扫一个目录（默认扫生产 data-room）
```

```bash
bash qa-gates/touch-target-check.sh https://vertciti.com/  # 门禁 3：390px 触控目标
curl -sI https://vertciti.com/ | head -1                   # 门禁 2：首页 200
```

## 它是怎么工作的

![架构](docs/assets/architecture.png)

三门禁是发布流水线的硬门，不是建议：

| # | 门禁 | 脚本 | FAIL 条件 |
|---|---|---|---|
| 1 | 敏感信息扫描 | `security-watch/data-room-gate.sh [目录]` | 私钥 / `ghp_` 等 token / 绝密字样 / `2027-02` |
| 2 | 首页可访问 | `curl -sI https://vertciti.com/` → 200 | 非 200（部署任务内执行） |
| 3 | 触控目标 | `qa-gates/touch-target-check.sh [URL]` | 390px 视口下可交互元素 < 44px |

门禁 1 的 WARN（人工复核）：口令赋值、邮箱地址——在
`security-watch/gate-allowlist.txt` 登记误报，而不是放宽扫描器。

![门禁运行](docs/assets/screenshot-gate.png)

## 功能

- **门禁 1：data-room 敏感扫描**——2027-02 / 绝密字样 / 私钥 / token 为
  FAIL；口令赋值 / 邮箱为 WARN。默认扫描生产 `data-room/`。
- **门禁 3：390px 触控目标检查**——headless 渲染量取所有可见可交互元素
  boundingBox，断言宽高 ≥ 44px（WCAG 2.5.8）；纯文本内联链接豁免但留痕。
- **颜色对比度审计**（`color-audit.py`）与**影子探针审计**（`shadow-audit.py`）——
  独立运行的审计脚本，产物归档在 `security-watch/archive/`。
- **allowlist 机制**：误报在 `gate-allowlist.txt` 登记，扫描器本身不放水。

## 诚实约定

- 门禁脚本只做它声明的事：扫描/断言/报告，不自动改生产、不动防火墙。
- FAIL 就是停发——脚本 exit 1，发布流水线必须停，没有"这次先过"的开关。
- 影子探针（shadow-audit）只观测记录，不向外推送。

## 测试

```bash
bash -n security-watch/data-room-gate.sh && echo "gate syntax OK"
bash -n qa-gates/touch-target-check.sh && echo "touch syntax OK"
python3 -m py_compile security-watch/color-audit.py security-watch/shadow-audit.py && echo "py OK"
# 真实跑一遍（2026-10-02 本机实测）：
bash security-watch/data-room-gate.sh   # 默认扫生产 data-room
```

CI（`.github/workflows/ci.yml`）：shell 脚本 `bash -n`、Python `py_compile`、
gitleaks 密钥扫描，push/PR 自动跑。

## 贡献

本仓库为 vertciti 内部工程，暂不接受外部 PR；发现问题请走内部渠道。

## 关于 vertciti

vertciti 为 Miao 构建运营人生的个人 AI 基础设施。

## 许可证

vertciti clean-room engineering — proprietary. 详见 [LICENSE](LICENSE)。
