# V3 Production Architecture

## Implemented Repair (2026-09-06)

The authorized repair is now implemented locally. Production deployment evidence is recorded separately in `V3_DEPLOYMENT_REPORT.md`. The STOP audit below is preserved as historical evidence, not the current implementation status.

- `v3_shadow.py`: atomic SQLite writer reservation, persisted immutable run/cutover/config, independent consumer ledger, long/short state machine, partial realization, atomic FLIP, market marks, funding and reconstruction checks.
- Additive tables: `v3_runs`, `v3_signal_processing`, `v3_shadow_positions`, `v3_shadow_trades`, `v3_shadow_actions`, `v3_shadow_equity_snapshots`, `v3_wallet_evaluations`, `v3_wallet_lifecycle`, `v3_data_quality`, `v3_notifications`, `v3_jobs`.
- `v3_intelligence.py`: as-of source snapshot deltas, independent wallet/signal/copyability scores and lifecycle transitions. Source scores do not overwrite `wallets.manual_score`, Discovery scores or Signal fields.
- `v3_runtime.py`: one five-minute worker with a cross-process SQLite lease and heartbeat; post-commit notification outbox; daily bounded public-source candidate import. Existing candidate evaluation remains on its eight-hour schedule. Existing Wallet rows are not deleted/expanded by lifecycle transitions; V3 demotion only restricts future V3 entries and never blocks exits.
- V3 enabled: legacy V2 Shadow jobs and manual mutation endpoints are disabled. Paper, Wallet Sync, Performance and Discovery schedules remain present. Legacy Signal delivery is replaced by the independent V3 high-value outbox; operational alerts remain.
- `v3_reporting.py` and `/api/v3/{dashboard,attribution,status}`: authenticated read-only, separate V3 equity, forward attribution, action cashflows, pro-rata OPEN/ADD cost-lot contribution, incomplete-data cohorts and rolling windows.
- `V3Dashboard.jsx`: existing shell, real data tables, sorting/filtering, equity canvas and quality warnings. No new authentication/member/payment system.

### Accounting contract

Gross = reference-midpoint price PNL. Fee is a positive cost. Slippage includes adverse bid/ask spread plus configured execution slippage, stored as a positive cost. Funding is signed: positive means paid; negative means received.

`action.net = gross - fee - slippage - funding`

Entry expenses are recognized immediately. Every Reduce (fixed 50% of the current Shadow quantity, version `v3.0`) books its own gross and exit costs; remaining average cost stays unchanged. Close adds only remaining-quantity results. FLIP closes and reopens inside one savepoint; an invalid new leg rolls back both legs. Public top-of-book depth and fill-fraction assumptions cap entry quantity.

`realized = SUM(all V3 actions.net)`; `unrealized = remaining reference-price PNL - estimated exit costs`; `total = realized + unrealized`; `equity = V3 starting balance + total`. Entry costs are not charged a second time in unrealized PNL. V1 Paper capital and historical PNL are not combined with V3 capital.

Funding uses public rates and the last observed held notional, not exact exchange settlement marks. It is explicitly Estimated and `funding_complete=false`; no precise funding or ROI claim is made. Missing quotes retain the last mark, mark the account degraded and prevent new allocations. They never close a position or replace its price with zero.

Reconstruction uses non-funding actions for terminal position state and every action for cumulative trade/account costs. Funding events are deduplicated by trade and settlement time. Processing and position changes commit together; a network request is never performed inside this accounting transaction.

### Operational contract

Set `V3_ENABLED=true` only with a newly generated `SHADOW_V3_CUTOVER_AT` at activation. The persisted high-water ID additionally excludes all pre-existing signals. Changing a persisted version's cutover or cost/model configuration fails closed. Only a successful real post-cutover action sets `started_at`; ignoring an orphan does not start the 30-day clock.

Telegram uses at-most-one automatic send attempt per durable outbox event. A timeout is `unknown`, not retried automatically, because Telegram does not provide an idempotency key. This prevents automatic duplicate attempts but cannot prove receipt from missing API responses. No delivery exception rolls back trades.

## Preserved STOP Audit

状态：设计草案，实施被历史数据保护检查阻塞，尚未部署。

检查时间：2026-09-06 UTC。当前正式版本：`07a618b64069e934d5fc2194077348f93b8e556c`。

## 已证实的实施阻塞

运行容器与本地 `v2_validation_service.py` 的 SHA-256 一致。线上 Settings 中 `paper_trading_cutover_at` 为空，Shadow Processor 因此在处理前直接返回。旧 Paper cutover JSON 为 2026-06-20，不能作为新的 V3 起点。

当前 Shadow 消费共享 Signal，并写入 `signal.status=simulated/ignored`。Paper Processor 只消费 `status=new`，因此两者会相互影响。临时数据库已复现 Shadow 将信号标为 simulated、但并没有 Paper Trade 的情况。

直接复用旧 Paper cutover 将使 948 条 V2 部署前的 simulated 信号重新进入 Shadow 候选输入。用户明确要求历史数据覆盖风险出现时停止，本次没有启用此配置，也没有修改线上逻辑。

## 最小兼容设计

沿用 FastAPI、SQLite、APScheduler、React、Docker Compose。以下均为待实现边界，不是已交付能力。

1. 先隔离 Shadow 消费状态。保留原始 Signal 和 Paper 状态；所有 Shadow eligibility、执行、忽略、失败均只写入独立的执行账本。
2. 为新验证周期增加持久化 run/cutover/high-water mark。使用数据库提交顺序和 UTC 时间共同确定边界；首次启用时明确排除存量信号，重启不可重新设置边界。
3. 保存版本化钱包评价、信号评价、市场状态和数据质量证据。评价可以更新当前视图，但历史决策引用当时的不可变版本。
4. 保留既有 Watchlist 行、Signals、Paper Trades 和 Performance Records。V3 生命周期用独立状态及事件记录，不能以删除旧钱包或改写旧评分的方式“淘汰”。新 Candidate 通过现有去重入口导入。
5. 每笔 Shadow Action 与仓位变化在同一事务提交，使用数据库唯一约束和原子锁处理并发；同一批逐条更新账户可用资金。
6. 新增只读 V3 查询接口，供现有 Dashboard 展示当前关注钱包、信号、独立 Shadow 收益和数据完整性。
7. Telegram 以已提交的评价及动作记录作为输入，单独维护通知去重；发送失败不改变交易状态。

## 拟新增的数据结构

| 结构 | 目的 | 历史保护 |
| --- | --- | --- |
| validation_runs | cutover、策略版本、费用版本、起止时间和冻结参数 | 不复用旧 Paper cutover |
| wallet_evaluations | as-of 评分、层级、copyability、样本覆盖和窗口 | 不覆盖 V1 钱包评分 |
| signal_evaluations | quality、regime、notional delta、eligibility 及原因 | 不改变原 Signal.status |
| market_observations | 市价、spread、funding、采集和行情时间 | 不用未来数据填补过去 |
| wallet_lifecycle_events | 晋升、降级及证据 | 不删除钱包记录 |
| execution/quality extensions | run_id、source、执行延迟、成本和完整性标记 | 只新增表或兼容字段 |

这些名称是接口设计建议，未运行迁移。已有 Shadow Action 表可复用，但必须先解决状态和 run 隔离。

## Scheduler 和数据源

保留现有主 Scheduler，新增任务必须有唯一 job id、max_instances=1 和数据库原子锁。禁止通过第二个 API/Scheduler 实例竞争同一数据库。把“任务返回成功”与“业务已消费数据”分别监控。

Discovery 使用现有 Hyperliquid seed adapter，之后再通过公共 /info 评价，设置有界扫描预算。扫描与 Watchlist Sync 共用请求配额、退避和失败窗口记录。单个来源或钱包失败必须可重试并显式降低数据质量，不能把空结果视作零仓位。

## 实施顺序和验收

1. 修复消费隔离、独立 cutover、真实 mark 和累计净收益；先在旧结构数据库副本证明 V1 行不变。
2. 完成数据覆盖、统一限速及 as-of regime，再实现评分、copyability 和 forward-only 评价。
3. 完成 V3 lifecycle、查询、Dashboard 和高价值通知。
4. 隔离集成测试、并发/重启/迁移测试和 full_verify；对旧表逐行摘要核对。
5. 备份线上 DB、配置和镜像版本后部署；验证真实业务周期，不能仅以 /health=ok 作为验收。

当前停在第 1 步之前的历史保护检查。没有新增服务、表、容器、分支或线上配置。
