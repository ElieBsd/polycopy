ÉTAT : complet — sections 0 à 9 + annexes A/B faites (audit lecture seule, 2026-11-05)

# Phase 1 — Inventaire du dépôt `polycopy` en vue du pivot « scalping Up/Down crypto »

> Audit en lecture seule du dépôt `/home/user/polycopy` (branche `claude/polymarket-updown-scalping-audit-5j7rwz`, HEAD `371f8dc`, 2026-05-22). Aucun fichier du dépôt modifié, bot non exécuté, aucun appel réseau.
> Les références `fichier:ligne` sont relatives à la racine du dépôt. Les affirmations marquées **(à vérifier)** n'ont pas pu être confirmées sans réseau ni SDK installé (`py-clob-client-v2` n'est pas installé dans cet environnement).
> Les requêtes SQL de la §7 ont été validées syntaxiquement sur un schéma SQLite reconstruit à partir des migrations (fichiers de test : `/tmp/claude-0/-home-user-polycopy/c1517565-1179-5cad-9d67-6c943a23d73d/scratchpad/phase1_sqltest/schema.sql` et `/tmp/claude-0/-home-user-polycopy/c1517565-1179-5cad-9d67-6c943a23d73d/scratchpad/phase1_sqltest/postmortem.sql`).

---

## 0. TL;DR

1. **polycopy est un pipeline « événement externe → décision → ordre FOK »**, conçu pour copier des trades détectés par polling REST de la Data API (5 s), avec une latence observée détection→POST de 8-20 s (p50 13,4 s le 2026-04-24, `docs/next/MK.md`). Rien n'y est piloté par le carnet d'ordres ; le WebSocket `market` ne sert qu'à fournir un mid au `SlippageChecker`.
2. **Le bot actuel est cassé en production** : la Data API v1 (retirée, HTTP 410) alimente le watcher (`/activity`), toute la discovery (`/holders`, `/trades`, `/value`, `/positions`, `/activity`), le `WalletStateReader` live (`/positions`) qui nourrit le kill switch live, et le health check du dashboard. Voir §9 (16 sites d'appel).
3. **L'executor n'a jamais tourné en live** : `FIXME` sur la sémantique de `size` (`src/polycopy/executor/clob_write_client.py:126`), limite = **mid** (`src/polycopy/strategy/orchestrator.py:191`) avec FOK (marchable seulement si le spread est nul), capital = stub constant (`src/polycopy/executor/wallet_state_reader.py:47,62`), aucun suivi d'ordre après la réponse du POST, aucun `cancel`, aucun channel `user`, aucun redeem.
4. **Le « dry-run réaliste » n'est pas réaliste pour du scalping** : la marche du carnet ignore le prix limite, la taille min (5 shares), les fees, la latence ; le book vient d'un `GET /book` REST caché 5 s ; les positions sont valorisées au mid ; et il y a **un bug de schéma qui interdit de rouvrir une position sur le même token** une fois fermée (contrainte UNIQUE non partielle, §3/§8). Pour un scalpeur qui ré-entre plusieurs fois sur le même token, c'est bloquant.
5. **Le modèle « SELL = copie d'un SELL source » est diffus** : `OrderApproved.tx_hash` → `my_orders.source_tx_hash NOT NULL`, `MyPosition.source_wallet_address`, `PositionSizer._check_sell` (taille = taille source × ratio), `realized_pnl` calculé seulement à la clôture complète et seulement sur la dernière tranche, et surtout **les SELL passent par les mêmes filtres que les BUY** (`MarketFilter.expiry_too_close` avec `MIN_HOURS_TO_EXPIRY=24`, `SlippageChecker`, `RiskManager.capital_exceeded`), ce qui bloque des sorties.
6. **Recommandation structurelle : nouveau dépôt, pas un fork.** On récupère environ 25 % du code (≈ 5 500 lignes : client CLOB signataire et ses garde-fous, monitoring/Telegram, sentinel/kill-switch ordering, remote control, coque du dashboard, CLI/logging, `FeeRateClient`, `GammaApiClient`, squelette WS). On repart d'une **baseline Alembic neuve** : garder les 10 révisions de copy trading coûte plus qu'il ne rapporte.
7. **L'intuition « garder storage, monitoring, dashboard, executor, dry-run, WS, fees, latence ; jeter discovery, scoring, eviction, watcher » est juste dans la direction**, mais pour le moment surestime ce qui est réutilisable dans executor, dry-run, WS client et storage : là, on récupère des briques, pas des modules. Elle oublie aussi les modules qui n'existent pas du tout : flux spot BTC, ordonnanceur de fenêtres, channel `user`, OMS (order manager), position manager TP/SL/time-stop, ledger cash/pUSD, redeem, enregistreur de données et backtester (le mode `SIMULATION` n'est qu'un stub).

---

## 1. Architecture actuelle

### 1.1 Points d'entrée et boot

| Étape | Où | Détail |
|---|---|---|
| CLI | `src/polycopy/__main__.py:1-8` → `src/polycopy/cli/runner.py:208` (`main`) | Flags `--execution-mode {simulation,dry_run,live}`, `--dry-run` (legacy), `--log-level`, `--verbose`, `--no-cli`, `--force-resume` (`runner.py:44-98`). Script console `polycopy` (`pyproject.toml`). |
| Logging | `runner.py:221-228` → `cli/logging_config.py` | Fichier rotatif `~/.polycopy/logs/polycopy.log` (0o600/0o700), JSON structlog. |
| Boot async | `runner.py:136-205` (`_async_main`) | `create_engine_and_session` → `init_db` (Alembic `upgrade head`, `storage/init_db.py:46-72`) → purge latence boot → 3 queues → sentinel `halt.flag` → `build_orchestrators(mode)` → `asyncio.TaskGroup` (`runner.py:199`). |
| Orchestrateurs | `src/polycopy/cli/boot.py:51-133` | Mode `normal` : Watcher, Strategy, Executor, Monitoring, (+ Dashboard, Discovery, LatencyPurge, RemoteControl selon flags). Mode `paused` (sentinel présent) : Monitoring(paused), Dashboard, RemoteControl. |
| Settings | `src/polycopy/config.py` (1 431 lignes, 29 validators) | Singleton module-level, `.env`. `database_url` par défaut `sqlite+aiosqlite:///polycopy.db` (`config.py:353`) → fichier **relatif au répertoire courant**. |

Remarque packaging : `alembic` n'est déclaré qu'en dépendance `dev` (`pyproject.toml`), alors que `storage/init_db.py:16,20` l'importe au runtime. Ça marche uniquement parce que `scripts/setup.sh:82` installe `.[dev]`. `init_db._project_root()` suppose une copie source du dépôt (`init_db.py:29-31`). Deux dépendances runtime déclarées ne sont jamais importées : `polymarket-apis` et `python-telegram-bot` (le client Telegram est en httpx direct, `monitoring/telegram_client.py:1`).

### 1.2 Flux de données de bout en bout

```
Data API v1 /activity (poll 5s/wallet)          Gamma /markets           CLOB REST + WSS market
        │  WalletPoller (watcher/wallet_poller.py)      │                          │
        ▼                                               │                          │
 detected_trades (INSERT OR dedup tx_hash)              │                          │
        │ put_nowait(DetectedTradeDTO)                  │                          │
        ▼  detected_trades_queue (maxsize 1000)         │                          │
 StrategyOrchestrator._consume_loop ──► run_pipeline (strategy/pipeline.py:430-483)
   1 TraderLifecycleFilter (DB)                         │                          │
   2 MarketFilter ◄──────────── get_market(condition_id)┘                          │
   3 EntryPriceFilter                                                              │
   4 PositionSizer (DB + FeeRateClient GET /clob-markets/{cid})                    │
   5 SlippageChecker ◄──────── mid WS cache (fallback GET /midpoint) ──────────────┘
   6 RiskManager (DB, capital stub)
        │ INSERT strategy_decisions (pipeline_state JSON complet, dump Gamma inclus)
        ▼ put_nowait(OrderApproved{tx_hash, my_size, my_price=mid, source_wallet})
 approved_orders_queue (maxsize 1000)
        ▼
 ExecutorOrchestrator._consume_loop (sériel) ──► execute_order (executor/pipeline.py:77-229)
   GET /tick-size (cache 5 min) + Gamma neg_risk → round(mid, tick) → BuiltOrder(FOK)
   ├─ simulation : MyOrder SIMULATED (stub)
   ├─ dry_run + M8 : GET /book (cache 5 s) → simulate_fill → my_orders + my_positions(simulated=1)
   └─ live : Data API /positions (exposition) vs stub → MyOrder SENT → SDK create_and_post_order
            → réponse synchrone → FILLED + upsert_on_fill, ou REJECTED, ou SENT (à vie)
        │
 MonitoringOrchestrator : PnlSnapshotWriter (300 s) → pnl_snapshots → kill switch
   AlertDispatcher ◄── alerts_queue (maxsize 100) ◄── tous les modules → Telegram MarkdownV2
 DryRunResolutionWatcher (30 min) : Gamma closed → close_virtual(realized_pnl)
 Dashboard FastAPI (GET-only) lit la DB ; RemoteControl (Tailscale+TOTP) pose/retire le sentinel
```

### 1.3 Événements et primitives asyncio

| Primitive | Producteur → consommateur | Où | Comportement en cas de saturation |
|---|---|---|---|
| `detected_trades_queue: Queue[DetectedTradeDTO]` (1000) | `WalletPoller._publish` → `StrategyOrchestrator` | `runner.py:41,166-168`, `watcher/wallet_poller.py:145-151` | `put_nowait` → drop + `strategy_queue_full` |
| `approved_orders_queue: Queue[OrderApproved]` (1000) | `StrategyOrchestrator` → `ExecutorOrchestrator` | `strategy/orchestrator.py:197-200` | drop + `executor_queue_full` |
| `alerts_queue: Queue[Alert]` (100) | tous → `AlertDispatcher` | `runner.py:42` | drop + `alerts_queue_full` |
| `stop_event: asyncio.Event` | signal SIGINT/SIGTERM, kill switch, auth fatal | `runner.py:99-113`, `monitoring/pnl_writer.py:229`, `executor/orchestrator.py:196-200` | toutes les boucles `while not stop_event.is_set()` |
| Sentinel `~/.polycopy/halt.flag` | kill switch, `/stop`, auto-lockdown | `remote_control/sentinel.py:54`, lu au boot `runner.py:182` | boot suivant en mode `paused` |
| contextvar structlog `trade_id` | `WalletPoller` → re-bind strategy/executor | `wallet_poller.py:115`, `strategy/orchestrator.py:145-146`, `executor/orchestrator.py:176-178` | — |

Toutes les consommations sont du **pull** sur queue avec `wait_for(get(), 1 s)`. Il n'y a pas d'event bus ni de fan-out. Le WS client est un cache interrogé par le pipeline, il ne pousse rien.

La règle de dépendance « aucun module fonctionnel ne dépend d'un autre » (CLAUDE.md) **n'est pas respectée** : `strategy/orchestrator.py:21` importe `executor.fee_rate_client`, `executor/pipeline.py:22-23` importe `strategy.dtos` et `strategy.gamma_client`, `monitoring/pnl_writer.py:21-23` importe les readers de l'executor, et `executor/realistic_fill.py` importe `strategy.dtos.OrderApproved`.

### 1.4 Tables DB (SQLite, head Alembic `0010_m17_pnl_snapshot_execution_mode`)

Chaîne : `0001_baseline_m3` → `0002_m4_pnl_snapshot` → `0003_m5_discovery` → `0004_m8_dry_run_realistic` → `0005_m11_latency_samples` → `0006_m12_trader_daily_pnl` → `0007_m5_bis_eviction` → `0009_m15_anti_toxic_lifecycle` → `0010_m17_...` (0008 sauté volontairement). Toutes les colonnes monétaires sont en `Float` (audit M-012). Pas de PRAGMA WAL ni `busy_timeout` (aucune occurrence dans `src/`).

| Table | Colonnes importantes | Spécificité copy trading | Réf. |
|---|---|---|---|
| `target_traders` | `wallet_address` UNIQUE, `status` ∈ {shadow, active, sell_only, pinned, blacklisted}, `pinned`, `score`, `is_probation`, `promoted_at`, `eviction_*` | 100 % | `storage/models.py:35-137` |
| `detected_trades` | `tx_hash` UNIQUE, `target_wallet`, `condition_id`, `asset_id`, `side`, `size`, `usdc_size`, `price`, `timestamp` (on-chain), `outcome`, `slug`, `raw_json` (payload Data API camelCase) | 100 % | `models.py:140-161` |
| `strategy_decisions` | `detected_trade_id` (**toujours 0**, `strategy/orchestrator.py:237-241`), `tx_hash`, `decision`, `reason`, `my_size`, `my_price` (= mid), `slippage_pct`, `decided_at`, `pipeline_state` JSON (contient `market` = dump Gamma complet avec `slug`, `question`, `feeType`, `endDate`, `fee_rate`, `fee_cost_usd`, `filter_trace`) | forte | `models.py:164-183`, `strategy/dtos.py:130-150` |
| `my_orders` | `source_tx_hash` **NOT NULL**, `clob_order_id`, `condition_id`, `asset_id`, `side`, `size`, `price`, `tick_size`, `neg_risk`, `order_type` (toujours `FOK`), `status` ∈ {SIMULATED, SENT, FILLED, REJECTED, FAILED} (PARTIALLY_FILLED jamais posé), `taking_amount`, `making_amount`, `transaction_hashes`, `error_msg`, `simulated`, `realistic_fill`, `sent_at`, `filled_at` | `source_tx_hash` | `models.py:189-224` |
| `my_positions` | `condition_id`, `asset_id`, `size`, `avg_price`, `opened_at`, `closed_at`, `simulated`, `realized_pnl`, `source_wallet_address` ; **UNIQUE(condition_id, asset_id, simulated)** y compris lignes fermées | `source_wallet_address` | `models.py:227-284`, `alembic/versions/0004_m8_dry_run_realistic.py:56-60` |
| `pnl_snapshots` | `timestamp`, `total_usdc`, `realized_pnl`, `unrealized_pnl`, `drawdown_pct`, `open_positions_count`, `is_dry_run` (déprécié), `execution_mode` CHECK ∈ {simulation, dry_run, live} | non | `models.py:287-326` |
| `trade_latency_samples` | `trade_id` (uuid hex, **non joignable** à un trade ou un ordre), `stage_name`, `duration_ms`, `timestamp` ; purge à 7 j | non (stages copy) | `models.py:329-350` |
| `trader_scores` | `wallet_address`, `score`, `scoring_version`, `cycle_at`, `metrics_snapshot` | 100 % | `models.py:356-379` |
| `trader_events` | `wallet_address` (nullable depuis 0010), `event_type`, `at`, `from_status`, `to_status`, `event_metadata` ; **sert aussi d'audit au kill switch** (`event_type='kill_switch'`) | forte | `models.py:382-421`, `monitoring/pnl_writer.py:187-206` |
| `trader_daily_pnl` | equity curve des wallets suivis | 100 % | `models.py:424-460` |

### 1.5 Modes d'exécution (M10)

`EXECUTION_MODE` (`config.py:356-369`, défaut `dry_run`) :

- **`simulation`** : seul `_persist_simulated_stub` est réellement implémenté (`executor/pipeline.py:114-124`). Il n'y a ni harness de backtest, ni fixtures rejouées. Le watcher continue d'appeler le réseau. Le mode existe donc de nom seulement.
- **`dry_run`** : pipeline complet en ligne. Avec `DRY_RUN_REALISTIC_FILL=true` (configuration utilisée par le propriétaire, `docs/todo.md:339-343`) : `/book` + positions virtuelles + `DryRunResolutionWatcher` + `VirtualWalletStateReader`. Sans ce flag : stub M3.
- **`live`** : signature CLOB V2 via `py-clob-client-v2==1.0.0`. **Aucune preuve d'exécution réelle** dans les docs ou les commits (la todo ne prévoit le flip qu'après le test 30 j).

### 1.6 Garde-fous de sécurité : ce qui existe et ce qui est réellement protégé

| Garde-fou | Implémentation | Remarque pour le nouveau bot |
|---|---|---|
| M3-1 lazy init `ClobClient` | `executor/orchestrator.py:89-91` ; `ClobWriteClient.__init__` refuse si `execution_mode != "live"` (`clob_write_client.py:41-51`) | à garder |
| M3-2 `RuntimeError` au boot si live sans clés | `executor/orchestrator.py:56-63` (avant TaskGroup) | à garder |
| M3-3 double check juste avant POST | `executor/pipeline.py:191-195` + `clob_write_client.py:99-103` | à garder |
| M3-4 re-fetch wallet avant POST | `executor/pipeline.py:152-189` | **faible** : exposition via Data API `/positions` v1 (cassée), capital = stub constant `RISK_AVAILABLE_CAPITAL_USD_STUB` ; s'applique aussi aux SELL |
| M8 4ᵉ garde-fou | `assert settings.execution_mode == "dry_run"` (`executor/pipeline.py:404`) | à garder (pattern) |
| M10 parité kill switch | `monitoring/pnl_writer.py:152-243` identique dans les 3 modes | concept à garder, mécanisme à refaire (polling 300 s) |
| M12_bis sentinel + ordre strict | insert_event → push_alert → touch sentinel → `stop_event.set()` (`pnl_writer.py:184-229`) | à garder tel quel |
| M12_bis remote control | FastAPI bindée sur l'IP Tailscale, TOTP, rate limit, auto-lockdown (`remote_control/server.py:84-202`) | à garder (zéro couplage) |
| M17 MD.1 ségrégation `simulated` | `pipeline.py:192-199,330-337,405-411` | concept à garder |
| M17 MD.2 CRITICAL bypass digest | `monitoring/alert_dispatcher.py:117-150` | à garder |
| M17 MD.3 baseline drawdown par mode | `pnl_snapshots.execution_mode` | à garder |
| Pas de secret dans les logs/templates | tests grep (`tests/unit/test_*security*`, `test_remote_control_no_secret_leak.py`, `test_m8_security_grep.py`) | à garder |

Ce qui manque côté sécurité/risque pour du scalping : un cap d'exposition **pré-trade** sur cash réel (balance pUSD), des limites de perte par fenêtre et par jour, un nombre max d'ordres ouverts, un « cancel all » si le flux WS est stale ou se déconnecte, et un garde-fou sur la taille minimale d'ordre.

### 1.7 Taille du code et des tests

| Module | Python | Templates | Commentaire |
|---|---|---|---|
| `discovery/` (scoring, eviction, goldsky) | 6 408 | — | 100 % copy trading |
| `dashboard/` | 3 785 (dont `queries.py` 2 229) | 1 950 | `queries.py` : 173 références à des concepts copy |
| `executor/` | 2 287 | — | |
| `storage/` | 2 245 (dont `repositories.py` 1 335) | — | |
| `monitoring/` | 2 163 | 326 (24 templates `.md.j2`) | |
| `strategy/` | 1 927 | — | |
| `config.py` | 1 431 | — | env. 50 % discovery/scoring/eviction |
| `remote_control/` | 987 | — | 0 référence copy |
| `cli/` | 796 | — | |
| `watcher/` | 595 | — | 100 % copy |
| **Total `src/`** | **≈ 22 600** | | |

Tests : 141 fichiers `tests/unit` (≈ 29 000 lignes, ≈ 1 296 fonctions `test_*`, ≈ 1 541 cas selon la ROADMAP), 10 tests d'intégration opt-in. Répartition par nom de fichier : ≈ 38 discovery/watcher (à jeter), 21 executor/CLOB, 20 dashboard, 30 monitoring/alertes/PnL, 20 CLI/config/remote control. Fixtures réelles **utiles** : `tests/fixtures/clob_orderbook_sample.json` (réel), `gamma_market_crypto_fees_sample.json` (réel : « Bitcoin Up or Down on April 25? », outcomes `["Up","Down"]`, `eventStartTime`, `orderMinSize=5`, `orderPriceMinTickSize=0.001`, `feeType=crypto_fees_v2`, `resolutionSource=https://www.binance.com/en/trade/BTC_USDT`), `data_api_trades_global_sample.json` (réel v1, 44/500 trades ≥ 100 $ sur des marchés `btc|eth|xrp-updown-5m|15m-<ts>`). Fixtures **synthétiques** malgré la mention « capturé » : `clob_ws_market_sample.jsonl` (hashes `0xdef456`, ids `8888…`) et `clob_v2_market_*_sample.json` (token ids `1234567890…`).

---

## 2. Inventaire GARDER / ADAPTER / JETER

Effort : **S** ≤ 1 j, **M** 2-4 j, **L** ≥ 5 j (single dev, tests inclus).

### 2.1 Décision structurelle : nouveau dépôt plutôt qu'un fork

**Recommandation : nouveau dépôt** (par exemple `polyscalp`), en portant explicitement les fichiers réutilisables. On peut conserver leur historique avec `git filter-repo --path …` si on y tient.

Pourquoi pas un fork :
- **Volume à retirer** : `discovery/` (6 408 l.), `watcher/` (595 l.), environ 700 lignes de `config.py` et la plupart des 29 validators croisés, environ 1 500 lignes de `dashboard/queries.py`, 11 templates Telegram (`trader_*`, `discovery_*`, `dry_run_market_resolved_neg_risk`), environ 38 fichiers de tests, 4 tables, 10 révisions Alembic. En tout, environ 60 % du dépôt.
- **Couplages cachés difficiles à retirer proprement** : `my_orders.source_tx_hash NOT NULL` (`models.py:195`) ; `OrderApproved.tx_hash` sert de clé d'audit partout ; `MyPosition.source_wallet_address` ; l'audit du kill switch passe par `trader_events` (`pnl_writer.py:187-201`) ; `StartupNotifier`, `HeartbeatScheduler` et `daily_summary_queries.py` comptent des wallets suivis ; les pages dashboard Home, Performance et Activity joignent `detected_trades`. Chacun de ces points demande un refactor dans un fork.
- **Le `CLAUDE.md` (70 Ko) est une liste d'invariants de copy trading** (versioning sacré du scoring, pinned, blacklist, probation…). Dans un fork, il induira en erreur toutes les futures sessions d'agent. Il faut l'écrire à neuf en ne gardant que la section sécurité (creds, dry-run, kill switch, sentinel, secrets).
- **Les bugs de schéma sont structurels** : UNIQUE sur positions fermées, `Float` pour l'argent, `realized_pnl` sur une seule ligne, absence de table de fills. Les corriger dans la chaîne existante, c'est 3-4 migrations `batch_alter_table(recreate="always")` plus leurs downgrades, pour un schéma qu'on va de toute façon remplacer.
- Un fork **ne réduit pas le risque** : le code réutilisable est petit et bien délimité (voir 2.2), et le gros de la valeur du nouveau bot (feed L2, OMS, position manager, simulateur maker) est à écrire.

**Coût de garder Alembic avec ses 10 migrations** :
- chaque nouvelle table de scalping s'empile après `0010`, et les tables `target_traders`, `trader_scores`, `trader_events` et `trader_daily_pnl` restent mortes ou doivent être supprimées par une migration dédiée, avec un downgrade à maintenir ;
- 5 fichiers de tests Alembic (`test_alembic_*`, `test_m5_alembic_migration.py`, `test_m8_alembic_migration.py`) testent une chaîne sans valeur pour le nouveau bot ;
- la logique d'auto-stamp « DB M3 sans `alembic_version` » (`init_db.py:66-72`) devient du code mort ;
- de toute façon, une DB neuve est nécessaire (la todo fait déjà des wipes, `docs/todo.md:278-330`).

→ **Garder l'outil (SQLAlchemy 2.0 async + Alembic) et le pattern `batch_alter_table` SQLite-friendly, mais repartir d'une baseline `0001` neuve.** Mettre `alembic` en dépendance runtime, activer `PRAGMA journal_mode=WAL` et `busy_timeout`, et stocker les montants en `Numeric`/`Decimal` ou en micro-unités entières (6 décimales, comme le fixed-math CLOB).

### 2.2 Module par module

| Module | Verdict | Justification | Effort | Couplages à casser |
|---|---|---|---|---|
| `watcher/` | **JETER** | Polling par wallet de `/activity` v1 (HTTP 410). Le concept de « trade source » n'a pas de sens pour le nouveau bot. | — | `DetectedTradeDTO` (`storage/dtos.py:9-39`), `TargetTraderRepository.list_wallets_to_poll` (`repositories.py:84`), resolver probation |
| `discovery/` (incl. `scoring/`, `eviction/`, goldsky) | **JETER** | 100 % copy trading. Les endpoints v1 sont cassés. | — | `cli/boot.py:121-124`, config L750-1110 et validators, 4 tables, templates Telegram, pages dashboard `/traders*` et `/performance` |
| `strategy/` | **ADAPTER partiel / réécrire** | Filtres pilotés par trade source. On garde Gamma, le cache adaptatif, le squelette WS et la formule de fee pure. | L | `OrderApproved`, `PipelineContext.trade`, `strategy.dtos` importé par l'executor |
| `executor/` | **ADAPTER partiel / réécrire** | On garde `ClobWriteClient` (coque + garde-fous), `FeeRateClient`, l'orderbook reader et les helpers purs. `pipeline.py` est à réécrire (OMS). | L | `OrderApproved`, `MyOrderDTO.source_tx_hash`, `WalletStateReader` (Data API) |
| `storage/` | **ADAPTER (techno) / JETER (schéma)** | Garder engine, pattern repositories, `PnlSnapshotRepository`, `TradeLatencyRepository`, purge scheduler. Nouveau schéma. | M | `init_db` (upsert `target_wallets`), `TraderEvent` utilisé par le kill switch |
| `alembic/` | **JETER la chaîne / GARDER l'outil** | Voir 2.1. | S | `alembic.ini`, `init_db._project_root` |
| `monitoring/` | **GARDER majoritairement** | Telegram, renderer, digest, dispatcher et sentinel ordering sont génériques et testés. Le writer PnL et le kill switch sont à rebrancher. | M | `daily_summary_queries.py`, `startup_notifier.py`, `heartbeat_scheduler.py` (wallets), `trader_events` |
| `dashboard/` | **ADAPTER (coque) / réécrire (contenu)** | Garder server, orchestrator, middleware, logs, health check, filtres Jinja, `base.html`/`macros.html`, page latence, tests sécurité. Réécrire environ 70 % de `queries.py` et des templates. | M-L | `queries.py` (173 refs), 11 pages |
| `remote_control/` | **GARDER tel quel** (optionnel) | 0 référence copy. Tailscale + TOTP + sentinel. | S | aucun |
| `cli/` | **GARDER / ADAPTER** | runner, logging, status screen, version. Retirer Watcher/Discovery de `boot.py`. | S | `boot.py:97-133`, `status_screen.py` |
| `config.py` | **ADAPTER** | Garder les sections creds, CLOB V2, pUSD, builder, mode, Telegram, dashboard, remote control, logs, machine id, WS, latence, fees. Retirer environ 50 %. | M | 29 validators croisés |
| `scripts/` | tri | GARDER `wrap_usdc_to_pusd.py`, `capture_clob_ws_fixture.py` (à transformer en enregistreur), `setup.sh`, `supervisor/`. ADAPTER `pnl_report.py`, `night_test_status.py`. JETER `score_backtest.py`, `backtest_scoring_v2.py`, `validate_ma_hypotheses.py`, `seed_m12_dev_curves.py`. | S | — |
| `tests/` | tri | Garder les tests sécurité/grep, Telegram, alert dispatcher, kill switch ordering, remote control, CLI, logging. Réécrire les tests executor/WS sur les nouveaux DTOs. Jeter environ 38 fichiers. | M | fixtures v1 camelCase |
| `docs/` | archiver | Les specs M8, M11, M16, M17, M18 restent de bonnes références (pièges API). `CLAUDE.md` est à réécrire. | S | — |

### 2.3 Fichier par fichier (modules clés)

**executor/**

| Fichier | Verdict | Détail |
|---|---|---|
| `clob_write_client.py` (133 l.) | **GARDER + étendre (M)** | Garder : refus d'instanciation hors live (`:41-51`), dérivation L1→L2 `create_or_derive_api_key` (`:65-95`), `BuilderConfig` optionnel, `to_thread` autour du SDK sync (`:114-119`), `PartialCreateOrderOptions` (`:107-110`). Ajouter `cancel`, `cancel_all`, cancel par marché, `get_order`, `get_open_orders`, `get_trades`, post-only, GTC/GTD, batch post, balance/allowance **(à vérifier : noms exacts dans `py-clob-client-v2==1.0.0`, non installé ici)**. Lever le `FIXME` (`:126`) : avec `OrderArgs` (ordre limite), `size` est en shares, alors que le commentaire de `BuiltOrder` (`executor/dtos.py:21-23`) et la spec M3 §6.4 disent « USD à dépenser pour un FOK BUY ». Évaluer `POLYMARKET_USE_SERVER_TIME=false` : d'après CLAUDE.md M18, le mode serveur ajoute 50-200 ms par signature. |
| `pipeline.py` (517 l.) | **RÉÉCRIRE (L)** | `order_type="FOK"` codé en dur à 3 endroits (`:106,168,207`, plus `:371`) ; limite = mid arrondi au tick le plus proche (`:97`, et `round()` Python fait un arrondi bancaire) ; garde-fou capital sur stub, appliqué aussi aux SELL (`:152-189`) ; `list_recent(limit=1)` pour retrouver l'id inséré (`:175-181`, race possible) ; statuts `live`/`delayed` → `SENT` sans suivi (`:296-306`). À récupérer : `_extract_fill` (`:51-74`, fixed-math 6 déc.), le double check (`:191-195`), le 4ᵉ garde-fou (`:404`). |
| `orchestrator.py` (244 l.) | **ADAPTER (M)** | Garder : `RuntimeError` au boot (`:56-63`), lazy init, auth fatal → alerte CRITICAL → `stop_event` (`:196-200,224-244`). Problème : la boucle consomme les ordres un par un (`:153-222`), donc ni concurrence ni cancel possible pendant un POST. |
| `fee_rate_client.py` (378 l.) | **GARDER + renommer (S)** | `GET /clob-markets/{cid}` : cache 60 s, LRU, single-flight, tenacity, fallback conservateur 1,8 %. La réponse V2 contient aussi `mts` (tick), `mos` (taille min), `nr` (neg_risk), `t` (tokens/outcomes), `cs` (statut), cf. `tests/fixtures/clob_v2_market_crypto_sample.json` (synthétique). Ce client peut devenir le `MarketInfoClient` unique et remplacer `/tick-size` et le lookup Gamma `neg_risk`. `fd.to=true` signifie taker-only : le maker ne paie pas de fee. |
| `clob_metadata_client.py` | **JETER** | Remplacé par `/clob-markets`. Cache de tick 5 min alors que l'événement WS `tick_size_change` est ignoré. |
| `clob_orderbook_reader.py` (153 l.) | **GARDER (S)** | `GET /book` REST : sert de snapshot de resync (champ `hash`). Le parse en `Decimal(str())` est propre (`:123-153`). |
| `realistic_fill.py` (104 l.) | **ADAPTER (M)** | Fonction pure testée (y compris par hypothesis). Il manque le prix limite, la taille min, les fees et la latence. À étendre en simulateur taker et à compléter par un simulateur maker séparé (voir §4). |
| `dry_run_resolution_watcher.py` | **ADAPTER (M)** | Polling Gamma toutes les 30 min (min 5), cassé jusqu'au 2026-05-22 (commit `371f8dc`). Pour des fenêtres de 5 min, il faut une résolution événementielle (WS `market_resolved` + confirmation Gamma). Il n'existe pas d'équivalent live (pas de redeem). |
| `virtual_wallet_reader.py` | **ADAPTER (S)** | Valorisation au **mid** (`:94-96`) : il faut valoriser au bid, c'est-à-dire en valeur de liquidation. À remplacer par un ledger cash et positions. |
| `wallet_state_reader.py` | **JETER / RÉÉCRIRE (M)** | Data API v1 `/positions` + capital stub. Le remplacer par la balance/allowance CLOB et le ledger interne. |
| `dtos.py`, `exceptions.py` | ADAPTER / GARDER | `OrderResult` (alias `orderID`, `makingAmount`, `takingAmount`, `transactionsHashes`, `tradeIDs`, `errorMsg`) est réutilisable. |

**strategy/**

| Fichier | Verdict | Détail |
|---|---|---|
| `clob_ws_client.py` (541 l.) | **ADAPTER lourdement (L)** | Voir §5 : garder connexion, ping 10 s, reconnect tenacity, watchdog et parse Pydantic ; réécrire l'état (book L2 par asset) et la diffusion (push vers la stratégie). |
| `gamma_client.py` (285 l.) | **GARDER + étendre (S)** | Le batch à paramètres répétés et `closed=true` (`:58-120`) sont des pièges déjà résolus. Ajouter la recherche par slug (`btc-updown-5m-<ts>`), `eventStartTime`, `orderMinSize`, `orderPriceMinTickSize` dans `MarketMetadata`. |
| `_cache_policy.py` | GARDER (S) | TTL adaptatif, 10 s près de la résolution. |
| `clob_read_client.py` | GARDER (S) | Fallback REST `/midpoint` ; le 404 n'est pas retenté (fix `effaa34`). |
| `pipeline.py` (483 l.) | **JETER** (récupérer des morceaux) | À récupérer : `_compute_effective_fee_rate` pur (`:296-323`), le pattern `FilterResult` + `filter_trace` pour l'audit, et le wrapper de timing par stage (`:462-482`). |
| `orchestrator.py` | **JETER** | Consomme des `DetectedTradeDTO`. |
| `dtos.py` | ADAPTER | Garder `MarketMetadata` (parse des strings JSON Gamma) ; remplacer `OrderApproved` par un `OrderIntent` (id interne, raison entry/TP/SL/time-stop, limite, TIF, post-only). |

**storage/** : `engine.py` GARDER + pragmas ; `init_db.py` ADAPTER ; `models.py` RÉÉCRIRE ; dans `repositories.py`, GARDER `PnlSnapshotRepository` (`:958-1052`) et `TradeLatencyRepository` (`:1191-1243`), RÉÉCRIRE `MyOrderRepository` et `MyPositionRepository`, JETER les quatre repositories traders ; `latency_purge_scheduler.py` GARDER ; `dtos.py` ADAPTER (`PnlSnapshotDTO` réutilisable).

**monitoring/** : GARDER `telegram_client.py`, `md_escape.py`, `alert_renderer.py` (badges de mode, machine id), `alert_digest.py`, `alert_dispatcher.py`, `dashboard_url.py`, `daily_summary_scheduler.py`, `heartbeat_scheduler.py` (requêtes à adapter). ADAPTER `pnl_writer.py` (garder l'ordre strict du kill switch, changer la source de données et la cadence, déplacer l'audit hors de `trader_events`), `orchestrator.py`, `startup_notifier.py`, `daily_summary_queries.py`. Templates : GARDER `kill_switch_triggered`, `executor_error`, `executor_auth_fatal`, `order_filled_large`, `pnl_snapshot_drawdown`, `heartbeat`, `startup`, `shutdown`, `digest`, `fallback`, `remote_control_brute_force_detected`, `daily_summary` (à adapter) ; JETER les 9 `trader_*`, les 2 `discovery_*` et `dry_run_market_resolved_neg_risk`.

**dashboard/** : GARDER `server.py`, `orchestrator.py`, `middleware.py` (filtre des logs bruyants), `log_reader.py`, `health_check.py` (corriger `DATA_API_URL`, `:24`), `jinja_filters.py`, `templates/base.html`, `macros.html`, `logs*.html`, `latency.html`, `pnl.html`, `tests/unit/test_dashboard_security*.py`. RÉÉCRIRE `queries.py` (garder `fetch_pnl_series`, `compute_latency_percentiles`, `get_pnl_milestones`, `parse_since`) et les pages `detections`, `strategy`, `traders`, `traders_scoring`, `performance`, `activity`, `backtest`.

### 2.4 Où l'intuition du propriétaire est fausse ou incomplète

| Intuition | Réalité | Conséquence |
|---|---|---|
| « Garder l'executor CLOB V2 + garde-fous » | Les **garde-fous** sont bons, mais l'executor **n'a jamais signé un ordre réel** et ne gère que du FOK synchrone. Limite au mid (`strategy/orchestrator.py:191`) avec FOK : un BUY à limite = mid sur un carnet avec spread est très probablement tué *(déduction depuis la sémantique limite+FOK, non testée en live)*. | Garder environ 130 lignes (`ClobWriteClient`) et le pattern de garde-fous ; l'OMS est entièrement à écrire. |
| « Garder le dry-run réaliste orderbook » | Pas de prix limite (`realistic_fill.py:45-70` consomme tout le book), pas de taille min (`orderMinSize=5`, aucune occurrence dans `src/`), pas de fees, pas de latence, book REST caché 5 s, valorisation au mid, bug de réouverture UNIQUE, PnL des SELL partiels perdu, résolution inopérante jusqu'au 2026-05-22. | Les résultats du dry-run polycopy (≈ −25 $ sur 1 000 $, voir annexe A) **ne disent rien** de la future stratégie. Le simulateur doit être refait, piloté par le flux WS L2, avec un modèle de file d'attente maker. |
| « Garder `ClobMarketWSClient` » | Il ne stocke qu'un **mid** par token et jette le book, les tailles, les timestamps et les hashes. `last_trade_price` est utilisé comme mid de secours. `tick_size_change` et `new_market` sont ignorés. Le fixture est synthétique. | Garder le transport (≈ 150 lignes), réécrire le modèle (L2, tape, séquence, resync) et le mode push. |
| « Garder `FeeRateClient` » | Correct, et c'est le module le plus réutilisable. Mais le calcul de fee n'est fait que côté BUY (SELL en passthrough, M16 D5), et `realized_pnl` n'inclut jamais les fees. | Fees sur les deux jambes, maker = 0 fee ; le PnL doit être net. |
| « Garder l'instrumentation latence » | Bonne base (`perf_counter_ns`, stages, page `/latency`), mais un `INSERT` + commit SQLite **awaité dans le chemin chaud** pour chaque stage (`strategy/pipeline.py:476-477`, `wallet_poller.py:126-131`, `executor/orchestrator.py:213-219`), `trade_id` non persisté ailleurs, et aucun timestamp exchange. | Garder le concept ; écritures asynchrones en batch, corrélation par `intent_id`/`order_id`, ajout du timestamp WS. |
| « Garder storage/Alembic » | La techno oui, le schéma et la chaîne non (voir 2.1). | Nouvelle baseline. |
| « Garder monitoring/Telegram/kill switch » | Telegram et l'ordre du kill switch : oui. Mais le kill switch est un **polling de drawdown toutes les 300 s** (`config.py:448-452`), alimenté en live par Data API v1 + stub (cassé). Pour des fenêtres de 5 min, c'est inadapté. | Garder le mécanisme d'arrêt ; ajouter un risk engine pré-trade synchrone et des déclencheurs événementiels (feed stale, déconnexion, perte de fenêtre, perte journalière, N pertes consécutives). |
| « Garder le dashboard » | La coque oui, le contenu est à environ 70 % copy-spécifique. | Effort M-L, pas S. |
| « Jeter discovery/scoring/eviction/watcher » | **Juste.** Seul point à noter : le flux global `/v2/trades` montre l'activité des concurrents sur les marchés up/down (8,8 % des trades ≥ 100 $ dans le fixture). Ça peut servir à l'analyse, pas au bot. | — |
| (non mentionné) | **Modules absents** : flux spot (BTC/ETH ; source de résolution à vérifier par marché via Gamma `resolutionSource`), scheduler de fenêtres (slug déterministe `btc-updown-5m-<start_ts>`, pré-souscription avant l'ouverture), channel `user` authentifié, OMS, position manager TP/SL/time-stop, ledger cash/pUSD + allowance, redeem/merge des positions résolues, enregistreur de données brutes (WS + spot) pour backtest, backtester (le mode `SIMULATION` est un stub). | C'est l'essentiel de l'effort du nouveau bot. |

---

## 3. Analyse « sorties actives »

### 3.1 Où le code suppose que SELL = copie d'un SELL source

| # | Endroit | Hypothèse codée | Effet pour un bot à sorties actives |
|---|---|---|---|
| 1 | `storage/dtos.py:9-39` `DetectedTradeDTO` (`tx_hash`, `target_wallet`, `size`, `price` source) | Toute décision naît d'un trade externe. | Il n'existe pas d'entrée pour une décision interne (TP, SL, time-stop). |
| 2 | `strategy/dtos.py:62-87` `OrderApproved` (`tx_hash`, `source_wallet_address`) + `my_orders.source_tx_hash NOT NULL` (`models.py:195`) | Chaque ordre référence un tx source. | Une sortie interne n'a pas de tx : il faut un `intent_id` interne. |
| 3 | `strategy/pipeline.py:325-345` `PositionSizer._check_sell` | Taille SELL = `source.size × copy_ratio`, plafonnée à la position ; rejet `sell_without_position`. | Taille de sortie fausse : souvent une sortie partielle qui laisse de la poussière. |
| 4 | `strategy/pipeline.py:41-81` `TraderLifecycleFilter` | Les SELL passent toujours (wind-down `sell_only`). | Sans objet. |
| 5 | `strategy/pipeline.py:91-109` `MarketFilter` appliqué **aussi aux SELL** | `expiry_too_close` si < `MIN_HOURS_TO_EXPIRY` (24 h par défaut, `config.py:146`), `liquidity_too_low`, `orderbook_disabled`. | Une sortie copiée est **bloquée dans les dernières 24 h** d'un marché, et tout marché 5m/15m/1h est rejeté à l'entrée. Requête Q5c §7. |
| 6 | `strategy/pipeline.py:130-152` `EntryPriceFilter` | SELL en passthrough. | — |
| 7 | `strategy/pipeline.py:348-384` `SlippageChecker` appliqué aux SELL | Rejet si \|mid − prix source\|/prix source > 2 %. | Un stop-loss est bloqué précisément quand le marché bouge. |
| 8 | `strategy/pipeline.py:398-417` `RiskManager` appliqué aux SELL | `current_exposure + my_size × mid > stub` → `capital_exceeded`. | Une sortie peut être refusée faute de « capital ». |
| 9 | `strategy/pipeline.py:192-201` `_check_buy` | Refuse tout BUY si une position est ouverte sur le `condition_id`. | Pas de scale-in, pas de pyramide, pas de couverture Up+Down. |
| 10 | `strategy/pipeline.py:186-275` fees | Fee calculée seulement sur BUY, au prix **source** et sur la taille avant multiplicateur de probation. | Le coût des sorties est ignoré. |
| 11 | `executor/pipeline.py:97,99-107` | Limite = mid arrondi au plus proche, FOK, pour les deux sens. | Pas de limite agressive (bid pour un SELL, ask pour un BUY), pas d'option maker. |
| 12 | `executor/pipeline.py:152-189` | Garde-fou capital live appliqué aux SELL. | Une sortie live peut être refusée. |
| 13 | `storage/repositories.py:643-705` `upsert_on_fill` (live) | Un SELL réduit `size` et ferme la position, **sans jamais calculer `realized_pnl`** ; `ValueError` si aucune position. | En live, le PnL réalisé est toujours NULL : le kill switch et l'internal_pnl sont aveugles. |
| 14 | `storage/repositories.py:734-802` `upsert_virtual` | `realized_pnl` posé seulement quand `size ≤ 0`, et sur `min(size_filled, size_before)` de la **dernière** vente. Un SELL sans position → `None` puis warning `dry_run_sell_without_position` (`executor/pipeline.py:475-481`). | Le PnL des ventes partielles est **perdu**. Après clôture par SELL, `size=0` : on ne peut plus reconstituer la taille d'origine sans `my_orders`. |
| 15 | `models.py:268-274` UNIQUE(`condition_id`, `asset_id`, `simulated`) incluant les lignes fermées | Une position par token, pour toujours. | **Ré-entrée impossible** : le BUY passe `_check_buy` (qui ne regarde que les positions ouvertes), l'ordre est inséré, puis `upsert_virtual` lève `IntegrityError` (reproduit sur un schéma SQLite reconstruit) → `executor_loop_error` → ordre SIMULATED orphelin. Requête Q9c §7. |
| 16 | `models.py:259-266` `source_wallet_address` + index composite | PnL attribué à un wallet. | À remplacer par `strategy_id`/`window_id`. |
| 17 | `executor/dry_run_resolution_watcher.py:73-121` | Les positions non vendues attendent la résolution, par polling Gamma toutes les 30 min. | Pas de time-stop. Une position 5 min reste ouverte jusqu'à 30 min, puis se résout à 0 ou 1. |
| 18 | `monitoring/pnl_writer.py:122-130` + `virtual_wallet_reader.py:94-96` | PnL latent au mid. | Surestime la valeur de liquidation (le spread n'est pas compté). |

### 3.2 Ce qui manque

**(a) Gestionnaire de positions TP / SL / time-stop.** Rien n'existe. Il faut :
- un état en mémoire par position (lots, prix moyen, fees payées, `opened_at`, `window_end`, niveaux TP/SL), réévalué à **chaque tick** du book du token. Le déclencheur est le best bid pour une position longue (c'est le prix de sortie), pas le mid.
- un time-stop relatif à `window_end` (`endDate` Gamma), avec une marge réglable pour sortir avant les dernières secondes où la liquidité disparaît.
- une politique de sortie : limite marchable FAK/FOK au bid moins N ticks, ou bien sortie passive maker et escalade vers le taker si non remplie après T ms.
- un PnL réalisé **par fill** (FIFO ou prix moyen), net de fees, sur une table `fills`, et pas une valeur unique `realized_pnl` sur la position.
- le cas des fenêtres terminées : redeem on-chain si la position est gagnante, ou acceptation de la perte. Aucun code de redeem n'existe (grep `redeem` : uniquement l'enum `watcher/dtos.py:16`).

**(b) GTC, annulation, fills partiels, channel `user`.**
- Le code n'émet **que du FOK** : `BuiltOrder.order_type` accepte `FOK|FAK|GTC` (`executor/dtos.py:27`), mais la valeur est codée en dur à `"FOK"` (`executor/pipeline.py:106,168,207,371`).
- **Aucun** `cancel` n'existe dans `src/` (grep). **Aucun** client `wss://…/ws/user` : seule l'URL `ws/market` est configurée (`config.py:658-661`). La spec M3 range explicitement le channel `user` hors scope (« create_and_post_order retourne déjà le résultat de fill pour FOK », `docs/specs/M3-executor.md:872`).
- Confirmation des fills : uniquement la réponse synchrone du POST (`status ∈ matched|live|delayed`, `executor/pipeline.py:257-306`). `live`/`delayed` → `SENT` sans aucun suivi, réconciliation ni timeout. `PARTIALLY_FILLED` existe dans le commentaire de l'enum (`models.py:205`) mais n'est jamais posé.
- À construire : client `user` authentifié (creds L2 ; abonnement **par condition_id** et non par wallet, cf. `docs/deepsearch/SYNTHESIS-…md:52`) consommant les événements `order` (placement/update/cancel) et `trade` (matched/mined/confirmed/failed) **(à vérifier : schéma exact)** ; état d'ordre machine-à-états (NEW → OPEN → PARTIAL → FILLED/CANCELED/EXPIRED/REJECTED) ; réconciliation REST au boot et après une reconnexion ; cancel-all au kill switch et sur feed stale ; idempotence (client order id / nonce).

**(c) Maker (post-only / GTC limit) vs taker FOK.**
- Taker : fee `fd.r × (p(1−p))^fd.e` sur le notionnel (`strategy/pipeline.py:296-323`). Exemple crypto V2 observé : `r=0.072, e=1` → 1,80 % à p=0,5 et 1,15 % à p=0,2. Un aller-retour taker coûte 2 à 3,6 % du notionnel. C'est acceptable pour un scalp 20¢→60¢, mais rédhibitoire pour un scalp de quelques ticks.
- Maker : `fd.to=true` signifie taker-only, donc 0 fee pour le maker, avec des rebates possibles. Pour s'en servir, il faut des ordres GTC/GTD, un flag post-only **(à vérifier dans le SDK V2 1.0.0)**, une boucle cancel/replace, la gestion des changements de tick (`tick_size_change`, ignoré aujourd'hui `clob_ws_client.py:365` ; le tick passe à 0,001 aux extrêmes, et le daily crypto du fixture a déjà `orderPriceMinTickSize=0.001`), le respect de `orderMinSize` (5 shares) et une estimation de la file d'attente.
- Risque spécifique aux fenêtres up/down : la sélection adverse (un ordre maker est rempli exactement quand le spot traverse le strike), qui s'accentue en fin de fenêtre.

**(d) Boucle de décision déclenchée par les ticks (< 200 ms).** L'architecture actuelle est à l'opposé :
- Le modèle est **pull** : la stratégie lit le mid dans le cache WS quand un trade source arrive (`pipeline.py:370-374`). Aucun callback sur tick.
- Il y a de l'I/O DB synchrone dans le chemin critique : 1 requête lifecycle, 1 requête positions dans le sizer, 1 requête listant **toutes** les positions ouvertes dans le risk manager (`pipeline.py:406-412`), 4 à 6 INSERT de latence, 1 INSERT de décision avec un JSON qui inclut le dump Gamma complet (`strategy/dtos.py:144-148`), puis côté executor 1 GET `/tick-size`, 1 Gamma, 1 GET `/book` et 2 à 3 commits.
- Mesures existantes : `executor_submitted_ms` p50 = 635 ms en dry-run (`docs/backlog.md`, section « Latence watcher »), `strategy_sized_ms` p50 = 2,7 ms.
- Ce qu'il faut à la place : un état en mémoire (books, positions, ordres, risque) et une persistance write-behind (une queue et un writer unique) ; un fan-out WS → stratégie par marché (une task par fenêtre active) ; des métadonnées marché préchargées avant l'ouverture de la fenêtre ; une signature hors thread (le SDK est synchrone, `to_thread`) avec un client HTTP keep-alive ; pas de `use_server_time` dans le chemin chaud ; une horloge NTP ; un budget de latence mesuré de bout en bout (§6).

---

## 4. Executor en détail

| Sujet | État actuel | Réf. |
|---|---|---|
| Types d'ordres | **FOK uniquement**, via `OrderArgs` (ordre limite) + `create_and_post_order(args, PartialCreateOrderOptions(tick_size, neg_risk), OrderType.FOK)`. `MarketOrderArgs` n'est jamais utilisé. | `executor/pipeline.py:99-107`, `clob_write_client.py:97-133` |
| Prix | `my_price = ctx.midpoint` (mid WS ou `/midpoint`), puis `round(price / tick) × tick` (arrondi au plus proche, bancaire). | `strategy/orchestrator.py:191`, `executor/pipeline.py:44-48,97` |
| Taille | Shares (`PositionSizer` : `source.size × copy_ratio` plafonné à `max_position_usd / source_price`). Le commentaire et la spec disent « USD pour FOK BUY » (incohérence, `FIXME`). | `strategy/pipeline.py:202-206`, `executor/dtos.py:21-23`, `clob_write_client.py:126` |
| tick_size | `GET /tick-size?token_id=` (cache 5 min), parse `minimum_tick_size`. | `executor/clob_metadata_client.py:53-81` |
| neg_risk | `GammaApiClient.get_market(condition_id).neg_risk` (cache adaptatif) ; défaut `False` si marché introuvable. | `executor/pipeline.py:95-96` |
| Min order size | **Non vérifiée** (aucune occurrence de `orderMinSize` / `min_order` dans `src/`). | — |
| Capital | Live : exposition = Σ `currentValue` Data API `/positions` (cache 30 s) ; capital = stub constant. Non-live : stub. | `executor/wallet_state_reader.py:42-89` |
| Confirmation des fills | Réponse synchrone du POST : `matched` → `_extract_fill(making, taking)` (BUY : maker = USDC, taker = shares ; SELL : l'inverse) → `FILLED` + `upsert_on_fill` ; `live`/`delayed` → `SENT` sans suivi ; `success=false` → `REJECTED` (auth → `ExecutorAuthError` → stop). | `executor/pipeline.py:232-306` |
| Erreurs | Exception SDK → `FAILED` + alerte `executor_error` (cooldown 60 s). Pas de retry, pas de gestion HTTP 425 (redémarrage du matching engine, cité dans `docs/next/MK.md`). | `executor/pipeline.py:212-218` |
| Persistance positions | Live : `upsert_on_fill` (moyenne pondérée sur BUY ; décrément sur SELL ; pas de realized). Dry-run : `upsert_virtual`. | `storage/repositories.py:643-802` |
| realized_pnl | Dry-run : clôture complète par SELL `= min(sold, held) × (fill − avg)` (`:786-799`) ou résolution `(payout − avg) × size` (`dry_run_resolution_watcher.py:107-113`). Live : jamais. Les fees ne sont jamais déduites. | — |
| Concurrence | Une coroutine consomme la queue en série ; un POST bloque les suivants. | `executor/orchestrator.py:153-222` |

**Ce que fait le dry-run réaliste (M8)** :
1. `GET /book?token_id=` (REST, cache TTL 5 s et LRU 500 ; `clob_orderbook_reader.py:69-87`), appelé **après** la récupération du tick et de Gamma, donc quelques centaines de ms après la décision. Ce délai n'est pas modélisé, il est simplement subi.
2. `simulate_fill` (`realistic_fill.py:25-104`) : trie les asks (BUY) ou les bids (SELL) et consomme niveau par niveau jusqu'à `my_size`, **sans borne de prix** (pas de limite). FOK strict par défaut : book insuffisant → `REJECTED insufficient_liquidity` ; `DRY_RUN_ALLOW_PARTIAL_BOOK=true` → partiel. Calculs en `Decimal`, persistance en `float`.
3. Persiste `my_orders` (`realistic_fill=1`, `price` = prix moyen) puis `upsert_virtual`.
4. Ce qu'il ne fait pas : fees, taille min, validation du tick, latence simulée (aucun délai artificiel), impact sur le book (le même niveau peut être « consommé » deux fois en 5 s), file maker, GTC/GTD, annulations.

**Ce qui manque pour simuler des fills maker** :
- un flux L2 incrémental et horodaté (WS `book` + `price_change`), plus la **tape** des trades (`last_trade_price` : prix, taille, side) ;
- un état « ordre reposant » par ordre simulé (prix, taille restante, heure d'arrivée, latence de placement et d'annulation) ;
- un **modèle de file d'attente** : quantité devant soi au niveau au moment du placement, décrémentée par les trades au niveau et, en hypothèse prudente, par une fraction des annulations (le `price_change` ne distingue pas un trade d'une annulation : à croiser avec la tape) ;
- un fill déclenché par les trades qui atteignent ou traversent le niveau ; des fills partiels ;
- le rejet post-only si l'ordre croise ; la gestion du changement de tick et de la taille min ;
- des fees maker = 0 et une option de rebates, des fees taker sur l'autre jambe ;
- une mesure de la sélection adverse (mouvement du mid ou du spot N secondes après le fill) ;
- un replay déterministe depuis les données enregistrées, pour faire du vrai backtest (le mode `SIMULATION` n'existe pas).

---

## 5. `ClobMarketWSClient` (`src/polycopy/strategy/clob_ws_client.py`)

| Aspect | Implémentation | Réf. |
|---|---|---|
| Connexion | `websockets.connect(url, ping_interval=10, ping_timeout=20, max_size=1 MiB)`, une seule connexion, retry tenacity 10× (OSError, handshake, timeout) | `:298-319` |
| Messages gérés | `book` → mid (best bid/ask calculés en itérant les niveaux) ; `price_change` → mid depuis `best_bid`/`best_ask` de chaque entrée ; `best_bid_ask` → mid ; `last_trade_price` → **utilisé comme mid** seulement si le token n'est pas encore en cache ; `market_resolved` → purge cache + subs. **Ignorés** : `tick_size_change`, `new_market` (`:365`). Texte `PING`/`PONG` ignoré. | `:337-417` |
| État stocké | `dict[token_id → (mid_price: float, last_update_ts: datetime locale)]`. Les niveaux du book, les tailles, le spread, le timestamp exchange (`timestamp` du message), le `hash` et la tape sont **jetés**. | `:151-156,419-423` |
| Fraîcheur | `get_mid_price` renvoie `None` si âge > 60 s (`_CACHE_STALE_SECONDS`), puis fallback HTTP. | `:58,256-268` |
| Sub/unsub | Sub paresseux par token au premier usage (`SlippageChecker`) : envoie `{"type":"market","assets_ids":[…],"custom_feature_enabled":true}` **à chaque nouveau token**. Unsub `{"assets_ids":[…],"operation":"unsubscribe"}`. Re-sub de tout l'ensemble après reconnexion. **(À vérifier : Polymarket documente `operation: "subscribe"` pour les ajouts dynamiques ; la deep-search cite NautilusTrader « no unsubscribe » et une limite d'environ 500 instruments par connexion.)** | `:237-254,427-455` |
| Anti-fuite | LRU dur `STRATEGY_CLOB_WS_MAX_SUBSCRIBED=500` ; GC des tokens inactifs depuis plus de 300 s (boucle de 30 s). Race LRU connue (audit H-015). | `:457-490` |
| Santé | Watchdog : si aucun message depuis 2 × 30 s → close + reconnect (double déclenchement possible, M-017) ; statut `up/reconnecting/down` loggé. | `:492-524` |
| Diffusion | **Aucune** : pas de callback ni de queue. Le cache est consulté à la demande. | — |
| Tests | `tests/unit/test_clob_ws_client.py` sur un fixture **synthétique** (`tests/fixtures/clob_ws_market_sample.jsonl`). | — |

**Manques pour un bot de scalping** :
1. **Book L2 complet par token** : snapshot `book`, puis application des deltas `price_change` (`price`, `size` = nouvelle taille au niveau, `side`), stocké en `Decimal`. Exposer best bid/ask, la profondeur cumulée jusqu'à un prix, et le spread.
2. **Intégrité** : comparer le `hash` du message ou du book REST et resynchroniser via `GET /book` (`ClobOrderbookReader`) en cas de divergence ou après reconnexion. Il n'y a pas de numéro de séquence documenté, d'où la dépendance au hash **(à vérifier)**.
3. **Horodatage double** : timestamp exchange (ms, champ `timestamp`) et `time.monotonic_ns()` local à la réception. C'est la base de la mesure de latence du feed et du replay.
4. **Tape** : conserver chaque `last_trade_price` (prix, taille, side, `fee_rate_bps`), nécessaire pour le modèle de file maker et pour le momentum.
5. **`tick_size_change`** à appliquer, **`new_market`** à exploiter (création des fenêtres up/down).
6. **Push** : diffusion par token vers les stratégies abonnées, en coalesçant les deltas si le consommateur est lent ; métriques de lag.
7. **Abonnement planifié** : s'abonner aux deux tokens Up/Down de la fenêtre N+1 avant son ouverture, désabonner après la résolution. Plusieurs connexions si on dépasse la limite par connexion.
8. **Channel `user` séparé**, authentifié, pour les ordres et fills propres (§3.2 b).
9. **Enregistreur brut** (JSONL ou Parquet par jour) de tous les messages, pour le backtest. `scripts/capture_clob_ws_fixture.py` en est l'embryon.
10. **Flux spot externe** (BTC/ETH) avec la même rigueur d'horodatage. La source de référence de résolution doit être vérifiée par marché ; le daily du fixture pointe vers Binance BTC_USDT.

---

## 6. Instrumentation latence M11 : réutilisable pour tick → décision → ordre ?

**Ce qui existe** : `trade_id` uuid généré par `WalletPoller` (`wallet_poller.py:105`), propagé dans les DTOs et bindé en contextvar ; `time.perf_counter_ns` autour de chaque filtre (`strategy/pipeline.py:462-482`), autour de `run_pipeline` (`strategy/orchestrator.py:147-173`) et autour de `execute_order` (`executor/orchestrator.py:182-219`) ; table `trade_latency_samples` ; purge 7 j (boot + quotidienne) ; dashboard `/latency` p50/p95/p99 par stage (`dashboard/queries.py:1270-1322`) ; flag `LATENCY_INSTRUMENTATION_ENABLED`.

**Verdict : le concept est réutilisable, l'implémentation est à refaire (effort M).**

| Problème | Réf. | Correction |
|---|---|---|
| `INSERT` + commit SQLite **awaités dans le chemin chaud**, un par stage | `pipeline.py:476-477`, `wallet_poller.py:126-131`, `executor/orchestrator.py:213-219` | buffer en mémoire, flush en batch par une task de fond ; ou histogrammes en mémoire (HDR) avec un snapshot périodique |
| `trade_id` non persisté dans `detected_trades`, `strategy_decisions` ni `my_orders` | `models.py:140-224` | `intent_id` / `order_id` / `client_order_id` présents dans toutes les tables |
| Stages codés en dur, métrique `watcher_detected_ms` qui mélange temps réel et backfill, `strategy_filtered_ms` émis aussi sur rejet précoce (H-001) | `dashboard/queries.py:1270-1277`, `docs/backlog.md` | nouveaux stages : `ws_exchange_to_recv`, `recv_to_book_applied`, `book_to_signal`, `signal_to_intent`, `intent_to_signed`, `signed_to_post_ack`, `post_ack_to_user_ws_fill`, `cancel_to_ack` |
| Mesure uniquement intra-process, pas de temps exchange | — | timestamp WS du message, `matchtime` du fill **(à vérifier)**, NTP |
| Temps d'attente en queue non mesuré | `executor/orchestrator.py:167-170` | horodater l'enqueue et le dequeue |
| Purge à 7 j | `config.py:696-704` | plus long, ou agrégats journaliers persistés |

---

## 7. Requêtes SQL de post-mortem du dry-run polycopy (SQLite)

**Où est la DB ?**
- Défaut code : `DATABASE_URL=sqlite+aiosqlite:///polycopy.db` (`src/polycopy/config.py:353`, `.env.example:66`). C'est un chemin **relatif au répertoire courant au lancement**, donc en pratique `<repo>/polycopy.db` si le bot est lancé depuis la racine.
- Machine prod du propriétaire : toutes les commandes de `docs/todo.md` (par ex. `:303`, `:443`, `:625`) utilisent `~/.polycopy/data/polycopy.db`, ce qui suppose un `DATABASE_URL` surchargé dans le `.env` local. Vérifier avec `grep DATABASE_URL .env`.

**Mode opératoire conseillé** (le bot peut tourner, la DB n'a pas de WAL) :
```bash
cp ~/.polycopy/data/polycopy.db /tmp/pm.db      # copie à froid
sqlite3 -readonly /tmp/pm.db
.headers on
.mode column
```
Prérequis : SQLite ≥ 3.38 (`json_extract` intégré, fonctions fenêtre). Les dates sont stockées par SQLAlchemy en texte naïf UTC `YYYY-MM-DD HH:MM:SS.ffffff`, donc `julianday()` fonctionne. Les booléens valent 0/1.

**Pièges de schéma à connaître avant d'interpréter les résultats** :
- `strategy_decisions.detected_trade_id` vaut toujours 0 : joindre par `tx_hash`. `my_orders.source_tx_hash` correspond à `detected_trades.tx_hash` et à `strategy_decisions.tx_hash`.
- Une position fermée **par SELL copié** garde `size = 0` (la taille est décrémentée), alors qu'une position fermée **par résolution** garde sa taille. C'est le critère utilisé ci-dessous pour distinguer les deux cas.
- `realized_pnl` ignore les fees et le PnL des SELL partiels (seule la dernière tranche compte).
- La résolution M8 n'a **jamais fonctionné avant le commit `371f8dc` du 2026-05-22** : avant cette date, toutes les clôtures viennent de SELL copiés (111 positions d'après le message de commit).
- `trade_latency_samples` est purgée à 7 jours et ne se joint à rien.
- Les positions orphelines dues à la contrainte UNIQUE de réouverture apparaissent comme des BUY `SIMULATED` sans position correspondante (Q9c).

### Q0 — Inventaire

```sql
-- Q0a : volumes et bornes temporelles par table
SELECT 'detected_trades' AS tbl, COUNT(*) AS n, MIN(timestamp) AS first_at, MAX(timestamp) AS last_at FROM detected_trades
UNION ALL SELECT 'strategy_decisions', COUNT(*), MIN(decided_at), MAX(decided_at) FROM strategy_decisions
UNION ALL SELECT 'my_orders', COUNT(*), MIN(sent_at), MAX(sent_at) FROM my_orders
UNION ALL SELECT 'my_positions', COUNT(*), MIN(opened_at), MAX(COALESCE(closed_at, opened_at)) FROM my_positions
UNION ALL SELECT 'pnl_snapshots', COUNT(*), MIN(timestamp), MAX(timestamp) FROM pnl_snapshots
UNION ALL SELECT 'trade_latency_samples', COUNT(*), MIN(timestamp), MAX(timestamp) FROM trade_latency_samples
UNION ALL SELECT 'target_traders', COUNT(*), MIN(added_at), MAX(added_at) FROM target_traders
UNION ALL SELECT 'trader_scores', COUNT(*), MIN(cycle_at), MAX(cycle_at) FROM trader_scores
UNION ALL SELECT 'trader_events', COUNT(*), MIN(at), MAX(at) FROM trader_events;

-- Q0b : révision Alembic (attendu : 0010_m17_pnl_snapshot_execution_mode)
SELECT version_num FROM alembic_version;

-- Q0c : modes présents dans les snapshots
SELECT execution_mode, is_dry_run, COUNT(*) AS n FROM pnl_snapshots GROUP BY 1, 2;

-- Q0d : répartition des ordres
SELECT simulated, realistic_fill, side, status, COUNT(*) AS n
FROM my_orders GROUP BY 1, 2, 3, 4 ORDER BY n DESC;
```

### Q1 — PnL réalisé total, win rate, profit factor (par mode de clôture)

```sql
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
```
Win rate : les break-even sont exclus du dénominateur, comme dans la convention M19.

### Q2 — PnL et win rate par wallet source

```sql
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
```
Les positions antérieures à M15 (migration 0009) ont `source_wallet_address = NULL`.

### Q3 — Distribution des durées de détention

```sql
-- Q3a : buckets
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

-- Q3b : médiane et p90 (heures)
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
```
Pour une clôture par résolution, `closed_at` correspond à l'heure du cycle de résolution, pas à l'heure de résolution du marché. Toutes les positions résolues avant le 2026-05-22 ont été fermées en bloc ce jour-là, d'où des durées artificiellement longues.

### Q4 — Slippage réalisé vs mid à la décision et vs prix source

```sql
-- Q4a : coût moyen (bps) ; positif = moins bon que la référence
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

-- Q4b : distribution
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
```
`my_orders.price` est le prix moyen du fill simulé, sans limite de prix ; `d.my_price` est le mid au moment de la décision. L'écart mesure donc demi-spread + profondeur + dérive pendant environ 0,1 à 1 s. En live, le FOK limité au mid aurait été tué au lieu d'être rempli.

### Q5 — Rejets pipeline par raison

```sql
-- Q5a : stratégie
SELECT d.decision, COALESCE(d.reason, '-') AS reason, t.side, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_all
FROM strategy_decisions d
LEFT JOIN detected_trades t ON t.tx_hash = d.tx_hash
GROUP BY 1, 2, 3 ORDER BY n DESC;

-- Q5b : executor (REJECTED = book vide ou insuffisant en FOK)
SELECT side, status, COALESCE(error_msg, '-') AS error_msg, COUNT(*) AS n
FROM my_orders WHERE simulated = 1
GROUP BY 1, 2, 3 ORDER BY n DESC;

-- Q5c : SELL source rejetés alors qu'on détenait la position (sorties bloquées)
SELECT d.reason, COUNT(*) AS n_sell_blocked_while_holding
FROM strategy_decisions d
JOIN detected_trades t ON t.tx_hash = d.tx_hash AND t.side = 'SELL'
WHERE d.decision = 'REJECTED'
  AND EXISTS (
    SELECT 1 FROM my_positions p
    WHERE p.simulated = 1 AND p.condition_id = t.condition_id AND p.asset_id = t.asset_id
      AND p.opened_at <= d.decided_at AND (p.closed_at IS NULL OR p.closed_at > d.decided_at))
GROUP BY d.reason ORDER BY n_sell_blocked_while_holding DESC;
```
Raisons possibles : `wallet_sell_only`, `wallet_blacklisted`, `market_not_found`, `market_inactive`, `market_closed`, `orderbook_disabled`, `liquidity_too_low`, `expiry_too_close`, `entry_price_too_high`, `position_already_open`, `size_zero`, `ev_negative_after_fees`, `sell_without_position`, `no_orderbook`, `invalid_source_price`, `slippage_exceeded`, `risk_inputs_missing`, `capital_exceeded`, `pipeline_error`.

### Q6 — Latence par stage

```sql
-- Q6a : p50 / p95 / p99 par stage (nearest-rank)
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

-- Q6b : bout en bout par trade soumis (hors temps d'attente en queue, non mesurés)
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
```
`strategy_filtered_ms` contient déjà enriched, sized et risk_checked : ne pas les additionner. `watcher_detected_ms` = temps écoulé depuis le timestamp on-chain, backfills inclus (p99 aberrant).

### Q7 — Fees (enregistrées côté BUY, estimées côté SELL)

```sql
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
```
- `fee_cost_usd` est calculée au prix **source**, sur la taille **avant** probation (`strategy/pipeline.py:239-252`). `fee_buy_on_fill_usd` réapplique le taux effectif au notionnel réellement rempli, ce qui est plus juste.
- Côté SELL, rien n'est enregistré (M16 D5). L'estimation utilise `r=0.072, e=1` pour la crypto (valeur observée le 2026-04-27 selon M18) et `r=0.03, e=1` pour le sport (hypothèse M16, **à vérifier**).
- **PnL net ≈ Q1.realized − Σ(fee_buy_on_fill + fee_sell_estimated)**.

### Q8 — PnL par catégorie / type de marché (dont crypto up/down)

```sql
-- Q8a : PnL par catégorie
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

-- Q8b : entonnoir des trades source sur marchés up/down (attendu : expiry_too_close dominant)
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
```
Les motifs de slug sont confirmés par le fixture réel `tests/fixtures/data_api_trades_global_sample.json` : `btc|eth|xrp-updown-5m-<unix_ts>` et `…-15m-<ts>`. Les marchés horaires et daily ont un slug `bitcoin-up-or-down-…` (cf. `gamma_market_crypto_fees_sample.json`). La classification sport/politique est heuristique. Avec `MIN_HOURS_TO_EXPIRY=24`, presque aucun trade up/down n'a pu être copié.

### Q9 — Positions jamais fermées et orphelines

```sql
-- Q9a : détail des positions ouvertes (END_PASSED = la fenêtre est terminée mais la position n'est pas résolue)
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

-- Q9b : agrégat
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

-- Q9c : BUY remplis après la clôture de la position sur le même token
--       (réouverture bloquée par la contrainte UNIQUE → ordre sans position)
SELECT o.id AS order_id, o.condition_id, o.asset_id, o.size, o.price, o.sent_at,
       p.id AS pos_id, p.closed_at AS pos_closed_at
FROM my_orders o
JOIN my_positions p ON p.condition_id = o.condition_id AND p.asset_id = o.asset_id AND p.simulated = 1
WHERE o.simulated = 1 AND o.realistic_fill = 1 AND o.status = 'SIMULATED' AND o.side = 'BUY'
  AND p.closed_at IS NOT NULL AND o.sent_at > p.closed_at
ORDER BY o.sent_at;
```
Pour confirmer Q9c côté logs : `grep -c 'UNIQUE constraint failed: my_positions' ~/.polycopy/logs/polycopy.log*` (l'erreur est loggée par `executor_loop_error`).

### Q10 — Écart prix détecté vs prix d'exécution, et délais

```sql
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
```

### Q11 — Trades par wallet

```sql
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
```

### Q12 — Turnover des wallets (promotions / démotions)

```sql
-- Q12a : événements par type
SELECT event_type, COUNT(*) AS n, COUNT(DISTINCT wallet_address) AS n_wallets
FROM trader_events GROUP BY 1 ORDER BY n DESC;

-- Q12b : état final du pool
SELECT status, is_probation, COUNT(*) AS n FROM target_traders GROUP BY 1, 2;

-- Q12c : périodes ACTIVE par wallet (transitions uniquement)
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

-- Q12d : turnover quotidien
SELECT date(at) AS day,
  SUM(event_type LIKE 'promoted%') AS promotions,
  SUM(event_type LIKE 'demoted%' OR event_type IN ('eviction_completed_to_shadow', 'auto_blacklisted', 'blacklisted')) AS exits,
  SUM(event_type = 'discovered') AS discovered,
  SUM(event_type = 'gate_rejected') AS gate_rejected
FROM trader_events GROUP BY 1 ORDER BY 1;
```

### Q13 — Drawdown et courbe de capital

```sql
-- Q13a : synthèse
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

-- Q13b : par jour
SELECT date(timestamp) AS day, COUNT(*) AS n,
  ROUND(MIN(total_usdc), 2) AS min_total, ROUND(MAX(total_usdc), 2) AS max_total,
  ROUND(MAX(drawdown_pct), 2) AS max_dd_pct, ROUND(MAX(realized_pnl), 2) AS realized_cum,
  MAX(open_positions_count) AS max_open
FROM pnl_snapshots WHERE execution_mode = 'dry_run' GROUP BY 1 ORDER BY 1;

-- Q13c : trous dans la série (> 30 min ; le gel de 11 jours corrigé par effaa34 doit apparaître)
WITH g AS (
  SELECT timestamp, total_usdc, LAG(timestamp) OVER (ORDER BY timestamp) AS prev_ts
  FROM pnl_snapshots WHERE execution_mode = 'dry_run'
)
SELECT prev_ts, timestamp, ROUND((julianday(timestamp) - julianday(prev_ts)) * 24, 2) AS gap_h
FROM g WHERE (julianday(timestamp) - julianday(prev_ts)) * 24 > 0.5
ORDER BY gap_h DESC LIMIT 20;

-- Q13d : déclenchements du kill switch
SELECT at, json_extract(event_metadata, '$.drawdown_pct') AS dd_pct,
       json_extract(event_metadata, '$.total_usdc') AS total, json_extract(event_metadata, '$.execution_mode') AS mode
FROM trader_events WHERE event_type = 'kill_switch' ORDER BY at;
```
`realized_pnl` des snapshots n'est rempli que depuis M17 (MD.6) ; avant, il vaut 0. Le total est valorisé au mid.

---

## 8. Dettes et bugs connus qui impacteraient le nouveau bot

Légende impact : 🔴 bloquant si le code est réutilisé tel quel, 🟠 important, 🟡 mineur. La colonne « Source » indique d'où vient le constat : **NOUVEAU** = constaté dans cet audit.

| # | Dette / bug | Source | Réf. | Impact nouveau bot |
|---|---|---|---|---|
| 1 | Data API v1 retirée (HTTP 410). Tenacity retente aussi les 410 (5 essais pour le watcher et le wallet reader, 4 pour la discovery), d'où des boucles d'erreur. | constat du 2026-11-05 + NOUVEAU (retry) | §9 | 🔴 tout ce qui lit la Data API |
| 2 | **Réouverture impossible** : UNIQUE(`condition_id`, `asset_id`, `simulated`) non partielle → `IntegrityError` au 2ᵉ BUY sur le même token après clôture, et ordre orphelin | NOUVEAU (l'audit M-004 ne parlait que de concurrence) | `models.py:268-274`, `0004_m8_dry_run_realistic.py:56-60`, `repositories.py:770-781` | 🔴 le scalping ré-entre en permanence |
| 3 | `realized_pnl` live jamais calculé (`upsert_on_fill` ne traite que la taille) | NOUVEAU | `repositories.py:699-702` | 🔴 PnL et kill switch live aveugles |
| 4 | PnL des SELL partiels perdu (seule la dernière tranche compte) ; aucune table de fills | documenté « v1 » dans le code | `repositories.py:786-799` | 🔴 les TP/SL partiels faussent le PnL |
| 5 | Fees jamais déduites du `realized_pnl` ; SELL en passthrough fee (M16 D5) | M16 | `pipeline.py:325-345` | 🟠 PnL surestimé de 2 à 3,6 % du notionnel par aller-retour taker crypto |
| 6 | Limite = mid avec FOK (non marchable si spread > 0) ; arrondi au plus proche | NOUVEAU (déduction, jamais testé en live) | `strategy/orchestrator.py:191`, `executor/pipeline.py:44-48,97` | 🔴 en live, les entrées et sorties seraient tuées |
| 7 | Sémantique `size` non tranchée (`FIXME`) ; jamais testé en live | M3 §17 | `clob_write_client.py:126`, `executor/dtos.py:21-23` | 🔴 à valider sur un ordre de 1 $ |
| 8 | Garde-fou capital : stub constant + exposition via Data API v1 ; appliqué aussi aux SELL | NOUVEAU (partiel M3) | `wallet_state_reader.py:42-89`, `executor/pipeline.py:152-189` | 🔴 aucune vérification de la balance pUSD réelle |
| 9 | Pas de `orderMinSize` (5 shares) ni de validation du tick au placement ; `tick_size_change` WS ignoré | NOUVEAU | `clob_ws_client.py:365`, `clob_metadata_client.py:40` | 🟠 rejets live, divergence dry-run vs live |
| 10 | Le simulateur de fill ignore le prix limite, les fees, la latence et l'impact ; book REST caché 5 s | NOUVEAU (M8 hors scope) | `realistic_fill.py:45-70`, `clob_orderbook_reader.py:57` | 🟠 dry-run optimiste |
| 11 | Les SELL passent par MarketFilter (`expiry_too_close` < 24 h), SlippageChecker et RiskManager | NOUVEAU | `strategy/pipeline.py:91-109,348-417` | 🔴 si le pipeline est réutilisé : sorties bloquées |
| 12 | Kill switch : polling 300 s, valorisation au mid ; en live, source Data API v1 + stub (total = exposition + constante) | NOUVEAU (partiel C-004) | `config.py:448-452`, `pnl_writer.py:92-150` | 🔴 inadapté à des fenêtres de 5 min |
| 13 | Résolution M8 inopérante jusqu'au 2026-05-22 (comma-join Gamma + `closed` exclu), puis polling 30 min ; pas de redeem live | commits `effaa34`, `371f8dc` | `dry_run_resolution_watcher.py`, `gamma_client.py:58-120` | 🟠 à refaire en événementiel |
| 14 | PnL figé 11 jours par une position injoignable (corrigé `effaa34`) ; retry tenacity sur 404 (corrigé) | commit `effaa34` | `virtual_wallet_reader.py:123-166`, `clob_read_client.py:25-40` | 🟡 corrigé, mais à garder en test de non-régression |
| 15 | Argent en `Float` | audit M-012 | `models.py` (toutes les colonnes USDC) | 🟠 dérive sur des milliers de fills |
| 16 | Caches async sans single-flight (Gamma, orderbook, WS) ; MD.8 différé | audit M-007 | `gamma_client.py`, `clob_orderbook_reader.py:69-87` | 🟡 |
| 17 | Race d'éviction LRU dans le WS (`pop` puis `await unsub`) ; double déclenchement du watchdog | audit H-015, M-017 | `clob_ws_client.py:457-464,506` | 🟠 si le transport WS est réutilisé |
| 18 | Instrumentation latence : INSERT awaité dans le chemin chaud ; `strategy_filtered > enriched` (H-001) ; `watcher_detected_ms` mélange temps réel et backfill | audit H-001, backlog | `pipeline.py:476-477`, `strategy/orchestrator.py:147-173` | 🟠 |
| 19 | Arrêt lent (1-3 min) au SIGTERM, TaskGroup non borné | backlog, session D3, MI | `runner.py:199-203` | 🟠 un cancel-all doit partir en moins d'une seconde |
| 20 | SQLite sans WAL ni `busy_timeout` ; une session et un commit par écriture | NOUVEAU | `storage/engine.py:11-19` | 🟠 contention sous flux de ticks |
| 21 | Mode `SIMULATION` = stub (pas de replay) | NOUVEAU | `executor/pipeline.py:114-124` | 🟠 il n'y a pas de backtester |
| 22 | `alembic` en dépendance dev mais importé au runtime ; `init_db` lié à l'arborescence source ; deps mortes `polymarket-apis`, `python-telegram-bot` | NOUVEAU | `pyproject.toml`, `storage/init_db.py:16-31` | 🟡 packaging |
| 23 | Règle de dépendance inter-modules non respectée (strategy ↔ executor ↔ monitoring) | NOUVEAU | §1.3 | 🟡 conception |
| 24 | `use_server_time=True` par défaut : +50-200 ms par signature (selon CLAUDE.md M18) | M18 D8 | `config.py:72`, `clob_write_client.py:94` | 🟠 latence d'ordre |
| 25 | Pas de gestion du HTTP 425 (redémarrage du matching engine, le mardi vers 7 h ET, ~90 s) | `docs/next/MK.md` (F51) | `executor/pipeline.py:212-218` | 🟠 fenêtres manquées |
| 26 | Fixtures WS et `clob-markets` V2 **synthétiques** (malgré « capturé ») | NOUVEAU | `tests/fixtures/clob_ws_market_sample.jsonl`, `clob_v2_market_*_sample.json` | 🟠 recapturer avant de coder le parse L2 |
| 27 | Dashboard « gain max latent » côté `No` = `size × avg_price` (faux : le payoff d'un token acheté est toujours `size × (1 − avg)`) ; outcomes `Up`/`Down` non prévus | NOUVEAU (régression MH.5 / M-011) | `dashboard/queries.py:977-986` | 🟡 à ne pas porter |
| 28 | Alertes avec cooldown 60 s par clé ; queue d'alertes de 100 en drop silencieux | M4, M-009 | `alert_dispatcher.py:129-133`, `runner.py:42` | 🟡 rafales d'erreurs d'ordres |
| 29 | Tests flaky `test_watcher_live_reload.py` | todo | `docs/todo.md` (§ tests flaky) | — (jeté) |
| 30 | Juridiction : Polymarket inaccessible officiellement depuis la France et d'autres pays | README | `README.md` | ⚠️ à trancher hors code |

---

## 9. Sites d'appel à la Data API v1 (cassés)

Tous ciblent `https://data-api.polymarket.com` **sans préfixe `/v2/`**. Les DTO lisent les champs camelCase v1. Ils utilisent `populate_by_name=True`, si bien que les champs **dont le nom Python est déjà en snake_case** (`proxy_wallet`, `condition_id`, `transaction_hash`, `usdc_size`, `outcome_index`, `avg_price`, `current_value`, `cash_pnl`…) seraient acceptés si v2 renvoie exactement ces noms. En revanche :
- les champs nommés `asset` (v2 `token_id`) restent obligatoires et casseraient la validation ;
- les accès **dict bruts** `.get("conditionId")` / `.get("proxyWallet")` renverraient silencieusement `None`, ce qui donnerait des métriques vides **sans erreur**. C'est le pire mode de panne si quelqu'un se contente de changer le chemin.

| # | Fichier:ligne | Endpoint v1 | Champs consommés | Usage / effet de la panne |
|---|---|---|---|---|
| 1 | `src/polycopy/watcher/data_api_client.py:37,114-127` | `GET /activity?user=&type=TRADE&limit&offset&sortDirection=ASC&start=` | filtre `raw["type"]` (`:70`) | Détection des trades source. 5 retries puis `poller_error` en boucle. |
| 2 | `src/polycopy/watcher/dtos.py:29-37` (`TradeActivity`) | idem | `proxyWallet`, `timestamp`, `conditionId`, `asset`, `side`, `size`, `usdcSize`, `price`, `transactionHash`, `outcome`, `slug`, `type` | `asset` → v2 `token_id` : échec de validation. |
| 3 | `src/polycopy/watcher/wallet_poller.py:101,168-182` | via #1 | `transaction_hash`, `asset`, `usdc_size`… ; `raw_json = model_dump(by_alias=True)` (camelCase en DB) | Les requêtes SQL qui lisent `raw_json` (§7 Q8) supposent des clés camelCase. |
| 4 | `src/polycopy/discovery/data_api_client.py:41,56-82` | `GET /holders?market=&limit=` | `holders[].proxyWallet` (dict brut `:74`), puis `HolderEntry` | Bootstrap du pool. Avec des clés snake_case, tous les holders seraient ignorés en silence. |
| 5 | `src/polycopy/discovery/data_api_client.py:86-115` | `GET /trades?limit&takerOnly&filterType=CASH&filterAmount` | `GlobalTrade` : `proxyWallet`, `asset`, `conditionId`, `side`, `size`, `price`, `timestamp`, `transactionHash`, `title`, `slug` | Bootstrap du pool (**410 confirmé**). |
| 6 | `src/polycopy/discovery/data_api_client.py:119-131` | `GET /value?user=` | `user`, `value` | Sanity check du capital et equity quotidienne. |
| 7 | `src/polycopy/discovery/data_api_client.py:135-163` | `GET /positions?user=&limit=500&sortBy=CASHPNL&sortDirection` | `RawPosition` : `conditionId`, `asset`, `size`, `avgPrice`, `initialValue`, `currentValue`, `cashPnl`, `realizedPnl`, `totalBought`, `redeemable`, `outcomeIndex` | Métriques v1/v2, gates, Brier, arbitrage gate. |
| 8 | `src/polycopy/discovery/data_api_client.py:167-198` | `GET /activity?user=&type=TRADE&limit=1000&sortDirection=DESC&start=` | dicts bruts `type`, `conditionId`, `size`, `price`, `timestamp` | `days_active`, volume, HHI. |
| 9 | `src/polycopy/discovery/data_api_client.py:211-232` | retry commun (4 essais, 404 → `[]`) | — | Les 410 sont retentés. |
| 10 | `src/polycopy/discovery/dtos.py:99-188` | (DTO pour #4-#7) | `proxyWallet`, `outcomeIndex`, `conditionId`, `transactionHash`, `avgPrice`, `initialValue`, `currentValue`, `cashPnl`, `realizedPnl`, `totalBought` | — |
| 11 | `src/polycopy/discovery/metrics_collector.py:47-48,76-81` | `get_positions` + `get_activity_trades` | `t.get("conditionId")`, `size`, `price` | Scoring v1 (métriques vides en silence si le schéma change). |
| 12 | `src/polycopy/discovery/metrics_collector_v2.py:116-117,142,355-356,380,401-407` | idem | `conditionId`, `size`, `price`, `timestamp` (dict bruts) | Scoring v2.x. |
| 13 | `src/polycopy/discovery/trader_daily_pnl_writer.py:153-154` | `get_value` + `get_positions` | `value`, `realized_pnl`, `is_resolved` | Courbe d'equity des wallets. |
| 14 | `src/polycopy/discovery/candidate_pool.py:101,123` | `get_holders`, `get_global_trades` | — | Construction du pool. |
| 15 | `src/polycopy/executor/wallet_state_reader.py:27,33,75-89` | `GET /positions?user=<funder>&limit=500` | `currentValue` (`:59`) | **Live** : garde-fou capital de l'executor et `PnlSnapshotWriter` (le kill switch live ne s'évalue plus). |
| 16 | `src/polycopy/dashboard/health_check.py:24,98` | `HEAD/GET /trades?limit=1` | code HTTP | Le footer du dashboard reste « degraded » en permanence. |
| 17 | `scripts/score_backtest.py:49,140-144` | `DiscoveryDataApiClient.get_positions` | via #7 | Script de backtest du scoring. |
| 18 | `tests/integration/test_data_api_live.py` | v1 | — | Test d'intégration opt-in. |
| 19 | Fixtures v1 camelCase : `tests/fixtures/activity_sample.json`, `data_api_holders_sample.json`, `data_api_positions_sample.json`, `data_api_trades_global_sample.json`, `data_api_value_sample.json` | — | — | Tests unitaires watcher/discovery (verts sur un schéma mort). |

Hors code : `docs/architecture.md`, `CLAUDE.md` (« APIs Polymarket utilisées »), les specs M1/M5 et `.env.example` documentent les chemins v1.

Ne dépendent **pas** de la Data API (et restent valides) : Gamma (`strategy/gamma_client.py`, `discovery/scoring/v2/category_resolver.py`, `fee_rate_client._resolve_token_to_condition` → Gamma `/markets-by-token`), CLOB REST (`/midpoint`, `/book`, `/tick-size`, `/clob-markets/{cid}`), CLOB WSS `market` et Goldsky.

---

## Annexe A — Faits empiriques du dry-run polycopy (tirés des commits et des docs)

- **Configuration** (`docs/todo.md:12-21,339-402`) : `EXECUTION_MODE=dry_run`, `DRY_RUN_REALISTIC_FILL=true`, capital virtuel 1 000 $, `MAX_POSITION_USD=20`, `COPY_RATIO=0.01`, `MAX_SLIPPAGE_PCT=2`, `KILL_SWITCH=20 %`, discovery + eviction actives, scoring v2.1, `MIN_HOURS_TO_EXPIRY` non surchargé (24 h). Redémarrage avec DB vierge le 2026-04-29, puis compteurs remis à zéro le 2026-05-02 après des correctifs.
- **État au 2026-05-22** (commits `effaa34`, `371f8dc`) : environ 566-567 positions virtuelles ouvertes ; 111 positions fermées, **toutes par SELL copié** (la résolution n'avait jamais fonctionné) ; PnL figé à environ 985 $ pendant 11 jours ; après le correctif, 95 positions résolues fermées, réalisé passé de −1,53 $ à −15,17 $, total de 988,77 $ à 975,08 $.
- **Latence** (2026-04-24, `docs/next/MK.md`) : `watcher_detected_ms` p50 13,4 s, p95 44 s, p99 44 min (backfill). Entonnoir enriched 27 418 → sized 13 153 → risk_checked 1 556 → submitted 1 169. Selon le backlog : `executor_submitted_ms` p50 635 ms, `strategy_sized_ms` p50 2,7 ms ; `position_already_open` est le premier motif de rejet.
- **Marché cible** : dans le fixture réel `/trades` v1 (2026-04-18, 500 trades ≥ 100 $), 44 trades portaient sur des fenêtres up/down 5m/15m (BTC 39, ETH 2, XRP 3). Titre type : « Bitcoin Up or Down - April 18, 5:20AM-5:25AM ET », outcomes `Up`/`Down`.

## Annexe B — Fichiers produits par cet audit

- Rapport : `/tmp/claude-0/-home-user-polycopy/c1517565-1179-5cad-9d67-6c943a23d73d/scratchpad/phase1_repo_inventory.md`
- Schéma SQLite reconstruit et données synthétiques : `/tmp/claude-0/-home-user-polycopy/c1517565-1179-5cad-9d67-6c943a23d73d/scratchpad/phase1_sqltest/schema.sql`
- Toutes les requêtes du §7 (validées : 31/31 s'exécutent) : `/tmp/claude-0/-home-user-polycopy/c1517565-1179-5cad-9d67-6c943a23d73d/scratchpad/phase1_sqltest/postmortem.sql`
