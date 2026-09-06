# V3 Deployment Report

## Current Repair Status

2026-09-06: the authorized V3 repair is implemented on `codex/v3-production`. Local V3 tests, legacy regression, frontend build and desktop/mobile fixture browser checks are being completed before rollout. This section will be updated with actual deployment evidence; the original STOP record below is retained unchanged for audit history.

Rollback remains `07a618b64069e934d5fc2194077348f93b8e556c`. No legacy cutover is reused. Fresh deployment cutover, backup hashes, migration row checks, service cycle evidence and the first natural event must be recorded before declaring production success.

## Preserved Pre-Repair STOP Report

结论：BLOCKED / NOT DEPLOYED。当前 V2 继续运行，本次未更改业务代码、配置、正式数据库或容器。

## 检查依据

- UTC 主采样时间：2026-09-06T06:23:43.968759+00:00。
- Ubuntu：novaion-node-01。
- 本地/Ubuntu branch：feat/v2-alpha-validation。
- 当前 commit：07a618b64069e934d5fc2194077348f93b8e556c。
- V1 历史 rollback 标记：66d7ed55；本次未执行回滚，也未重新验收旧备份。
- API 容器运行源码与本地 v2_validation_service.py 的 SHA-256 一致：9f0916078ec7b83078f4d339acaf044273d8014a68b4b9d995b10c5e88df59cf。

## 当前生产数据

以下计数来自同一个只读 SQLite 事务；生产仍正常写入，因此后续采样数量会增加。

| 数据 | 数量 |
| --- | ---: |
| Candidates | 200 |
| Wallet rows | 20 |
| Active Watchlist | 10 |
| Signals | 4139 |
| Paper Trades | 88 |
| Performance Records | 4138 |
| Shadow Trades | 0 |
| Shadow Trade Actions | 0 |
| Equity Snapshots | 426 |
| Data Quality Events | 0 |
| Paper Trade Actions | 35 |

2026-09-01 20:20:00 UTC 后已有 871 条 Signal：835 ignored、35 simulated、1 new。426 条权益快照全部 source=paper_trading。不能称为 30-Day Shadow Validation 已开始。

## 根因及停止条件

1. `v2_validation_service.py:205` 只读 settings.paper_trading_cutover_at；空值直接成功返回零计数。容器 Settings 已确认空值，而 V2、Shadow、Scheduler 开关均为 true。
2. Paper 的 JSON cutover 为 2026-06-20T05:54:35.942738+00:00。直接将此时间用于 Shadow，会让 948 条 V2 部署前 simulated 信号进入回放范围。不能用该值“修好”开关。
3. `v2_validation_service.py:285/301/314/325/334` 改写共享 Signal.status，Paper Processor 只消费 new。隔离复现已证明 Shadow 执行会干扰 Paper 消费；Shadow 无权替 Paper 标记 simulated。
4. `v2_validation_service.py:20` 只累计 closed ShadowTrade.net_pnl，漏计 open 仓位已发生的 Reduce 净收益。真实账户评价不能建立在此口径上。

这触发用户要求的“历史数据覆盖风险：STOP”。本次没有修改 cutover、重新处理历史信号、实现/部署 V3 或修改生产 Scheduler。

此前“没有真实新信号，所以等待”的判断不充分，已由本次实际数据纠正。

## 运行状态

API /health 返回 status=ok；Web HTTP 200。这是可用性证据，不代表 V3 业务验收。

API StartedAt：2026-09-01T20:20:35.70743201Z，running，restart=0。Web running，restart=0。原 test 与 migration-drill 容器也仍在运行。

Wallet Sync、Metrics、Discovery、Paper Update、Performance Update、Daily/Health Report、Equity Snapshot、Shadow Processor 锁均为 ok。Shadow 的 ok 仅证明函数返回，未证明消费发生。

数据库使用 mode=ro/query_only 检查，PRAGMA integrity_check=ok。未执行写入接口、health refresh 或 migration。不能据此保证所有历史业务语义无缺陷，但本次没有更改历史数据。

## Telegram 和质量证据

后续采样最近 24 小时日志显示：253 次聚合通知成功、2 次 Signal 通知成功、1 次 Daily Report 成功；未发现该窗口 Telegram 失败日志。未发送测试消息。未检查群端 message id 去重，不能把日志成功次数等同于已证明无重复。

同窗口 Hyperliquid 日志中包含 429 的记录有 6 条，Data Quality Events 总数仍为 0。它们是错误/重试日志条数，不是独立故障窗口数；现有质量覆盖尚不能支撑完整 Alpha 结论。

安全开关：ENABLE_LIVE_TRADING=false，EMERGENCY_STOP=true；本次只使用 SSH 只读检查、公开本机健康 GET 和本地隔离 SQLite 测试，没有调用真实下单或 Telegram 发送接口。

## 已执行测试和变更

隔离缺陷复现、V2 8/8、Shadow Processor 8/8、full_verify ok=true。原测试能通过但缺少消费隔离与生产等效空 cutover 覆盖，不能标为 V3 PASS。

仅新增四份 V3 文档：V3_PRODUCTION_ARCHITECTURE.md、V3_SCORING_MODEL.md、V3_VALIDATION_MODEL.md、V3_DEPLOYMENT_REPORT.md。其他既有未跟踪文档保留。没有 commit、push、部署、重启、钱包扩容或参数修改。

## 后续实施门槛

先使 Shadow 拥有独立 run/cutover、独立消费状态和正确累计收益，证明所有 V1 记录不变，再恢复 V3 工作。不能通过填旧 cutover、回放历史或将模拟收益标为实际 Alpha 绕过此门槛。详细待实施范围见另外三份文档。
