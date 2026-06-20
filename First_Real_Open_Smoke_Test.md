# First Real Open Smoke Test

- Report Time: 2026-06-20
- Mode: Research-only / Paper Trading
- Real Trading: Disabled
- Private Keys: Not Used
- Branch: feat/paper-trading-auto-processor

## Cutover

- paper_trading_cutover_at: 2026-06-20T05:54:35.942738+00:00

## Signal

- signal_id: 317
- created_at: 2026-06-20T17:02:30.941780+00:00
- later_than_cutover: true
- wallet_id: 12
- wallet_address: 0x86dd7aa83d1d1ef0a957137c6d4f5b8ada90f065
- symbol: ZRO
- signal_type: open
- side: long
- risk_score: 46
- suggested_size_usd: 20.0
- source_entry_price: 0.905
- current_price: 0.90419
- final_signal_status: simulated

## Processor

- processed_at: 2026-06-20T17:17:29.006722+00:00
- scheduler_period_minutes: 15
- latency_seconds: 898.065
- latency_result: pass
- processor_summary: processed=1, simulated=1, ignored=0, failed=0, paper_opened=1

## Paper Trade

- paper_trade_id: 1
- signal_id: 317
- wallet_id: 12
- symbol: ZRO
- position_side: long
- entry_price: 0.90509419
- expected_slipped_entry_price: 0.90509419
- size_usd: 20.0
- leverage: 3.0
- status: open
- opened_at: 2026-06-20T17:17:29.002576+00:00

## Mark Price And PnL

- first_verified_mark_price: 0.90125
- unrealized_pnl: -0.374582
- unrealized_pnl_pct: -0.624303
- updated_at: 2026-06-20T18:17:29.259548+00:00
- current_price_nonzero: true
- latest_mark_update_result: open_trades=1, updated=1, price_missing=0, failed=0
- price_failure_overwrite_check: no real price failure observed during this smoke test; no artificial failure was injected into the real DB.

## System Logs

- paper_opened_log_count_for_signal_317: 1
- paper_opened_log_created_at: 2026-06-20T17:17:29.006722+00:00
- paper_opened_payload: {"signal_id":317,"wallet_id":12,"symbol":"ZRO","action":"paper_opened","paper_trade_id":1}
- error_logs_since_signal: 0
- duplicate_processing_errors: 0

## Duplicate Check

- manual_processor_rerun_result: processed=0, simulated=0, ignored=0, failed=0, paper_opened=0
- paper_trades_for_signal_317_before: 1
- paper_trades_for_signal_317_after: 1
- paper_opened_logs_for_signal_317_before: 1
- paper_opened_logs_for_signal_317_after: 1
- duplicate_open_result: pass

## Conclusion

First real Cutover Open smoke test passed.

The ZRO Long Open signal was generated after cutover, processed by the Paper Trading Processor within one scheduler cycle, created exactly one open paper trade, recorded paper_opened in system_logs, updated mark_price and unrealized PnL on a later paper_trade_update cycle, and did not duplicate when the processor was run again.
