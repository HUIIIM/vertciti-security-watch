# security-watch

安全与发布门禁脚本区。官网每次发布前必跑三门禁（任一 FAIL 停发）：

| 门禁 | 脚本 | 说明 |
|---|---|---|
| 1 | `bash data-room-gate.sh [--help] [目录]` | data-room 敏感信息扫描（全部文件，双层形态）：规则 1（封存日期）/规则 2（停发字样）/私钥/token/无法扫描的二进制或不可读文件/空目录为 FAIL，口令赋值/邮箱为 WARN 人工复核。目录经参数或 `DATA_ROOM_DIR` 指定。 |
| 2 | `bash ../qa-gates/homepage-200-check.sh [URL]` | 部署后验证首页 HTTP 200；非 200、重定向、连接失败均 FAIL。 |
| 3 | `bash ../qa-gates/touch-target-check.sh [--help] [URL]` | 390px 触控目标检查（WCAG 2.5.8，<44px 违规；非 2xx、JS 报错、空路由也 FAIL）。 |

- `gate-patterns-skeleton.txt`：门禁 1 的仓内骨架模式集（双层形态）——六规则的结构与合成模式在仓，仅供结构测试与非约束性运行，**不是完整门禁**；全量模式集存部署侧私有面，发布运行经 `GATE_PATTERN_FILE` 装载并按登记指纹验真（`GATE_PATTERN_SHA256` / `GATE_PATTERN_FP_FILE`），不符即停发。
- `gate-allowlist.txt`：门禁 1 的放行白名单（误报在此登记；格式 `相对路径:行号:精确内容`、`fp:<sha256>` 或二进制文件的 `bin:相对路径:<sha256>`，精确比对，见文件头）。
- `color-audit.py` / `shadow-audit.py`：只读审计脚本，分别统计首页内联 CSS 的色值、列出 box-shadow 声明（不计算对比度）。
- `archive/`：历史审计产物归档（不与脚本混放）。
