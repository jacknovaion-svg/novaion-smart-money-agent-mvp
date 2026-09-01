# NOVAION-001 Smart Money Agent
# 60-Day Validation Final Audit

## 1. 审计范围

- 数据来源：Ubuntu 正式实例现有生产数据库，只读查询
- 报告生成时间：2026-09-01 18:47:27 UTC
- 统计窗口：最近 60 天，约 2026-07-03 至 2026-09-01 UTC
- Candidates：200，未新增，仅持续评估
- Active Watchlist：10
- 本报告不修改代码、数据库、评分模型、Candidates 或 Watchlist

金额均为模拟盘数据库中的美元值。没有把未平仓浮动盈亏当作已实现收益，也没有虚构 ROI。

## 2. 总体结论

**CONDITIONAL PASS**

系统业务链路在 60 天内持续产生真实数据：Signals、Position Snapshots 和 Performance Records 在每个统计日均有记录，容器没有异常重启。但策略收益尚未达到“稳定有效”的证据标准：79 笔已平仓 Paper Trades 的已实现 PnL 为负，Profit Factor 为 0.95，且存在 331 次 Hyperliquid 重试耗尽和 152 次 Wallet Sync 失败。

这意味着：

- 可以完成 V1 的运行数据验证和初步策略评估；
- 不能据此宣称策略盈利或评分模型有效；
- 需要把请求失败、信号过滤和模拟成交语义作为数据质量限制写入最终结论。

## 3. Paper Trading 表现

| 指标 | 结果 |
|---|---:|
| Closed Trades | 79 |
| Open Trades | 7 |
| Winning Closed Trades | 36 |
| Losing/flat Closed Trades | 43 |
| Win Rate | 45.57% |
| Total Realized PNL | -$3.06 |
| Current Unrealized PNL | +$38.32 |
| Average Closed PNL | -$0.04 |
| Median Closed PNL | -$0.08 |
| Average Winner | +$1.70 |
| Average Loser | -$1.50 |
| Profit Factor | 0.95 |
| Best Closed Trade | +$19.05 |
| Worst Closed Trade | -$12.64 |
| Average Holding Time | 不可可靠计算：当前审计字段未提供完整可比的持仓时长样本 |
| Max Drawdown | 不可由当前快照可靠重建：缺少统一的逐时账户权益曲线 |
| Return / ROI | 不作为正式结论：虽存在 $100 模拟本金配置，但当前累计收益口径和未平仓估值不适合作为完整 ROI 断言 |

已实现收益仅按 closed trade 的 `pnl` 统计。7 笔 open trade 的浮动 PnL 单独列为 unrealized PNL。

## 4. 按 Watchlist Wallet 分析

以下为当前 10 个 active wallet 的全库统计；仅有 4 个钱包产生了 Paper Trades。未发生 Paper Trade 的钱包不代表策略一定无效，只代表当前模拟执行链路没有形成可评价样本。

| Wallet | Signals | Paper Trades | Closed | Win Rate | Realized PNL | Avg PNL | PF | Conversion |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `0x86dd...f065` | 534 | 30 | 27 | 33.33% | +$13.18 | +$0.49 | 1.43 | 5.62% |
| `0x107b...7979` | 188 | 35 | 35 | 65.71% | -$9.07 | -$0.26 | 0.39 | 18.62% |
| `0x8446...ba1b` | 1417 | 13 | 11 | 0.00% | -$3.86 | -$0.35 | 0.00 | 0.92% |
| `0xb40d...75d9` | 737 | 8 | 6 | 66.67% | -$3.31 | -$0.55 | 0.77 | 1.09% |
| `0x0980...d1c2` | 122 | 0 | 0 | N/A | N/A | N/A | N/A | 0.00% |
| `0x0000...bbbb` | 29 | 0 | 0 | N/A | N/A | N/A | N/A | 0.00% |
| `0x52a1...142d` | 179 | 0 | 0 | N/A | N/A | N/A | N/A | 0.00% |
| `0xbb08...0964` | 0 | 0 | 0 | N/A | N/A | N/A | N/A | 0.00% |
| `0xb510...1ed6` | 59 | 0 | 0 | N/A | N/A | N/A | N/A | 0.00% |
| `0xbe18...ab88` | 0 | 0 | 0 | N/A | N/A | N/A | N/A | 0.00% |

### 钱包结论

- 当前唯一明确的利润贡献钱包：`0x86dd...f065`，但只有 27 笔已平仓交易，仍需继续观察。
- `0x107b...7979` 信号转化率较高，但累计亏损，说明信号数量或胜率不能单独代表价值。
- `0x8446...ba1b` 信号最多，但 Paper Trade 转化率低且已评价样本为负，是典型的“信号很多但当前没有价值”候选。
- `0xb40d...75d9` 胜率较高但累计亏损，说明盈亏比和样本质量需要同时考虑。
- 其余 6 个钱包没有足够 Paper Trade 样本，不能直接判定保留或删除。

仅从验证结果建议：继续重点观察 `0x86dd...f065`；将 `0x107b...7979`、`0x8446...ba1b`、`0xb40d...75d9` 标记为需要降权/复核的候选。此处为报告建议，不执行任何 Watchlist 变更。

## 5. 按 Signal Type 分析

| Signal Type | Signals | 1h 平均表现 | 4h 平均表现 | 24h 平均表现 | 关联 Paper Trades | 说明 |
|---|---:|---:|---:|---:|---:|---|
| Open | 465 | -0.031% | -0.086% | -0.298% | 86 | Paper Trade 的 `signal_id` 主要对应开仓入口 |
| Add | 1171 | +0.139% | +0.320% | +0.767% | 0 | 主要由后续表现记录评价，未形成独立 Paper Trade 行 |
| Reduce | 1213 | +0.058% | +0.097% | +0.952% | 0 | 不能直接等同于开仓收益 |
| Close | 416 | +0.048% | +0.047% | +0.570% | 0 | 主要作为退出动作，不能单独计算开仓收益 |

当前 schema 没有把“后续方向正确率”作为独立字段保存；可用 Performance 的正负收益近似，但不应冒充标准命中率。由于 Paper Trade 行主要以 Open signal 作为开仓入口，不能把 Add/Reduce/Close 的 Paper Trade 转化率解释为它们没有作用。

## 6. Signal 到 Paper Trade 漏斗

当前全库漏斗：

```text
3265 Signals
├─ 947 simulated signal statuses
├─ 2013 ignored signal statuses
└─ 305 new statuses（主要为 cutover 前历史 new 信号）
        ↓
86 Paper Trade rows
        ↓
79 Closed Trades
        ↓
36 Winning Closed Trades
```

这里的 `simulated` 是 Signal 状态，不等于新增一行 Paper Trade；Add、Reduce、Close 可能更新已有仓位、被 orphan/duplicate/risk gate 忽略，或不创建独立交易行。

主要原因包括：

- 正常业务限制：同仓位重复 Open、Add/Reduce 没有对应 open trade、Close 无对应仓位或方向不明确；
- 风控限制：高风险、资金不足、零仓位等；
- 数据完整性限制：缺少价格或方向信息；
- API 失败：Hyperliquid 请求重试耗尽，可能导致同步或价格更新缺失；
- 当前 cutover 规则：历史 `status=new` 信号不应自动补录 Paper Trade。

因此不能用 `3265 → 86` 简单判定为程序故障，也不能把所有 ignored 都视为正常过滤；它们需要在后续报告中按原因分桶。

## 7. 429 与数据完整性影响

过去约60天记录到：

- Hyperliquid 429/相关请求失败记录：`2102` 条；
- `Info request exhausted retries`：`331` 条；
- Wallet Sync failed：`152` 次；
- Paper mark price refresh failed：`4` 次；
- Signal quality job failed：`4` 次。

影响判断：

- 不是全程中断：Signals、Position Snapshots、Performance Records 在统计窗口的每天都有记录；
- 不是零影响：部分钱包周期可能缺少 fills、positions、orders 或 mark price，造成信号、性能记录和 Paper Trade 估值不完整；
- 当前证据不足以逐条证明某个 429 是否漏掉了特定 Signal，因为现有日志没有完整的“请求失败 → 钱包动作 → signal 缺失”关联链；
- 因此 429 足以降低结论置信度，但不足以证明全部策略结果失真。

## 8. 时间维度

| 周次 | Signals | Paper Trades | Closed PNL | API Errors |
|---|---:|---:|---:|---:|
| 2026-W26 | 131 | 6 | +$6.70 | 40 |
| 2026-W27 | 342 | 11 | +$2.46 | 58 |
| 2026-W28 | 307 | 1 | -$0.27 | 163 |
| 2026-W29 | 197 | 1 | $0.00 | 50 |
| 2026-W30 | 339 | 1 | +$5.86 | 125 |
| 2026-W31 | 211 | 0 | -$2.26 | 35 |
| 2026-W32 | 161 | 0 | +$19.05 | 13 |
| 2026-W33 | 299 | 1 | -$5.77 | 6 |
| 2026-W34 | 264 | 3 | -$0.29 | 5 |
| 2026-W35 | 97 | 3 | -$10.49 | 1 |

周度结果不稳定，利润明显集中在少数周，尤其 W32 的单笔大盈利显著影响总结果；W35 出现较明显亏损。当前不能认为策略收益稳定。

## 9. 运行连续性

- Signals 覆盖：`61` 个统计日；
- Position Snapshots 覆盖：`61` 个统计日；
- Performance Records 覆盖：`61` 个统计日；
- Wallet Sync 成功记录：`171,602`；失败：`152`；
- Discovery 完成：`180` 次，符合约每天3次的运行形态；
- Paper Trade Update 完成：约 `5,760` 次；
- 发现过 task lock skip：`76` 次；当前 task locks 状态为 `ok`；
- 未发现连续多日业务数据空窗；
- 容器重启次数：`0`。

## 10. 最终回答

### A. V1 是否已经完成 Validation

**部分完成。** V1 的运行稳定性和数据采集验证已完成；策略有效性验证未完成。负的已实现 PNL、Profit Factor 小于1、周度收益不稳定和 API 失败记录，使得“模型有效”结论不成立。

### B. 是否值得进入 V2

**值得，但应以数据质量和可解释性为目标。** V2 不应先扩大钱包数量，而应先提高当前样本的可追溯性和可评价性。

### C. 哪些 Wallet 应保留

从已有 Paper Trading 证据看，优先保留观察 `0x86dd...f065`。其余钱包没有足够证据支持“高质量”，不建议仅按手动评分继续提升优先级。

### D. 哪些 Wallet 应降级/删除

报告层面的降级候选：`0x107b...7979`、`0x8446...ba1b`、`0xb40d...75d9`。其余无样本钱包暂不建议直接删除，应标为“样本不足”。本报告没有执行任何操作。

### E. 当前评分模型最明显的问题

评分和实际 Paper Trading 结果存在脱节：高 Signals 数量、高手动分数或较高 Win Rate，并没有稳定转化为正 PNL。当前模型可能低估了交易成本、信号可执行性、仓位规模、资金约束和信号过滤后的有效样本量。

### F. V2 最值得修改的前三项

1. 建立完整的 signal → source snapshot → paper action → PNL 追踪，区分信号表现和模拟成交表现；
2. 将数据质量、API 缺失、资金门控、orphan/duplicate 等过滤原因纳入可审计的样本分层；
3. 用统一账户权益曲线计算真实 max drawdown、持仓时间、净收益和按周稳定性，再重新评估评分权重。

### G. 是否应该扩大200 Candidate 池

**不建议现在扩大。** 当前 200 个 Candidate 已足够暴露模型与执行链路问题；在数据质量和收益口径尚未进一步稳定前扩大池子只会增加 API 成本和噪声。

## 11. 限制与声明

- 本报告只分析现有数据库，不修改任何业务逻辑或历史数据。
- 未把未平仓 PNL 计入已实现收益。
- 由于当前记录结构限制，Average Holding Time、严格 Max Drawdown、按 Signal Type 的独立 Paper Trade 转化率和完整 429 漏数归因不能可靠推导，已明确标记，不做虚构。
- 本项目是 Smart Money 研究与模拟跟单工具，不保证盈利；模拟结果不代表未来收益。
