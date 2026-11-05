# Note de reprise — audit pivot crypto Up/Down (WORK IN PROGRESS)

> Sauvegarde intermédiaire du 2026-11-05 ~12:50 UTC, faite à la demande d'Elie (limite d'usage proche).
> Ce dossier `crypto-updown-wip/` est **temporaire** : scripts et sorties de travail, à retirer du commit final
> (les règles de la mission demandent de ne committer que le rapport). Le rapport final ira dans
> `docs/research/crypto-updown-feasibility.md`.

## Où on en est

| Phase | État |
|---|---|
| Accès réseau | ✅ OK après création d'un environnement cloud dédié « polycopy » (hôtes Polymarket + exchanges autorisés). Binance `api.binance.com` → **451** (IP US) ; spot via `data-api.binance.vision`. Coinbase, Kraken, Bitstamp OK. `docs.polymarket.com` OK via curl (pas via WebFetch). |
| Phase 1 (inventaire repo) | ⏳ sous-agent lancé → `scratchpad/phase1_repo_inventory.md` (perdu si session coupée : à relancer) |
| Phase 2 (état API) | ⏳ sous-agent lancé → `scratchpad/phase2_api_state.md` (à relancer si perdu) |
| Phase 3a/3b (manipulation, concurrence) | ⏳ sous-agent lancé → `scratchpad/phase3ab_manipulation_competition.md` (à relancer si perdu) |
| Phase 3c dataset historique | ✅ 14 jours BTC 5m (2026-10-22 → 2026-11-05), **4 007 fenêtres**, ~6 M trades taker, spot Binance 1 s. Re-téléchargeable en ~10 min : `scripts/build_dataset.py data_btc5m 14 btc 300` |
| Phase 3c analyse 1 | ✅ `outputs/out_analysis1.txt` (microstructure, amplitude, allers-retours, calibration, lead-lag, mark-out makers) |
| Phase 3c collecteur temps réel | ⏳ tourne 12:36 → ~13:32 UTC (`scripts/collector.py`, WS CLOB market BTC 5m+15m + RTDS Chainlink/Binance). Analyse : `scripts/live_analysis.py` |
| Phase 3c backtest stratégies | ⏳ script écrit (`scripts/backtest.py`), pas encore lancé |
| Rapport final | ❌ à rédiger |

## Comment reprendre

```bash
S=/tmp/<scratchpad>; cd $S
python3 -m venv venv && venv/bin/pip install websockets numpy pandas scipy matplotlib httpx
venv/bin/python -I scripts/build_dataset.py data_btc5m 14 btc 300      # ~10 min
venv/bin/python -I scripts/analysis1.py                                 # écrit W_btc5m.pkl (~10 min)
venv/bin/python -I scripts/backtest.py W_btc5m.pkl                      # stratégies train/test
venv/bin/python -I scripts/collector.py live/live_$(date +%s).jsonl.gz 3360   # 56 min
venv/bin/python -I scripts/live_analysis.py
```

## Faits VÉRIFIÉS par appel réel (2026-11-05)

### API
- **Data API v1 retirée** : `GET https://data-api.polymarket.com/trades` et `/activity` → HTTP 410
  `{"error":"Data API v1 has been retired","migration":"https://data-api.polymarket.com/v2/"}`.
  **Polycopy (watcher, discovery) est cassé** sur ce point.
- Data API **v2** : `/v2/trades?condition=<conditionId>&limit=1000` (param `market` refusé, `offset` refusé :
  **pagination par curseur** `pagination.next_cursor` / `has_more`). Champs snake_case : `proxy_wallet, side,
  token_id, condition_id, size, price, timestamp, title, slug, outcome, outcome_index, transaction_hash`.
  Une ligne par transaction = **côté taker uniquement**. `outcome_index=999` observé sur `/v2/trades` sans filtre (anomalie).
- `GET /prices-history` (CLOB) : **~1 point par minute** quel que soit `fidelity` → 5 points par fenêtre 5 min,
  inutilisable pour du scalping intra-fenêtre.
- Gamma `/markets?slug=` ne renvoie **rien** pour un marché fermé sans `closed=true` (piège). Batch : slugs répétés + `closed=true` OK (50/req).
- WS CLOB `wss://ws-subscriptions-clob.polymarket.com/ws/market` : abonnement `{"type":"market","assets_ids":[...],"custom_feature_enabled":true}`
  OK ; ~45 messages/s sur une fenêtre BTC 5m active (`book`, `price_change` avec `best_bid`/`best_ask`).
- RTDS `wss://ws-live-data.polymarket.com` : `{"action":"subscribe","subscriptions":[{"topic":"crypto_prices_chainlink","type":"update"},{"topic":"crypto_prices","type":"update"}]}`
  → tous symboles, ~1 update/s chacun. Chainlink btc/usd reçu **~1,2 s** après son timestamp ; Binance btcusdt **~0,13 s**.
  Écart Binance BTCUSDT − Chainlink BTC/USD ≈ +77 $ dans l'échantillon (prime USDT). Filtre `{"symbol":"btc/usd"}` avec `type:"*"` marche aussi. PING texte toutes les ~5 s.
- Doc : il existe désormais des **Polymarket Perps** et un SDK Python avec `AsyncPublicClient` / `AsyncSecureClient` (à creuser, phase 2).

### Marchés Up/Down (séries Gamma, volume 24 h au 2026-11-05)
- BTC : 5m (id 10684, **13,7 M$**/24 h), 15m (10192, 3,1 M$), hourly (10114, 0,61 M$), 4h (10331, 68 k$), daily (41, 97 k$).
- ETH 5m 445 k$, 15m 354 k$ ; SOL 5m 106 k$ ; XRP 15m 76 k$ ; DOGE/BNB/HYPE (depuis mars 2026) < 50 k$.
- Slugs : `btc-updown-5m-<ts début>`, `btc-updown-15m-<ts>`, `btc-updown-4h-<ts>` ; horaire : `bitcoin-up-or-down-november-5-2026-7am-et` ; journalier : `bitcoin-up-or-down-on-november-5-2026`.
- Un marché 5m est **créé ~24 h avant** la fenêtre et **accepte des ordres dès sa création** (`acceptingOrdersTimestamp`). 5,4 % du notional taker est traité avant l'ouverture de la fenêtre.
- `orderMinSize=5` shares, tick 0.01 (0.001 près des extrêmes), `negRisk=false`, `restricted=true`, `rewardsMinSize=50`, `rewardsMaxSpread=4.5`.
- **Résolution 5m/15m/4h** : TWAP 60 s Chainlink (`https://data.chain.link/streams/btc-usd-twap-60s-streams`), `cryptoMarketConfig.twapLookbackSeconds=60`.
  Historique : Chainlink spot jusqu'au 2026-08-06 ; **TWAP 30 s du 2026-08-07 au 2026-08-13** ; **TWAP 60 s depuis le 2026-08-14 00:00 UTC**.
- **Horaire et journalier** : bougie Binance BTC/USDT (1 h ; ou close 1 min à 12:00 ET pour le journalier).
- `events[0].eventMetadata = {priceToBeat, finalPrice}`. **priceToBeat(n) == finalPrice(n−1)** sur 4 005/4 005 paires → Up ssi TWAP60(fin) ≥ TWAP60(début).
- Résolution **automatique** (`automaticallyResolved=true`, `resolutionMechanism=oracle`) **~79 s** après la fin (p10 78 s, p90 81 s). 0 égalité sur 4 007. Up = 49,7 %.
- Des trades continuent **après la fin de fenêtre** jusqu'à la résolution (ex. à 0.999, +54 s).

### Frais (doc officielle `docs.polymarket.com/trading/fees.md`, copie dans `outputs/`)
- `fee (USDC) = C × feeRate × p × (1 − p)`, C = nb de shares. Crypto : **feeRate = 0.07**, makers jamais facturés, **maker rebate 20 %** des frais.
  Gamma : `feeSchedule={"exponent":1,"rate":0.07,"takerOnly":true,"rebateRate":0.2}`, `feeType=crypto_fees_v2`.
- Par share : 1,75 ¢ à p=0.5 (**3,5 % du notional**), 1,12 ¢ à 0.20 (5,6 %), 0,33 ¢ à 0.05 (6,65 %).
- **Écart polycopy** : `PositionSizer._compute_effective_fee_rate` calcule `rate × (p(1−p))^e` en % du notional = 1,75 % à 0.5 → **sous-estime d'un facteur 1/p** (×2 à 0.5, ×5 à 0.2).
- **Taker Rebate Program** (live depuis 2026-05-28) : wV = taille$ × (1 − prix) × poids (crypto 2,3) ; paliers 30 j : Bronze 2 k$ → 3 %, Silver 20 k$ → 8 %, Gold 200 k$ → 18 %, Platinum 1 M$ → 32 %, Diamond 4 M$ → 44 %, Obsidian 10 M$ → 50 %.
- Maker rebates payés quotidiennement en pUSD (min 1 $), lisibles via `GET https://clob.polymarket.com/rebates/current?date=&maker_address=`.

### Résultats empiriques préliminaires (14 j, 4 000 fenêtres BTC 5m — `outputs/out_analysis1.txt`)
- Par fenêtre : médiane **1 383 trades taker**, **21 k$ de notional taker**, **520 wallets** distincts. Trade médian 4 $, p99 200 $.
- Spread : quasi toujours **1 tick (0.01)**.
- Amplitude max−min du mid Up dans une fenêtre : médiane **0.60**, p90 0.86 → les gros mouvements sont la norme.
- Allers-retours exécutables (achat ask ≤ a puis bid ≥ b plus tard, même côté) : 0.20→0.60 touché **26,8 %** des cas,
  0.15→0.60 **18,7 %**, 0.20→0.40 **39 %**, 0.40→0.60 **57 %**. À comparer aux seuils de rentabilité si l'alternative était
  la perte totale (36 %, 27 %, 55 %, 72 %) → **pas rentable en l'état** ; la valeur dépend du stop / de la résolution (backtest à faire).
- **Calibration** : le prix de marché est bien calibré à tous les horizons (écarts dans les IC95) ; Brier marché ≤ Brier du modèle FV.
  Pas de biais favori/longshot exploitable visible.
- **Mark-out taker à la résolution** (tous trades) : −0,04 ¢/share brut, **−1,02 ¢/share net de frais**. Les makers gagnent
  +0,04 ¢ brut, **+0,24 ¢/share avec rebate 20 %**. Les takers en début de fenêtre (0–120 s) perdent le plus (−1,7 ¢ net).
- **Lead-lag** : Δmid corrèle surtout avec ΔFV d'il y a **3 s** (0,32) → le marché semble suivre le spot avec ~2–3 s de retard
  **dans les timestamps Data API** (peut-être artefact d'horodatage on-chain ; à vérifier avec le collecteur ms).
- **Modèle FV** (`scripts/fv.py`) : bon jusqu'à τ=60 s, **faux près de la fin** (Brier 0,40 à τ=3 s) → bug/hypothèse TWAP à revoir
  (tester si `finalPrice` = TWAP des 60 dernières secondes ou de toute la fenêtre ; basis Binance−Chainlink variable).

## Prochaines étapes
1. Vérifier la définition exacte du TWAP (fin de fenêtre) en comparant `finalPrice` au spot Binance − basis ; corriger `fv.py`.
2. Lancer `backtest.py` (S1 fade, S1b fade+FV, S1c chute non justifiée, S2 momentum, S3 écart FV, S4 longshot, S5 favori tardif) train/test.
3. Analyser le collecteur (spread, profondeur réelle du bid, lead-lag ms) et valider la reconstruction par trades.
4. Analyse wallets (taker PnL par wallet, allers-retours vs hold) depuis le dataset.
5. Rassembler phases 1/2/3ab, rédiger le rapport final, retirer `crypto-updown-wip/`, pousser.

---
## Mise à jour 2026-11-05 ~13:35 UTC (pause demandée par Elie pour économiser le quota)

Nouveaux résultats (fichiers dans `outputs/`) :
- `out_twap_check.txt` : finalPrice = TWAP des **60 dernières secondes** (Binance − basis : MAE 3,5 $, direction 97,4 %). Basis Binance(USDT) − Chainlink(USD) ≈ 112 $ médiane, dérive intra-fenêtre ~2,6 $ → **un bot doit lire Chainlink directement** pour la fin de fenêtre.
- `out_fv_recal.txt` : marché mieux calibré que le modèle FV Binance à toutes les échéances (normal près de la fin : le marché voit Chainlink).
- `out_backtest.txt` + `out_latency_sens.txt` : **fade brut (idée initiale) ≈ 0 à toutes latences**. Les signaux « écart FV » et « chute non justifiée par le spot » font +6 à +10 ¢/share à 1 s de latence mais **tombent à 0 dès 4–5 s** → soit edge de latence réservé aux bots rapides, soit artefact d'horodatage Data API. **Non tranché.**
- `out_wallets.txt` : sur 14 j, takers −1,93 M$ net (frais 1,79 M$), 28 % des wallets takers profitables ; les wallets qui font des allers-retours sont parmi les pires.
- `phase1_repo_inventory.md`, `phase2_api_state.md`, `phase3ab_manipulation_competition.md` : rapports complets des sous-agents. Faits marquants : polycopy cassé (16 appels Data API v1), `py-clob-client-v2` déprécié → `polymarket-client` 0.16.0, taker delay crypto 150 ms, RTDS legacy → PolyBolt (credentials requis), Suisse : pas dans la liste geoblock mais blocage DNS Gespa depuis 2024 ; papier arXiv 2606.31675 (manipulation spot au fixing → passage TWAP) ; arXiv 2607.26245 (lag Binance ~16 ms, réponse cotations ~347 ms) ; wallets célèbres (0x8dxd, gabagool22…) tous inactifs.

**Reste à faire à la reprise (coût modéré) :**
1. `venv/bin/python -I scripts/live_analysis2.py live/live_1793882166.jsonl.gz` → décalage horodatage Data API vs WS (appariement par tx hash) + lead-lag ms. ⚠️ le fichier live (160 Mo) est **dans le scratchpad, pas sur git** : s'il a disparu, relancer `collector.py` 30–60 min (ou accepter l'estimation du papier arXiv 2607.26245).
2. Si l'écart FV survit à la latence réelle : tester en mode maker (le seul profil qui gagne d'après les données).
3. Rédiger `docs/research/crypto-updown-feasibility.md` (synthèse) + annexes, retirer `crypto-updown-wip/`, pousser.
