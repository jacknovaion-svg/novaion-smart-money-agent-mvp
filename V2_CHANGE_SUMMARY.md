# V2 Alpha Validation Baseline Summary

## 本次整理与实施

- 将 Ubuntu 实际运行的 `66d7ed55` 记录为 `V1 60-Day Production Baseline`。
- 保留 V1 60 天验证数据和报告，不重算、不覆盖历史数据。
- 将已通过生产验证的 V1 feature branch 合并到本地 `main`。
- 创建唯一 V2 开发分支：`feat/v2-alpha-validation`。

## V2 当前变更

本次在 `feat/v2-alpha-validation` 实施了最小 V2 分析基础：

- 新增 `equity_snapshots`，保留模拟账户 realized、unrealized、net PNL 和 equity 时间序列；
- 新增完整 Equity Curve 和 Max Drawdown 金额/百分比计算；无曲线时返回不可用，而不是估算；
- 新增 Holding Time 平均值、中位数和样本数计算；
- 新增 Wallet → Signal → Paper Trade → Net PNL 的 Wallet、Symbol、Signal Type 归因接口；
- 新增可配置的 `fees`、`slippage`、Gross PNL、Net PNL、Profit Factor 和 Expectancy 计算；
- 新增 `data_quality_events`，支持 429、同步失败、缺少快照/价格、性能更新失败等污染标记；
- 新增 `shadow_trades`，支持只模拟的开仓、平仓、成本计算和幂等创建；
- 新增 `paper_trade_actions`，为后续新 Paper Trading 动作保存 Open/Add/Reduce/Close 的 Signal Type 与净 PNL 归因；
- 新增 V2 专用 API：权益快照、权益曲线、归因、Shadow 摘要及 Shadow 开平仓；
- 新增默认关闭的 `V2_ALPHA_VALIDATION_ENABLED` 和 `SHADOW_TRADING_ENABLED`，V2 快照调度只有显式开启后才运行；
- 未修改 Discovery、Wallet Ranking、评分规则、现有 Paper Trading 信号定义或真实交易接口。

## V2 允许范围

- 数据可信度：Equity Curve、Max Drawdown、Holding Time、数据完整性和失败样本标记
- Alpha Attribution：Wallet → Signal → Trade → PNL，以及钱包、币种和动作分层分析
- 真实交易成本：Fee、Slippage、Net PNL、Profit Factor、Expectancy
- Shadow Trading：只记录假设跟单结果，不真实下单、不接私钥

## 基线保护

- 不扩大 Candidates 或 Watchlist。
- 不接 DeBank、Arkham、Nansen 或其他第三方数据源。
- 不修改历史数据库，不补录历史 Paper Trades。
- 不启用真实交易，不调用真实交易接口。
- 不自动部署 Ubuntu Production。

## 测试结果

- V2 Alpha Validation：`8/8` 通过
- 覆盖：模型建表/迁移兼容、权益曲线、回撤、持仓时长、质量标记、Shadow 开平仓、幂等和 Alpha 归因
- Paper Trading Processor：`31/31` 通过
- Paper Boss Mode：`42/42` 通过
- Telegram Noise Reduction：`27/27` 通过
- `full_verify`：通过
- 未发现失败测试

## V1 历史数据安全

没有对 V1 数据库执行迁移、回放、重算或覆盖。新增表只会在 V2 配置显式启用并启动对应应用时创建；本次未部署 Ubuntu Production。

## 30-Day Shadow Validation 条件

当前已具备开始前的本地实现和测试条件，但不建议立即宣称 Shadow Validation 已开始。正式开始前仍需在独立测试环境：

- 显式开启两个 V2 开关；
- 验证真实市场信号到 Shadow Trade 的处理延迟和退出关联；
- 验证 API 失败样本与信号缺失的关联完整性；
- 确认至少一个完整观察窗口和数据备份策略。

因此当前状态为：**具备启动 30-Day Shadow Validation 的技术准备条件，尚未开始运行验证。**

## V1 历史数据影响

本次整理不影响 V1 历史数据、V1 生产数据库或 Ubuntu Production。V2 默认关闭，不会改变线上运行结果。
