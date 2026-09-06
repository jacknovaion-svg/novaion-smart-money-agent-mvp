# V3 Validation Model

## Implemented Forward Validation

V3 is opt-in and strictly uses `created_at > SHADOW_V3_CUTOVER_AT` AND IDs beyond the activation high-water mark. Historical statuses are never a consumption filter. The first committed, real Shadow action establishes the 30-day start; synthetic test fixtures cannot establish a production start.

Attribution includes wallet, symbol, side, tier, trend, volatility, signal-score band, copyability band, holding-duration band, action cashflows and pro-rata OPEN/ADD entry-lot contribution. Closed-trade PF/expectancy exclude open-trade floating PNL. Account realized PNL includes every partial action and already-paid entry cost. All/clean/contaminated cohorts and 7d/30d/90d/lifetime forward windows are separate; short coverage is not claimed to be a complete 90-day sample.

Drawdown uses only the independent V3 equity sequence. Any degraded snapshot or gap over 15 minutes makes full-window drawdown unavailable. Even a complete sampled curve cannot prove an intrainterval maximum. No historical curve is reconstructed from current account value.

At least 30 closed forward trades are needed for even a preliminary grade. An approximate 95% normal-mean interval is explicitly an approximation and is not reliable proof under correlated/tail-heavy samples. Positive expectancy interval and net PF > 1 yield at most CONDITIONAL PASS; otherwise FAIL, or INSUFFICIENT DATA below the sample floor. Funding settlement prices remain estimated. Strategy profitability is never inferred from container uptime or successful unit tests.

`scripts/verify_v3.py` uses disposable databases only. It covers cutover, independent Paper statuses, OPEN/ADD/REDUCE/CLOSE/FLIP, cumulative costs, signed funding, action-ledger reconciliation, rollback, concurrency, restart, funds, quote failure, as-of scoring, drawdown gaps, authenticated API, Scheduler isolation and Telegram failure/duplicate protection. Existing regression suites and `full_verify.py` remain separate.

## Preserved STOP Specification

状态：验收规格和阻塞复现记录；尚未启动 V3 验证。

## 已执行验证

2026-09-06 在独立 TemporaryDirectory 和 SQLite 中调用当前 commit 的真实服务函数，关闭 Scheduler、Telegram 及实盘开关。未向 Mac 正式库或 Ubuntu 插入测试数据。

| 复现场景 | 结果 |
| --- | --- |
| V2/Shadow 开关开启，cutover 为空，存在新 Open | processed=0、failed=0、Shadow Trade=0，任务可被记录为 ok |
| 测试中填入旧 Paper cutover，包含一条 2026-06-22 Open | 历史 Open 被回放为 Shadow Trade |
| 新 Open 被 Shadow 消费 | 原 Signal.status 被改为 simulated，但 Paper Trades=0 |
| Open 后 Reduce，仓位仍 open | 累计净已实现收益 1.966024，equity snapshot.realized_pnl=0 |

上述是缺陷复现成功，不是 V3 验收通过。临时数据自动清理，业务代码未修改。

现有回归也在临时工作目录执行：

- verify_shadow_processor.py：8/8。
- verify_v2_alpha_validation.py：8/8。
- full_verify.py：ok=true。

full_verify 通过 importlib 加载原脚本，将运行时 ROOT 指向临时目录后调用 main，防止覆盖仓库内已有测试数据库。测试脚本本身未改动。

既有 Shadow 测试主动设置 cutover，且期待改写 Signal.status，因此其通过不能证明线上配置有效或 Paper/Shadow 互不影响。

## 必须新增的验收

1. production 等效空配置不能静默显示 Shadow 正常；需要明确 blocked_reason。
2. 独立 run/cutover 持久化，重复启动不变；cutover 前的 Signal、Paper 和 Performance 行摘要始终不变。
3. Shadow 对原 Signal/Paper 不写入，两个 Processor 以任意顺序运行得到相同各自结果。
4. 多进程竞争、新任务与重试并发，唯一动作约束与原子事务阻止重复执行。
5. 逐批资金重新计算；不足资金不加风险，Reduce/Close 能继续。
6. Open/Add/Reduce/Close/Flip 严格按 wallet/symbol/side 匹配；orphan、ambiguous、failed 可审计。
7. gross - fee - slippage - funding 的符号约定一致；多次 Reduce 后 Close 不覆盖累计值；开仓未结算成本与退出预计成本不得双计。
8. open 仓位的已实现收益进入账户余额，未实现收益仅进入权益；不同 run 和 paper/shadow 曲线不能混算回撤。
9. mark 来自带采样时间的市场行情；缺价保留有效价格并标记 stale，不能以旧 Signal.current_price 假装新市场价格。
10. fee、slippage、spread、delay、partial fill、minimum notional 均版本化；未知 funding 不得假定已完整计入。
11. 429、sync gap、missing snapshot、out-of-order 和失败覆盖能够被归因样本引用。
12. API、Dashboard、Telegram 用同一 as-of 评价，不使用未来信息；通知的 outbox/idempotency 不影响模拟事务。

## Alpha 验证

将发现/筛选窗口与前向验证窗口分开。训练期选钱包不得计为验证收益；记录全部 Candidate 和淘汰事件以暴露幸存者偏差。滚动统计只使用窗口内、决策时可见、质量合格的样本。

每个 wallet/symbol/side/type/regime 分组给出样本数、净 PF、expectancy、收益分布、置信区间及覆盖度。低样本组显示 insufficient_data。用时间块/钱包块重采样检查相关性，并报告费用和执行延迟敏感性。正收益不等于 Alpha 已证实。

## 数据保护和部署门槛

只允许兼容性新增结构。先用数据库副本重复运行迁移，核对所有既有表结构和行内容。禁止历史重算、删表、重置信号或用旧价格补造交易。

生产基线必须来自真实信号首次合格执行的事务时间，而非容器启动时间。至少一个业务周期要有消费数、跳过原因、真实 mark、权益、归因和任务状态对应证据；没有自然信号可以等待，但不能把空 cutover 返回当作等待。

当前触发“历史数据覆盖风险 STOP”，所以没有运行 V3 migration、commit、push 或生产升级。
