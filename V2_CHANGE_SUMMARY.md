# V2 Alpha Validation Baseline Summary

## 本次整理

- 将 Ubuntu 实际运行的 `66d7ed55` 记录为 `V1 60-Day Production Baseline`。
- 保留 V1 60 天验证数据和报告，不重算、不覆盖历史数据。
- 将已通过生产验证的 V1 feature branch 合并到本地 `main`。
- 创建唯一 V2 开发分支：`feat/v2-alpha-validation`。

## V2 当前变更

本次没有实施 V2 业务代码、数据库字段、评分规则、Signal Logic、Paper Trading 或 Shadow Trading。当前提交只是 V1 封存和 V2 开发基线准备。

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

## 30-Day Shadow Validation 条件

当前尚不具备直接开始条件。开始前必须先补齐可复算的 Equity Curve、Max Drawdown、Holding Time、净 PNL 归因和 API 失败样本标记，并通过 V2 测试。

## V1 历史数据影响

本次整理不影响 V1 历史数据、V1 生产数据库或 Ubuntu Production。新增的 V1 基线记录和本摘要均为文档，不会改变线上运行结果。
