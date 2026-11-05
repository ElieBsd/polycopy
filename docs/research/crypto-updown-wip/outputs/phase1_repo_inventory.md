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
