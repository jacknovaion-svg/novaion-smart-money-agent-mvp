# NOVAION-001 Smart Money Agent
# V2 Alpha Validation Plan

## 状态

- 阶段：规划与基线冻结
- 基线：V1 约60天验证报告
- 当前结论：CONDITIONAL PASS
- 本阶段不扩大 Candidates 或 Watchlist
- 本阶段不接真实交易、不接私钥、不修改评分规则
- 本文档只定义分析口径和最小实施边界，不执行模型调整

## V1 基线

- Active Watchlist：10
- Candidates：200
- Signals：3265
- Paper Trades：86
- Closed Trades：79
- Open Trades：7
- Win Rate：45.57%
- Realized PNL：-$3.06
- Unrealized PNL：+$38.32
- Profit Factor：0.95
- Hyperliquid 重试耗尽：331
- Wallet Sync 失败：152

V1 数据说明：Signals、Position Snapshots 和 Performance Records 在统计窗口每天都有记录，但策略收益不稳定，且 API 失败会降低部分信号和价格数据的完整性。

## V2 目标

### WHO：识别持续 Alpha 钱包

每个 active wallet 分层统计：

- Signal 数量
- 有效 Open 数量
- Paper Trade 数量
- Closed Trade 数量
- 净已实现 PNL
- Win Rate
- Profit Factor
- 平均赢家/平均亏家
- 最大回撤
- 平均持仓时长
- Signal 到 Paper Trade 转化率
- API 缺失和风控忽略比例

钱包至少达到最小样本门槛后才允许进入“有效 Alpha”判断。建议门槛为 20 笔已平仓交易；低于门槛只能标记为样本不足。

### WHAT：识别有预测价值的动作

按 Open、Add、Reduce、Close 分开统计：

- 1h、4h、24h Performance 的样本数、均值、中位数和正收益比例
- 发生时的仓位变化比例和美元变化
- 大仓位变化与小仓位变化的分层表现
- 信号延迟和可执行性
- 被 ignored、orphan、duplicate、资金不足拦截的比例

Add、Reduce、Close 不能被误当成独立新开仓；它们的预测表现和对已有 Paper Trade 的影响必须分别解释。

### WHY：解释 Profit Factor = 0.95

按以下顺序归因：

1. 交易选择：哪些信号进入了模拟盘，哪些被过滤；
2. 价格执行：源钱包价格、信号价格、模拟成交价格和退出价格的差异；
3. 成本：手续费和滑点占毛收益的比例；
4. 组合约束：资金不足、重复仓位、orphan 动作造成的选择偏差；
5. 数据质量：429、缺失快照、缺失价格和处理延迟；
6. 市场阶段：收益是否集中在少数周或少数币种。

## 当前钱包判断

根据 V1 现有样本，仅作分析优先级，不修改 Watchlist：

- 优先观察：`0x86dd...f065`，当前唯一明确的正净 PNL 钱包，但样本仍有限；
- 重点复核：`0x107b...7979`，转化率高但净 PNL 为负；
- 信号噪音候选：`0x8446...ba1b`，Signals 很多但转化率低且已评价样本为负；
- 需要成本/执行复核：`0xb40d...75d9`，胜率较高但净 PNL 和 Profit Factor 为负向；
- 其余钱包：样本不足，不作盈利或亏损判断。

## 最小数据与指标方案

### 优先复用现有字段

不新增数据库字段时，可直接使用：

- `paper_trades.opened_at` / `closed_at`：持仓时长；
- `paper_trades.pnl`、`raw_pnl`、`fees`、`slippage_adjustment`、`net_pnl`：成本和净收益；
- `paper_trades.mark_price`、`unrealized_pnl`：当前未实现收益；
- `signals.created_at`、`signal_type`、`source_trade_id`：信号归因；
- `signal_performance.return_1h/4h/24h`：动作后的市场表现；
- `system_logs`：过滤、429、失败和任务执行证据。

### 必须补齐的派生分析

- 基于 closed trade 序列的 realized equity curve；
- 基于统一时点快照的 open-position unrealized equity curve；
- 最大回撤金额和百分比；
- 平均/中位持仓时间；
- 按钱包、币种、动作和周的收益归因；
- API 失败窗口与缺失数据的重叠分析。

如果没有统一的逐时账户权益快照，Max Drawdown 只能标记为近似值，不能当作最终风险指标。

## P0 / P1 / P2

### P0：必须修复或确认

- 固定 realized / unrealized / net PNL 的唯一统计口径；
- 生成可审计的权益曲线和回撤；
- 统一 source signal、paper action、fill、exit 的关联；
- 明确排除历史信号、失败请求和缺失价格样本；
- 保持 Paper Trading 的资金门控、幂等和安全开关不变。

### P1：直接影响 Alpha 判断

- 钱包、币种、Signal Type 分层统计；
- 大小仓位变化分层；
- 信号延迟和可执行性统计；
- 429 影响窗口与漏数证据关联；
- 时间外验证和最小样本门槛。

### P2：以后再做

- 扩大 Candidate 池；
- 新增第三方数据源；
- Dashboard 扩展和 UI 美化；
- 自动交易、真实跟单、多账户和复杂 AI。

## Validation Baseline 规则

### 会改变 Baseline 的修改

- 改评分权重或筛选阈值；
- 改 Open/Add/Reduce/Close 的信号语义；
- 改 Paper Trade 的进入、退出、资金门控、手续费或滑点计算；
- 补录历史信号或按当前价格回放历史交易；
- 改变 Watchlist 或 Candidate 集合后重新比较结果。

### 不改变历史 Baseline 的修改

- 只读生成新的派生报表；
- 增加不写回历史数据的分析脚本；
- 增加数据质量标签和缺失样本说明；
- 增加测试，不改变生产数据库；
- 增加运行观测日志，但不改变信号和交易状态。

## V2 成功标准

V2 不以“某个钱包盈利”作为成功标准，而以可复现和可解释为标准：

- 每个钱包的收益归因可复核；
- 每类动作的样本数和结果可分开计算；
- PF 低于1的原因可以被分解；
- Max Drawdown 和 Holding Time 可复算；
- API 失败样本不会静默混入有效 Alpha 样本；
- 至少一个时间外窗口仍能得到相同方向的结论；
- 结论不依赖单个异常大盈利交易。

## 后续决策门槛

只有当 V2 达到上述数据质量标准后，才进入 Shadow Trading。Shadow Trading 仍不下真实订单。

真实小额人工交易必须另外通过账户权限、订单幂等、限额、紧急停止、成交对账和法律合规审查；V2 本身不授权真实交易。

本项目是 Smart Money 研究与模拟跟单工具，不保证盈利；模拟结果不代表未来收益。
