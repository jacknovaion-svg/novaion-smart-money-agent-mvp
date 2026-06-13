# Discovery Seed Guide

## 1. 如何准备 Seed Wallet

Seed Wallet 是 Discovery Engine 的候选地址来源。第一版不要假设系统能匿名扫描全网 Hyperliquid 钱包，因为 Hyperliquid `/info` API 需要指定 user address。

建议来源：

- 你已经关注的公开 Hyperliquid 地址
- 朋友提供的公开地址
- 社区公开排行榜地址
- 后续接入 requester-pays 历史数据或第三方索引数据

每个地址必须符合：

```text
^0x[a-fA-F0-9]{40}$
```

## 2. 如何导入 TXT

准备 `data/discovery_wallets.txt`，一行一个地址：

```text
0x1111111111111111111111111111111111111111
0x2222222222222222222222222222222222222222
```

也可以在 Discovery Center 的导入框里直接批量粘贴。

## 3. 如何导入 CSV

CSV 建议包含 `address` 字段：

```csv
address,name,source
0x1111111111111111111111111111111111111111,Wallet A,manual
```

Discovery Center 支持上传 `.csv` 或粘贴 CSV 文本。

## 4. 如何理解 Discovery Score

Discovery Score 是系统估算分，不是盈利承诺。当前评分考虑：

- 30 天交易次数
- 7 天活跃度
- 估算胜率
- 估算盈亏比
- Estimated ROI
- Estimated PnL
- 当前持仓数量
- 风险分扣减

等级：

- `S`: 高分且风险较低
- `A`: 推荐重点观察
- `B`: 可观察
- `Watch`: 数据不足或表现一般
- `Reject`: 暂不建议加入

## 5. 为什么默认不自动加入 Watchlist

默认 `DISCOVERY_AUTO_ADD_ENABLED=false`。

原因：

- 候选来源可能包含噪音地址
- ROI/PnL 是估算值
- Hyperliquid 公开数据不等于完整风控画像
- 内测阶段优先人工审核，避免 watchlist 被低质量地址污染

只有用户点击 `Approve` 后，候选钱包才会进入 `wallets` 观察名单。

## 6. ROI/PnL 为系统估算值

所有 Discovery 里的 ROI / PnL 都应理解为 `Estimated`。

它们来自 Hyperliquid 只读公开数据和当前系统估算逻辑，不包含完整资金流、策略上下文、滑点、外部账户或链下信息。该工具用于研究和模拟验证，不保证未来收益。
