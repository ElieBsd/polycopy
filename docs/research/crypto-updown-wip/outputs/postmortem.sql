-- Q0a inventaire tables
SELECT 'detected_trades' AS tbl, COUNT(*) AS n, MIN(timestamp) AS first_at, MAX(timestamp) AS last_at FROM detected_trades
UNION ALL SELECT 'strategy_decisions', COUNT(*), MIN(decided_at), MAX(decided_at) FROM strategy_decisions
UNION ALL SELECT 'my_orders', COUNT(*), MIN(sent_at), MAX(sent_at) FROM my_orders
UNION ALL SELECT 'my_positions', COUNT(*), MIN(opened_at), MAX(COALESCE(closed_at, opened_at)) FROM my_positions
UNION ALL SELECT 'pnl_snapshots', COUNT(*), MIN(timestamp), MAX(timestamp) FROM pnl_snapshots
UNION ALL SELECT 'trade_latency_samples', COUNT(*), MIN(timestamp), MAX(timestamp) FROM trade_latency_samples
UNION ALL SELECT 'target_traders', COUNT(*), MIN(added_at), MAX(added_at) FROM target_traders
UNION ALL SELECT 'trader_scores', COUNT(*), MIN(cycle_at), MAX(cycle_at) FROM trader_scores
UNION ALL SELECT 'trader_events', COUNT(*), MIN(at), MAX(at) FROM trader_events;
-- Q0b
SELECT version_num FROM alembic_version;
-- Q0c
SELECT execution_mode, is_dry_run, COUNT(*) AS n FROM pnl_snapshots GROUP BY 1, 2;
-- Q0d
SELECT simulated, realistic_fill, side, status, COUNT(*) AS n FROM my_orders GROUP BY 1, 2, 3, 4 ORDER BY n DESC;
-- Q1 PnL total par etat
SELECT
  CASE WHEN closed_at IS NULL THEN 'open'
       WHEN size <= 1e-9   THEN 'closed_by_copied_sell'
       ELSE 'closed_by_resolution' END                       AS state,
  COUNT(*)                                                   AS n,
  ROUND(SUM(COALESCE(realized_pnl, 0)), 2)                   AS realized_usd,
  ROUND(AVG(realized_pnl), 4)                                AS avg_pnl_usd,
  SUM(realized_pnl > 0)                                      AS wins,
  SUM(realized_pnl < 0)                                      AS losses,
  SUM(realized_pnl = 0)                                      AS breakeven,
  ROUND(100.0 * SUM(realized_pnl > 0) / NULLIF(SUM(realized_pnl <> 0), 0), 1) AS win_rate_pct,
  ROUND(SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl END)
        / NULLIF(-SUM(CASE WHEN realized_pnl < 0 THEN realized_pnl END), 0), 2) AS profit_factor
FROM my_positions
WHERE simulated = 1
GROUP BY 1
UNION ALL
SELECT 'TOTAL_closed', COUNT(*), ROUND(SUM(realized_pnl), 2), ROUND(AVG(realized_pnl), 4),
       SUM(realized_pnl > 0), SUM(realized_pnl < 0), SUM(realized_pnl = 0),
       ROUND(100.0 * SUM(realized_pnl > 0) / NULLIF(SUM(realized_pnl <> 0), 0), 1),
       ROUND(SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl END)
             / NULLIF(-SUM(CASE WHEN realized_pnl < 0 THEN realized_pnl END), 0), 2)
FROM my_positions WHERE simulated = 1 AND closed_at IS NOT NULL;
-- Q2 par wallet source
SELECT
  COALESCE(p.source_wallet_address, '(null)')                 AS source_wallet,
  t.status, ROUND(t.score, 3) AS score, t.is_probation,
  COUNT(*)                                                    AS n_pos,
  SUM(p.closed_at IS NOT NULL)                                AS n_closed,
  SUM(p.realized_pnl > 0)                                     AS wins,
  SUM(p.realized_pnl < 0)                                     AS losses,
  ROUND(100.0 * SUM(p.realized_pnl > 0) / NULLIF(SUM(p.realized_pnl <> 0), 0), 1) AS win_rate_pct,
  ROUND(SUM(COALESCE(p.realized_pnl, 0)), 2)                  AS realized_usd,
  ROUND(SUM(CASE WHEN p.closed_at IS NULL THEN p.size * p.avg_price ELSE 0 END), 2) AS open_cost_usd
FROM my_positions p
LEFT JOIN target_traders t ON t.wallet_address = p.source_wallet_address
WHERE p.simulated = 1
GROUP BY p.source_wallet_address
ORDER BY realized_usd ASC;
-- Q3 holding
WITH h AS (
  SELECT (julianday(closed_at) - julianday(opened_at)) * 86400.0 AS hold_s,
         CASE WHEN size <= 1e-9 THEN 'sell' ELSE 'resolution' END AS close_type,
         realized_pnl
  FROM my_positions
  WHERE simulated = 1 AND closed_at IS NOT NULL
)
SELECT close_type,
  CASE WHEN hold_s < 300 THEN '1_<5min' WHEN hold_s < 3600 THEN '2_5-60min'
       WHEN hold_s < 6*3600 THEN '3_1-6h' WHEN hold_s < 86400 THEN '4_6-24h'
       WHEN hold_s < 7*86400 THEN '5_1-7j' ELSE '6_>7j' END AS bucket,
  COUNT(*) AS n, ROUND(SUM(realized_pnl), 2) AS pnl_usd, ROUND(AVG(realized_pnl), 4) AS avg_pnl,
  ROUND(100.0 * SUM(realized_pnl > 0) / NULLIF(SUM(realized_pnl <> 0), 0), 1) AS win_rate_pct
FROM h GROUP BY 1, 2 ORDER BY 1, 2;
-- Q3b median holding
WITH h AS (
  SELECT CASE WHEN size <= 1e-9 THEN 'sell' ELSE 'resolution' END AS close_type,
         (julianday(closed_at) - julianday(opened_at)) * 24.0 AS hold_h
  FROM my_positions WHERE simulated = 1 AND closed_at IS NOT NULL
), r AS (
  SELECT close_type, hold_h,
         ROW_NUMBER() OVER (PARTITION BY close_type ORDER BY hold_h) AS rn,
         COUNT(*)     OVER (PARTITION BY close_type)                 AS n
  FROM h
)
SELECT close_type, MAX(n) AS n,
  ROUND(MIN(CASE WHEN rn >= 0.50 * n THEN hold_h END), 2) AS p50_h,
  ROUND(MIN(CASE WHEN rn >= 0.90 * n THEN hold_h END), 2) AS p90_h,
  ROUND(MAX(hold_h), 1) AS max_h
FROM r GROUP BY close_type;
-- Q4 slippage
SELECT o.side, COUNT(*) AS n,
  ROUND(AVG(CASE WHEN o.side = 'BUY' THEN (o.price - d.my_price) / d.my_price
                 ELSE (d.my_price - o.price) / d.my_price END) * 1e4, 1) AS avg_cost_vs_mid_bps,
  ROUND(AVG(CASE WHEN o.side = 'BUY' THEN (o.price - t.price) / t.price
                 ELSE (t.price - o.price) / t.price END) * 1e4, 1)       AS avg_cost_vs_source_bps,
  ROUND(SUM(CASE WHEN o.side = 'BUY' THEN (o.price - d.my_price)
                 ELSE (d.my_price - o.price) END * o.size), 2)           AS cost_vs_mid_usd,
  ROUND(SUM(o.size * o.price), 2)                                       AS notional_usd
FROM my_orders o
JOIN strategy_decisions d ON d.tx_hash = o.source_tx_hash AND d.decision = 'APPROVED'
JOIN detected_trades   t ON t.tx_hash = o.source_tx_hash
WHERE o.simulated = 1 AND o.realistic_fill = 1 AND o.status = 'SIMULATED'
  AND d.my_price > 0 AND t.price > 0
GROUP BY o.side;
-- Q4b distribution slippage
WITH s AS (
  SELECT o.side,
         (CASE WHEN o.side = 'BUY' THEN o.price - d.my_price ELSE d.my_price - o.price END)
           / d.my_price * 1e4 AS bps
  FROM my_orders o
  JOIN strategy_decisions d ON d.tx_hash = o.source_tx_hash AND d.decision = 'APPROVED'
  WHERE o.simulated = 1 AND o.realistic_fill = 1 AND o.status = 'SIMULATED' AND d.my_price > 0
)
SELECT side,
  CASE WHEN bps < -50 THEN '1_<-50bps (mieux que mid)' WHEN bps < 0 THEN '2_[-50,0)'
       WHEN bps < 50 THEN '3_[0,50)' WHEN bps < 200 THEN '4_[50,200)'
       WHEN bps < 500 THEN '5_[200,500)' ELSE '6_>=500bps' END AS bucket,
  COUNT(*) AS n
FROM s GROUP BY 1, 2 ORDER BY 1, 2;
-- Q5 rejets
SELECT d.decision, COALESCE(d.reason, '-') AS reason, t.side, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_all
FROM strategy_decisions d
LEFT JOIN detected_trades t ON t.tx_hash = d.tx_hash
GROUP BY 1, 2, 3 ORDER BY n DESC;
-- Q5b rejets executor
SELECT side, status, COALESCE(error_msg, '-') AS error_msg, COUNT(*) AS n
FROM my_orders WHERE simulated = 1
GROUP BY 1, 2, 3 ORDER BY n DESC;
-- Q5c SELL bloques alors qu'on detenait la position
SELECT d.reason, COUNT(*) AS n_sell_blocked_while_holding
FROM strategy_decisions d
JOIN detected_trades t ON t.tx_hash = d.tx_hash AND t.side = 'SELL'
WHERE d.decision = 'REJECTED'
  AND EXISTS (
    SELECT 1 FROM my_positions p
    WHERE p.simulated = 1 AND p.condition_id = t.condition_id AND p.asset_id = t.asset_id
      AND p.opened_at <= d.decided_at AND (p.closed_at IS NULL OR p.closed_at > d.decided_at))
GROUP BY d.reason ORDER BY n_sell_blocked_while_holding DESC;
-- Q6 latence par stage
WITH s AS (
  SELECT stage_name, duration_ms,
         ROW_NUMBER() OVER (PARTITION BY stage_name ORDER BY duration_ms) AS rn,
         COUNT(*)     OVER (PARTITION BY stage_name)                     AS n
  FROM trade_latency_samples
)
SELECT stage_name, MAX(n) AS n,
  ROUND(MIN(CASE WHEN rn >= 0.50 * n THEN duration_ms END), 1) AS p50_ms,
  ROUND(MIN(CASE WHEN rn >= 0.95 * n THEN duration_ms END), 1) AS p95_ms,
  ROUND(MIN(CASE WHEN rn >= 0.99 * n THEN duration_ms END), 1) AS p99_ms,
  ROUND(MAX(duration_ms), 1) AS max_ms
FROM s GROUP BY stage_name
ORDER BY CASE stage_name WHEN 'watcher_detected_ms' THEN 1 WHEN 'strategy_enriched_ms' THEN 2
  WHEN 'strategy_sized_ms' THEN 3 WHEN 'strategy_risk_checked_ms' THEN 4
  WHEN 'strategy_filtered_ms' THEN 5 WHEN 'executor_submitted_ms' THEN 6 ELSE 7 END;
-- Q6b e2e
WITH per AS (
  SELECT trade_id,
    SUM(CASE WHEN stage_name = 'watcher_detected_ms'   THEN duration_ms END) AS det_ms,
    SUM(CASE WHEN stage_name = 'strategy_filtered_ms'  THEN duration_ms END) AS strat_ms,
    SUM(CASE WHEN stage_name = 'executor_submitted_ms' THEN duration_ms END) AS exec_ms
  FROM trade_latency_samples GROUP BY trade_id
), e AS (
  SELECT det_ms + strat_ms + exec_ms AS e2e_ms, det_ms,
         ROW_NUMBER() OVER (ORDER BY det_ms + strat_ms + exec_ms) AS rn,
         COUNT(*) OVER () AS n
  FROM per WHERE det_ms IS NOT NULL AND strat_ms IS NOT NULL AND exec_ms IS NOT NULL
)
SELECT MAX(n) AS n_trades_soumis,
  ROUND(MIN(CASE WHEN rn >= 0.50 * n THEN e2e_ms END) / 1000.0, 2) AS p50_e2e_s,
  ROUND(MIN(CASE WHEN rn >= 0.95 * n THEN e2e_ms END) / 1000.0, 2) AS p95_e2e_s,
  ROUND(AVG(det_ms) / 1000.0, 2) AS avg_detect_s
FROM e;
-- Q7 fees
SELECT
  COALESCE(json_extract(d.pipeline_state, '$.market.feeType'), 'null/fee_free') AS fee_type,
  o.side, COUNT(*) AS n_fills,
  ROUND(SUM(o.size * o.price), 2) AS notional_usd,
  ROUND(SUM(json_extract(d.pipeline_state, '$.fee_cost_usd')), 4) AS fee_logged_sizer_usd,
  ROUND(SUM(o.size * o.price * COALESCE(json_extract(d.pipeline_state, '$.fee_rate'), 0)), 4) AS fee_buy_on_fill_usd,
  ROUND(SUM(CASE
      WHEN o.side = 'SELL' AND json_extract(d.pipeline_state, '$.market.feeType') LIKE 'crypto%'
        THEN o.size * o.price * 0.072 * o.price * (1 - o.price)
      WHEN o.side = 'SELL' AND json_extract(d.pipeline_state, '$.market.feeType') LIKE 'sports%'
        THEN o.size * o.price * 0.03 * o.price * (1 - o.price)
      ELSE 0 END), 4) AS fee_sell_estimated_usd
FROM my_orders o
JOIN strategy_decisions d ON d.tx_hash = o.source_tx_hash AND d.decision = 'APPROVED'
WHERE o.simulated = 1 AND o.realistic_fill = 1 AND o.status = 'SIMULATED'
GROUP BY 1, 2 ORDER BY 1, 2;
-- Q8 categories
WITH mk AS (
  SELECT condition_id, MAX(slug) AS slug,
         MAX(json_extract(raw_json, '$.title')) AS title,
         MAX(json_extract(raw_json, '$.eventSlug')) AS event_slug
  FROM detected_trades GROUP BY condition_id
), ft AS (
  SELECT json_extract(pipeline_state, '$.condition_id') AS condition_id,
         MAX(json_extract(pipeline_state, '$.market.feeType')) AS fee_type
  FROM strategy_decisions GROUP BY 1
), cat AS (
  SELECT mk.condition_id,
    CASE
      WHEN mk.slug LIKE '%-updown-5m-%'  THEN 'crypto_updown_5m'
      WHEN mk.slug LIKE '%-updown-15m-%' THEN 'crypto_updown_15m'
      WHEN mk.slug LIKE '%updown%' OR mk.slug LIKE '%up-or-down%'
           OR mk.title LIKE '%Up or Down%' THEN 'crypto_updown_autre'
      WHEN ft.fee_type LIKE 'crypto%' OR mk.slug LIKE '%bitcoin%' OR mk.slug LIKE 'btc-%'
           OR mk.slug LIKE '%ethereum%' OR mk.slug LIKE 'eth-%' OR mk.slug LIKE '%solana%'
           OR mk.slug LIKE '%xrp%' OR mk.slug LIKE '%crypto%' THEN 'crypto_autre'
      WHEN ft.fee_type LIKE 'sports%'
           OR mk.slug LIKE 'nba-%' OR mk.slug LIKE 'nfl-%' OR mk.slug LIKE 'nhl-%' OR mk.slug LIKE 'mlb-%'
           OR mk.slug LIKE 'epl-%' OR mk.slug LIKE 'ucl-%' OR mk.slug LIKE 'lal-%' OR mk.slug LIKE 'atp-%'
           OR mk.slug LIKE 'wta-%' OR mk.slug LIKE 'ufc-%' OR mk.slug LIKE 'lol-%' OR mk.slug LIKE 'cs2-%'
           OR mk.slug LIKE 'dota2-%' OR mk.slug LIKE 'val-%' OR mk.slug LIKE '%-vs-%' THEN 'sports_esports'
      WHEN mk.slug LIKE '%election%' OR mk.slug LIKE '%president%' OR mk.slug LIKE '%trump%'
           OR mk.slug LIKE '%senate%' OR mk.slug LIKE '%governor%' OR mk.slug LIKE '%prime-minister%'
           THEN 'politique'
      ELSE 'autre' END AS category
  FROM mk LEFT JOIN ft ON ft.condition_id = mk.condition_id
)
SELECT COALESCE(c.category, '(inconnu)') AS category,
  COUNT(p.id) AS n_pos, SUM(p.closed_at IS NOT NULL) AS n_closed,
  SUM(p.realized_pnl > 0) AS wins, SUM(p.realized_pnl < 0) AS losses,
  ROUND(100.0 * SUM(p.realized_pnl > 0) / NULLIF(SUM(p.realized_pnl <> 0), 0), 1) AS win_rate_pct,
  ROUND(SUM(COALESCE(p.realized_pnl, 0)), 2) AS realized_usd,
  ROUND(SUM(CASE WHEN p.closed_at IS NULL THEN p.size * p.avg_price ELSE 0 END), 2) AS open_cost_usd
FROM my_positions p
LEFT JOIN cat c ON c.condition_id = p.condition_id
WHERE p.simulated = 1
GROUP BY 1 ORDER BY realized_usd;
-- Q8b funnel updown
SELECT
  CASE WHEN t.slug LIKE '%-updown-5m-%' THEN 'updown_5m'
       WHEN t.slug LIKE '%-updown-15m-%' THEN 'updown_15m'
       ELSE 'updown_autre' END AS kind,
  t.side, COALESCE(d.decision, '(pas de decision)') AS decision, COALESCE(d.reason, '-') AS reason,
  COUNT(*) AS n, ROUND(SUM(t.usdc_size), 0) AS source_usd
FROM detected_trades t
LEFT JOIN strategy_decisions d ON d.tx_hash = t.tx_hash
WHERE t.slug LIKE '%updown%' OR t.slug LIKE '%up-or-down%'
GROUP BY 1, 2, 3, 4 ORDER BY n DESC;
-- Q9 positions ouvertes
WITH m AS (
  SELECT json_extract(pipeline_state, '$.condition_id') AS cid,
         MAX(json_extract(pipeline_state, '$.market.endDate'))  AS end_date,
         MAX(json_extract(pipeline_state, '$.market.question')) AS question
  FROM strategy_decisions GROUP BY 1
)
SELECT p.id, p.source_wallet_address, ROUND(p.size, 4) AS size, ROUND(p.avg_price, 4) AS avg_px,
  ROUND(p.size * p.avg_price, 2) AS cost_usd, p.opened_at,
  ROUND(julianday('now') - julianday(p.opened_at), 1) AS age_days, m.end_date,
  CASE WHEN m.end_date IS NULL THEN '?'
       WHEN m.end_date < strftime('%Y-%m-%dT%H:%M:%SZ', 'now') THEN 'END_PASSED' ELSE 'pending' END AS st,
  substr(m.question, 1, 60) AS question
FROM my_positions p LEFT JOIN m ON m.cid = p.condition_id
WHERE p.simulated = 1 AND p.closed_at IS NULL
ORDER BY age_days DESC;
-- Q9b agrégat ouvertes
WITH m AS (
  SELECT json_extract(pipeline_state, '$.condition_id') AS cid,
         MAX(json_extract(pipeline_state, '$.market.endDate')) AS end_date
  FROM strategy_decisions GROUP BY 1
)
SELECT CASE WHEN m.end_date < strftime('%Y-%m-%dT%H:%M:%SZ', 'now') THEN 'END_PASSED'
            WHEN m.end_date IS NULL THEN '?' ELSE 'pending' END AS st,
       COUNT(*) AS n_open, ROUND(SUM(p.size * p.avg_price), 2) AS cost_usd
FROM my_positions p LEFT JOIN m ON m.cid = p.condition_id
WHERE p.simulated = 1 AND p.closed_at IS NULL GROUP BY 1;
-- Q9c orphelins UNIQUE
SELECT o.id AS order_id, o.condition_id, o.asset_id, o.size, o.price, o.sent_at,
       p.id AS pos_id, p.closed_at AS pos_closed_at
FROM my_orders o
JOIN my_positions p ON p.condition_id = o.condition_id AND p.asset_id = o.asset_id AND p.simulated = 1
WHERE o.simulated = 1 AND o.realistic_fill = 1 AND o.status = 'SIMULATED' AND o.side = 'BUY'
  AND p.closed_at IS NOT NULL AND o.sent_at > p.closed_at
ORDER BY o.sent_at;
-- Q10 ecart prix + delais
SELECT o.side, COUNT(*) AS n,
  ROUND(AVG((julianday(d.decided_at) - julianday(t.timestamp)) * 86400), 1) AS avg_onchain_to_decision_s,
  ROUND(AVG((julianday(o.sent_at)    - julianday(t.timestamp)) * 86400), 1) AS avg_onchain_to_fill_s,
  ROUND(AVG(o.price - t.price), 4)      AS avg_fill_minus_source_px,
  ROUND(AVG(ABS(o.price - t.price)), 4) AS avg_abs_diff_px,
  ROUND(AVG(d.slippage_pct), 2)         AS avg_slippage_pct_mid_vs_source
FROM my_orders o
JOIN detected_trades    t ON t.tx_hash = o.source_tx_hash
JOIN strategy_decisions d ON d.tx_hash = o.source_tx_hash AND d.decision = 'APPROVED'
WHERE o.simulated = 1 AND o.realistic_fill = 1 AND o.status = 'SIMULATED'
GROUP BY o.side;
-- Q11 trades par wallet
SELECT t.target_wallet, COUNT(*) AS n_detected,
  SUM(t.side = 'BUY') AS buys, SUM(t.side = 'SELL') AS sells,
  SUM(d.decision = 'APPROVED') AS approved,
  SUM(o.status = 'SIMULATED') AS filled_sim, SUM(o.status = 'REJECTED') AS rejected_exec,
  ROUND(SUM(t.usdc_size), 0) AS source_volume_usd,
  SUM(t.slug LIKE '%updown%' OR t.slug LIKE '%up-or-down%') AS n_updown,
  MIN(t.timestamp) AS first_trade, MAX(t.timestamp) AS last_trade
FROM detected_trades t
LEFT JOIN strategy_decisions d ON d.tx_hash = t.tx_hash
LEFT JOIN my_orders o ON o.source_tx_hash = t.tx_hash
GROUP BY t.target_wallet ORDER BY n_detected DESC;
-- Q12 turnover events
SELECT event_type, COUNT(*) AS n, COUNT(DISTINCT wallet_address) AS n_wallets
FROM trader_events GROUP BY 1 ORDER BY n DESC;
-- Q12b status
SELECT status, is_probation, COUNT(*) AS n FROM target_traders GROUP BY 1, 2;
-- Q12c spells
WITH tr AS (
  SELECT wallet_address, at, to_status,
         LEAD(at) OVER (PARTITION BY wallet_address ORDER BY at) AS next_at
  FROM trader_events
  WHERE wallet_address IS NOT NULL AND to_status IS NOT NULL
    AND (from_status IS NULL OR from_status <> to_status)
)
SELECT wallet_address, COUNT(*) AS n_active_spells,
  ROUND(SUM(julianday(COALESCE(next_at, datetime('now'))) - julianday(at)), 2) AS days_active_total,
  MIN(at) AS first_active_at
FROM tr WHERE to_status IN ('active', 'pinned')
GROUP BY 1 ORDER BY days_active_total DESC;
-- Q12d turnover jour
SELECT date(at) AS day,
  SUM(event_type LIKE 'promoted%') AS promotions,
  SUM(event_type LIKE 'demoted%' OR event_type IN ('eviction_completed_to_shadow', 'auto_blacklisted', 'blacklisted')) AS exits,
  SUM(event_type = 'discovered') AS discovered,
  SUM(event_type = 'gate_rejected') AS gate_rejected
FROM trader_events GROUP BY 1 ORDER BY 1;
-- Q13 drawdown
WITH s AS (
  SELECT timestamp, total_usdc, drawdown_pct, realized_pnl,
         MAX(total_usdc) OVER (ORDER BY timestamp ROWS UNBOUNDED PRECEDING) AS peak
  FROM pnl_snapshots WHERE execution_mode = 'dry_run'
)
SELECT COUNT(*) AS n_snap, ROUND(MIN(total_usdc), 2) AS min_total, ROUND(MAX(total_usdc), 2) AS max_total,
  ROUND(MAX((peak - total_usdc) / peak * 100), 2) AS max_dd_pct_recalc,
  ROUND(MAX(drawdown_pct), 2) AS max_dd_pct_logged,
  (SELECT ROUND(total_usdc, 2) FROM s ORDER BY timestamp DESC LIMIT 1) AS last_total,
  (SELECT ROUND(realized_pnl, 2) FROM s ORDER BY timestamp DESC LIMIT 1) AS last_realized_cum
FROM s;
-- Q13b daily
SELECT date(timestamp) AS day, COUNT(*) AS n,
  ROUND(MIN(total_usdc), 2) AS min_total, ROUND(MAX(total_usdc), 2) AS max_total,
  ROUND(MAX(drawdown_pct), 2) AS max_dd_pct, ROUND(MAX(realized_pnl), 2) AS realized_cum,
  MAX(open_positions_count) AS max_open
FROM pnl_snapshots WHERE execution_mode = 'dry_run' GROUP BY 1 ORDER BY 1;
-- Q13c gaps
WITH g AS (
  SELECT timestamp, total_usdc, LAG(timestamp) OVER (ORDER BY timestamp) AS prev_ts
  FROM pnl_snapshots WHERE execution_mode = 'dry_run'
)
SELECT prev_ts, timestamp, ROUND((julianday(timestamp) - julianday(prev_ts)) * 24, 2) AS gap_h
FROM g WHERE (julianday(timestamp) - julianday(prev_ts)) * 24 > 0.5
ORDER BY gap_h DESC LIMIT 20;
-- Q13d kill switch
SELECT at, json_extract(event_metadata, '$.drawdown_pct') AS dd_pct,
       json_extract(event_metadata, '$.total_usdc') AS total, json_extract(event_metadata, '$.execution_mode') AS mode
FROM trader_events WHERE event_type = 'kill_switch' ORDER BY at;
