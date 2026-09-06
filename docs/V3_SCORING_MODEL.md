# V3 Scoring Model

## Implemented Model v3.0

The specifications below the preserved audit describe the original STOP. Current implementation is in `v3_intelligence.py`; scores and their inputs are stored independently with `as_of` and version. The model is a forward-validation hypothesis, not proven Alpha.

Inputs use fills whose market **and ingestion timestamps** are no later than the event, plus earlier position snapshots. Signal deltas compare quantities rather than position USD changes alone, so price/transfer-only changes cannot masquerade as an entry. A changed sign maps to FLIP. Missing before/after evidence fails entry eligibility; no synthetic before value is used.

Seven normalized score components sum to 0-100: net PNL / observed capital (weight 20), PF (15), net expectancy (10), positive-day consistency (20), profit concentration penalty (10), active days (10), leverage-risk penalty (15). Weights, tiers, minima, source-gap/age, execution-age, spread and notification thresholds are configuration inputs frozen in `v3_runs.config_json`.

Minimum coverage: 30 observed closing fills, seven active days and $100 account equity by default. Closing fills are explicitly **not round-trip trades**. Missing capital-flow data means ROI and source-wallet max drawdown are null; unknown funding is disclosed. No-loss PF is null, not infinity. Insufficient coverage caps the grade below B and blocks V3 entries. Estimated source metrics cannot reach S.

Copyability is separate: activity frequency, observed reconstructed holding periods and source leverage. GOOD TO COPY additionally requires adequate observed holding samples. Signal execution separately checks current public book spread, depth, quote age and delayed execution. These remain assumptions, not proof that a real order would fill.

Signal quality combines wallet score (45%), copyability (25%), risk (20%), and recent same-wallet/symbol event frequency (10%). A low quality score, tiny quantity/notional movement, snapshot gap, missing data, insufficient wallet samples or demoted lifecycle prevents OPEN/ADD. Valid REDUCE/CLOSE remain available to reduce existing exposure.

BTC completed hourly candles supply the contemporaneous trend (Bull/Bear/Sideways) and daily volatility context. Unavailable context is UNKNOWN, never retrospectively filled using future candles. Source gross/net, fees, active days, concentration, position size, equity, capital CV, loss tail, holding coverage, diversification, directional bias and recent decay are queryable. Source Sharpe-like is an explicitly nonannualized daily PNL statistic, not investment-return Sharpe.

Lifecycle changes are independent audit events: Watchlist -> Approved after sufficient positive forward closed samples; Elite requires twice the forward sample floor and stronger PF; deterioration causes Probation -> Demoted after the dwell interval. No legacy wallet or history is deleted. Candidate discovery inserts fresh public Hyperliquid trader addresses through the existing deduplicating import service; it never auto-approves legacy wallets.

## Preserved STOP Specification

状态：未实施的模型规格，不是生产评分模型。V3 因历史数据保护阻塞而停止。

## 评价约束

所有评分必须记录 model_version、as_of、window、数据截止时间、样本数量及覆盖度。不得使用随后发生的成交或收益来改变信号发生时的评价。7d/30d/90d/Lifetime 仅在真实覆盖该窗口时输出，缺失不是 0。

既有历史评分保留。V3 评价写入独立版本，不将新模型覆盖到 V1/V2 原始记录。

## 指标分组

| 组 | 必需输入 | 不可靠时的处理 |
| --- | --- | --- |
| 净收益 | realized PNL、fee、funding、gross/net PF、expectancy、average win/loss | funding 或费用未覆盖时标记 Estimated |
| 资本和回撤 | equity、外部资金流、ROI、position size、capital stability、equity drawdown | 缺少资金流时不输出确切 ROI；缺少曲线时不输出确切回撤 |
| 稳定性 | active days、分期净收益、concentration、loss tail、recent decay | 少量巨额盈利不得替代持续样本 |
| 行为 | holding time、frequency、symbol diversification、directional bias | 部分平仓和交易分段方法必须明确版本 |
| 风险调整 | 分期收益序列、波动、Sharpe-like | 非等间隔或样本不足时 unavailable；不得随意年化 |

先做最低样本和数据质量门控，再计算 0-100 分。PF 无亏损样本时不是无限高分。机器人、高频和小本金只能依证据分类，不能仅凭地址或交易次数猜测。

## Tier 和 Copyability

S/A/B/C/Reject 的阈值、最低样本、权重和晋升/降级滞回必须配置化并冻结版本。当前未用 V1 全量历史寻找收益最高的阈值，也没有宣布任何参数已经有效。

Copyability 与盈利评分分开：输入包括持仓时间、信号延迟、成交频率、仓位周转、预计 spread/slippage、市场可成交量、执行后价格偏离及反复加减仓行为。缺少流动性或执行覆盖时不能评为 GOOD TO COPY，最多为 OBSERVE ONLY。

## 市场状态

Bull/Bear/Sideways 是趋势维度，High/Low Volatility 是波动维度，分别记录。使用当时可见的价格序列判定，不能把未来行情标签回填为交易前信息。每个 regime 的 PF、净收益、胜率和回撤必须同时显示样本数和覆盖度。

## 晋升和淘汰

Candidate/Watchlist/Approved/Elite/Probation/Demoted/Rejected 均需事件证据、as-of 时间和 minimum dwell/cooldown。晋升需要前向样本，不能仅凭发现时训练窗口净收益。降级不删除钱包、历史信号或仓位，也不能阻断已有仓位的 Reduce/Close。

## 未实现项

综合评分、copyability、regime 分组及自动晋升均尚未实现；生产仍使用既有 V2 逻辑。不会把现有 Win Rate/PF 评分标记为 V3 已完成。
