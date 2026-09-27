# security-watch

安全与发布门禁脚本区。官网每次发布前必跑三门禁（任一 FAIL 停发）：

| 门禁 | 脚本 | 说明 |
|---|---|---|
| 1 | `bash data-room-gate.sh [--help] [目录]` | data-room 敏感信息扫描：2027-02/绝密字样/私钥/token 为 FAIL，口令赋值/邮箱为 WARN 人工复核。默认扫描 `deploy-prod-root/data-room`。 |
| 2 | `curl -sI https://vertciti.com/` | 部署后验证首页 HTTP 200（门禁 2 在部署任务内执行）。 |
| 3 | `bash ../deliverables/qa-gates/touch-target-check.sh [--help] [URL]` | 390px 触控目标检查（WCAG 2.5.8，<44px 违规）。 |

- `gate-allowlist.txt`：门禁 1 的放行白名单（误报在此登记）。
- `color-audit.py` / `shadow-audit.py`：颜色对比度与影子探针审计脚本。
- `archive/`：历史审计产物归档（不与脚本混放）。
