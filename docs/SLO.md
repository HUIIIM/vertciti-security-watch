# 门禁运行 SLO / Gate run SLOs (OPS-2)

本页定义 vertciti 三道门禁自身的服务水平目标。衡量对象是"门禁是否在运行、是否给出了有约束力的判定"，不是被测站点。

This page defines service-level objectives for the three vertciti gates themselves. They measure whether the gates run and reach a binding verdict, not the site under test.

## 数据来源 / Data

- 每道门禁设 `GATE_JSON_OUT=<路径>` 时都会写一份 JSON 运行记录：门禁 1 为 `security-watch/data-room-gate.sh`，门禁 2、3 经 `qa-gates/run_record.py` 写出。核心字段相同：`gate`、`run_id`、`trace_id`、`started_at`/`finished_at`、`result`、`exit_code`。
- 发布流水线设 `GATE_TRACE_ID` 时，同一次发布的三道门禁共用一个 `trace_id`；未设时，`trace_id` 取本次的 `run_id`。
- `scripts/run-log.py append <LOG> <记录>...` 把记录摘要追加进一份只追加、带哈希链的 JSONL 日志。每行含 `prev_sha256` 与 `record_sha256`，任一行被改、删或调序都会使链从该行起断开。`run-log.py verify` 校验整条链。

## SLO

| 编号 | 指标 / Indicator | 目标 / Target | 窗口 / Window |
|---|---|---|---|
| SLO-1 | 判定率：以 `PASS`/`FAIL`/`WARN` 结束的运行占比；`USAGE`、`ERROR` 与门禁 1 的 `NON-BINDING`（骨架模式集）都计为未达成 / verdict rate | ≥ 99 % | 滚动 30 天 / rolling 30 days |
| SLO-2 | 新鲜度：每道预期门禁在最近 26 小时内都有一次结束的运行 / freshness | 100 % | 最近 26 h（每日一次加 2 h 余量） |

`FAIL` 计为**达成**：门禁拦下了问题，就是在正常工作。SLO 衡量的是门禁能否给出判定，不是站点是否合格。

## 告警 / Alerting

`scripts/run-log.py slo <LOG>` 计算两条 SLO。出现以下任一情况时，它打印 `[ALERT]` 行并以 exit 1 退出：违约、哈希链断开、日志不存在、窗口内无数据。告警通道是 `.github/workflows/monitor.yml`，每日一次加手动触发：

1. `probe` job 只持只读令牌，不保留凭据。它以门禁 2 探测 `https://vertciti.com/` 并写运行记录；`trace_id` 为 `monitor-<run_id>-<attempt>`。
2. `record` job 把记录追加进 `monitor/run-log` 分支的 `runs.jsonl`，这条分支只由本 job 推送，不是 main。probe 没产出记录时记一次 `ERROR`，这次中断照样计入 SLO-1。随后跑 `slo --gates homepage-200`。
3. 门禁不是 `PASS`、或 SLO 违约时，开一个 `[monitor-alert]` issue；已有打开的就追加评论；本次运行标红。下一次健康运行时评论并关闭该 issue。

目前只监控门禁 2。门禁 3 需要 Playwright 与浏览器，待 #35 的 CI 依赖入 main 后接入；门禁 1 的 data-room 不在本仓，由发布流水线负责（#25）。

## 未覆盖 / Not covered

- 发布流水线不在本仓，其是否设置 `GATE_JSON_OUT` / `GATE_TRACE_ID` 并调用 `append`，本仓无法验证（#25）。
- 日志本身存放在哪里、由谁持有写权限，决定了哈希链能防到什么程度：链能发现改写，但不能防止整份日志被替换。外部只追加存储另行决定。
