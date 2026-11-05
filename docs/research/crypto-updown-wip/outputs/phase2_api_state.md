# Polymarket — état de l'API, des marchés crypto « Up or Down » court terme, des frais et de l'accès légal (au 5 novembre 2026)

> Rapport de recherche, phase 2. Cible : un développeur basé en **Suisse** qui veut un bot de scalping intra-fenêtre sur « Bitcoin Up or Down » 5 min / 15 min / 1 h, et dont le dernier état de l'art date d'avril–mai 2026 (CLOB V2 + pUSD, `py_clob_client_v2==1.0.0`).
> Collecte : 2026-11-05, entre 12:30 et 12:50 UTC. Lecture seule publique : aucune credential, aucun POST, aucun ordre.
> JSON bruts : `/tmp/claude-0/-home-user-polycopy/c1517565-1179-5cad-9d67-6c943a23d73d/scratchpad/agent_api/raw/` (pages de doc officielles en `.md` dans `raw/docs/`, carnets dans `raw/books/`).

## Légende des étiquettes

| Étiquette | Sens |
| - | - |
| **[VÉRIFIÉ appel réel]** | Constaté par un GET réel le 2026-11-05 (12:30–12:50 UTC). Un extrait brut est collé ou sauvegardé. |
| **[VÉRIFIÉ doc officielle]** | Lu dans docs.polymarket.com (fichier `.md`, consulté le 2026-11-05), sur PyPI ou dans le code du SDK officiel. La date de la source est donnée quand elle existe. |
| **[DÉDUIT]** | Raisonnement à partir de faits vérifiés (calcul, recoupement). |
| **[SUPPOSÉ]** | Non vérifié à la source. Comprend les informations de presse ou de blog remontées par WebSearch, que je n'ai pas pu ouvrir. |

### Limites de collecte (hôtes bloqués ou non testés)

- `api.github.com/repos/Polymarket/py-clob-client-v2/releases` → **403** (« GitHub access to this repository is not enabled for this session »). Contournement : `raw.githubusercontent.com` (README, `setup.py`, sources) et les **wheels PyPI 1.0.0 et 1.2.1** téléchargées et comparées par diff. Il n'y a pas de `CHANGELOG.md` dans le repo (404).
- WebFetch vers `blocklist.gespa.ch`, `www.coindesk.com` et les autres sites hors liste → **ENOTFOUND** (hôtes hors du réseau autorisé). Les informations légales et de presse viennent donc des résumés WebSearch, étiquetées [SUPPOSÉ] sauf recoupement.
- **WebSockets non testés en direct** : `ws-subscriptions-clob`, `ws-live-data` et `ws-live-v2` ne figurent pas dans la liste curl autorisée. Section B = doc officielle + AsyncAPI.
- **Cloudflare 1010** : le CLOB renvoie `403 error code: 1010` au User-Agent par défaut `Python-urllib/3.13` alors que curl passe [VÉRIFIÉ appel réel]. Un client Python doit envoyer un User-Agent explicite et honnête, par exemple celui de httpx ou un UA applicatif.
- La sandbox sort géolocalisée **US/OH** (voir D). Mes latences mesurées ne sont donc pas représentatives d'un hôte en Suisse ou à Londres.

---

## 0. Résumé exécutif — ce qui a changé depuis avril–mai 2026

1. **Data API v1 retirée le 2 novembre 2026.** Toutes les routes v1 (`/activity`, `/trades`, `/positions`, `/value`, `/holders`, `/v1/leaderboard`…) renvoient **HTTP 410** [VÉRIFIÉ appel réel]. La v2 (`/v2/...`, sortie le 4 sept. 2026) impose un envelope `{data, pagination}`, une pagination **par curseur uniquement** (`offset` → 400), du snake_case, et `condition` à la place de `market` (`market` → 400) [VÉRIFIÉ appel réel + changelog du 2026-11-02].
2. **`py-clob-client-v2` est déprécié** : README et PyPI affichent « This package is deprecated. Please migrate to the unified Polymarket SDK ». Dernière version **1.2.1 (2026-10-15)**. Le remplaçant est **`polymarket-client` 0.16.0 (2026-11-02, Python ≥ 3.11)** [VÉRIFIÉ PyPI].
3. **Frais crypto actuels** : `fee = C × 0.07 × p × (1−p)`, exponent 1, taker only, rebate maker 20 % [VÉRIFIÉ appel réel `fd:{r:0.07,e:1,to:true}` + doc Fees]. Au pic p = 0,50, cela fait **1,75 ¢/share, soit 3,5 % du notional**, et **7 % pour un aller-retour taker/taker**. Le coefficient est passé de 0,072 (fixture polycopy d'avril) à 0,07 ; ce changement n'apparaît pas dans le changelog [DÉDUIT].
4. **Bug de calcul dans polycopy** : `pipeline.py` calcule `fee = notional × r × p(1−p)`, alors que la formule officielle est `shares × r × p(1−p)`. Les frais sont donc **sous-estimés d'un facteur 1/p** (×2 à p = 0,5, ×5 à p = 0,2) [DÉDUIT : code polycopy vs doc + `fees.py` du SDK].
5. **Résolution « TWAP Chainlink 60 s »** sur les marchés 5 m, 15 m et 4 h. Le TWAP a remplacé le prix spot ponctuel le 7 août 2026 (30 s pour le 5 m, puis 60 s le 14 août). La source est `https://data.chain.link/streams/btc-usd-twap-60s-streams`. **Les marchés 1 h et daily se résolvent encore sur la bougie Binance BTC/USDT**, pas sur Chainlink [VÉRIFIÉ appel réel, descriptions Gamma].
6. **Price to beat de la fenêtre N = finalPrice de la fenêtre N−1**, exposé dans Gamma `events[].eventMetadata.{priceToBeat, finalPrice}`. Vérifié sur 12 fenêtres consécutives, mais ces champs ne sont renseignés **qu'après la fin de la fenêtre** [VÉRIFIÉ appel réel]. Résolution automatique « oracle » environ **79 à 81 s après la fin** de la fenêtre (12/12 marchés) [VÉRIFIÉ appel réel].
7. **Taker delay sur les marchés crypto** : 250 ms → 50 ms (17 août) → **150 ms depuis le 4 sept. 2026, 14:00 UTC** [VÉRIFIÉ doc officielle, changelog]. Une page de doc et l'OpenAPI disent encore 250 ms : la doc diverge d'elle-même. Le champ `itode: true` est visible sur `/clob-markets` [VÉRIFIÉ appel réel].
8. **Prix de référence temps réel** : RTDS (`ws-live-data`, topics `crypto_prices` et `crypto_prices_chainlink`) est **legacy** depuis le 15 sept. 2026. **PolyBolt** (`wss://ws-live-v2.polymarket.com/ws`) le remplace : canaux `price.crypto` (Chainlink par défaut, Pyth en option, **plus de Binance**) et `price.crypto.twap` (le TWAP 60 s qui sert à la résolution). PolyBolt **exige des credentials CLOB API** [VÉRIFIÉ doc officielle].
9. **Microstructure 5 m BTC** : spread de 1 tick (0,01), environ 45 à 78 niveaux par côté, profondeur à ±5 ¢ du mid d'environ **0,4 à 5 k$ par côté**, volume moyen d'environ **46 k$ par fenêtre de 5 min** (12 fenêtres échantillonnées). Le prix bascule violemment en cours de fenêtre (Up 0,545 → 0,215 en 61 s). Le tick passe à 0,001 près de 0/1 [VÉRIFIÉ appel réel].
10. **Suisse** : CH **n'est pas** dans la liste geoblock officielle ni dans la liste des ToS (en vigueur depuis le 11 août 2026) [VÉRIFIÉ doc officielle]. En revanche, la Gespa a mis **polymarket.com sur sa liste de blocage (blocage DNS) depuis le 26.11.2024**, et a ajouté des clones « .ch » ensuite [SUPPOSÉ, plusieurs sources de presse concordantes]. Selon les sources cantonales, la participation n'est **pas punissable pour le joueur**, mais les gains sont **entièrement imposables** comme revenu (pas d'exonération LJAr pour un opérateur non autorisé) [SUPPOSÉ, merkblätter cantonaux via WebSearch]. Contourner un blocage par VPN est **interdit par les ToS** [VÉRIFIÉ ToS].

---

## A. CLOB V2 — SDK, endpoints, ordres, limites

### A.1 SDK Python : `py-clob-client-v2` déprécié, `polymarket-client` unifié

| Paquet | Dernière version | Date | Statut | Source |
| - | - | - | - | - |
| `py-clob-client` (V1) | 0.34.6 | 2026-02-19 | Mort depuis le cutover du 28 avril 2026 (« No V1 compatibility ») | [pypi json](https://pypi.org/pypi/py-clob-client/json) + changelog du 2026-04-28 [VÉRIFIÉ] |
| `py-clob-client-v2` | **1.2.1** | 2026-10-15 | **Déprécié** (bannière README et PyPI) | [pypi json](https://pypi.org/pypi/py-clob-client-v2/json), [README](https://raw.githubusercontent.com/Polymarket/py-clob-client-v2/main/README.md) [VÉRIFIÉ] |
| `polymarket-client` (SDK unifié) | **0.16.0** | 2026-11-02 | Recommandé. Python ≥ 3.11, pydantic v2, websockets, httpx[http2], msgpack. Extras `pandas`, `polars`, `arrow`, `quant` | [pypi json](https://pypi.org/pypi/polymarket-client/json), [repo py-sdk](https://github.com/Polymarket/py-sdk) [VÉRIFIÉ] |

**Historique des versions `py-clob-client-v2`** [VÉRIFIÉ PyPI] : 0.0.1 et 0.0.2 (2026-04-08), 0.0.4 (2026-04-16), **1.0.0 (2026-04-17)**, 1.0.1rc1 (2026-05-01), 1.0.1 (2026-05-09), 1.0.2 (2026-07-02), 1.1.0 (2026-07-17), 1.2.0 (2026-09-25), 1.2.1 (2026-10-15).

**Écarts 1.0.0 → 1.2.1** (diff des wheels PyPI) [VÉRIFIÉ code SDK officiel] :
- `TickSize` gagne `"0.005"` et `"0.0025"` : `Literal["0.1","0.01","0.005","0.0025","0.001","0.0001"]`. En 1.0.0 c'était `["0.1","0.01","0.001","0.0001"]`. Le changelog du 2026-07-02 annonce le tick 0.0025 sur les marchés Coupe du monde.
- `OrderArgs` / `MarketOrderArgs` deviennent `@dataclass(init=False)` avec `token_id: Optional[str]` et un nouvel argument keyword `position_id` (marchés « Polymarket Protocol V2 », qui signent via **ExchangeV3**, domaine EIP-712 version `"3"`). Il faut fournir exactement un des deux identifiants. `OrderArgs` reçoit aussi `user_usdc_balance` : si le solde ne couvre pas `size × price + fees`, la taille est réduite.
- Nouveau module `fees.py` (`adjust_buy_amount_for_fees`) : `platform_fee = (amount/price) × rate × (p(1−p))^e`, c'est-à-dire **shares × rate × p(1−p)**, plus `builder_fee = amount × builder_taker_fee_rate`.
- `config.py` : ajout de `exchange_v3 = 0xe3333700cA9d93003F00f0F71f8515005F6c00Aa` (Polygon).
- `constants.py` : `RESOLVE_TRADES_TIMEOUT_SECONDS=30`, `RESOLVE_TRADES_POLL_INTERVAL_SECONDS=0.25`. Le client résout lui-même les hash de transaction à partir des `tradeIDs`. Depuis le 24 juillet 2026, `POST /order` ne renvoie plus `transactionHashes` sur les matchs FAK/FOK, seulement `tradeIDs` [VÉRIFIÉ changelog du 2026-07-17].
- Inchangé : `OrderType` reste une classe à attributs (`GTC`, `FOK`, `GTD`, `FAK`), `PartialCreateOrderOptions(tick_size, neg_risk, version)`, `create_or_derive_api_key`, `post_heartbeat`, `post_only` (refusé pour FOK/FAK), `cancel_market_orders`.

**SDK unifié** (`polymarket-client`) [VÉRIFIÉ doc officielle, [Migrate from Legacy SDKs](https://docs.polymarket.com/migrate/clob-sdk-to-unified-sdk.md), [SDK changelog](https://docs.polymarket.com/changelog/sdks.md)] :
- Clients `AsyncPublicClient` / `AsyncSecureClient` (plus des versions synchrones). Ils couvrent CLOB, Gamma, Data API v2 (depuis 0.10.0) et les streams (`polymarket.streams` : `MarketSpec`, `CryptoPriceSpec`, `CryptoTwapPriceSpec`…).
- 0.11.0 : PolyBolt. 0.14.0 : heartbeats d'ordres, rebates maker par date. 0.15.0 : `market.trading.taker_delay_ms` (remplace `seconds_delay`, déprécié). 0.16.0 : suppression de `download_accounting_snapshot`.
- Nouveau type de wallet **Deposit Wallet**, signature type **3** (`DEPOSIT_WALLET` / `POLY_1271`). C'est le type par défaut de tous les comptes créés **depuis le 4 mai 2026**. EOA = 0, POLY_PROXY = 1, GNOSIS_SAFE = 2 [VÉRIFIÉ doc [Wallets and Authentication](https://docs.polymarket.com/trading/wallets-auth.md)]. Les « Session Keys » permettent de déléguer un signer limité dans le temps.

### A.2 Endpoints REST CLOB (host `https://clob.polymarket.com`)

`GET /version` → `{"version":2}` et `GET /time` → `1793881870` [VÉRIFIÉ appel réel].

Liste des routes publiques et privées de l'[OpenAPI CLOB](https://docs.polymarket.com/api-spec/clob-openapi.yaml) et de `endpoints.py` du SDK [VÉRIFIÉ doc officielle] :
- **Marché, public** : `/book`, `POST /books` (batch, 500 éléments max), `/midpoint`, `/midpoints`, `/price`, `/prices`, `/spread`, `/spreads`, `/last-trade-price`, `/last-trades-prices`, `/tick-size[/{token_id}]`, `/neg-risk[/{token_id}]`, `/fee-rate[/{token_id}]`, `/clob-markets/{condition_id}`, `/markets/{condition_id}`, `/markets-by-token/{token_id}`, `/markets/live-activity/{condition_id}`, `/prices-history`, `/batch-prices-history`, `/sampling-markets`, `/simplified-markets`, `/rebates/current`, `/rewards/markets/current`.
- **Ordres, L2** : `POST /order`, `POST /orders` (batch), `DELETE /order`, `DELETE /orders` (≤ 1000 IDs selon le changelog du 2026-06-15, mais la page *Manage Orders* dit « up to 3,000 » : **divergence de la doc**), `DELETE /cancel-all`, `DELETE /cancel-market-orders`, `GET /data/orders`, `/data/order/{id}`, `/data/trades`, `/data/pre-migration-orders`, `/order-scoring`, `POST /v1/heartbeats`, `/balance-allowance[/update]`, `/notifications`, `/v1/user/rate-limit-tier`, `/auth/ban-status/closed-only`.
- **Auth** : L1 (signature EIP-712 `ClobAuth`, domaine `"1"`) pour `/auth/api-key` et `/auth/derive-api-key`. L2 (HMAC-SHA256 base64 url-safe sur `timestamp + METHOD + path + body`, headers `POLY_ADDRESS`, `POLY_API_KEY`, `POLY_PASSPHRASE`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`) pour tout le reste [VÉRIFIÉ doc officielle].

**Appels réels sur le marché `btc-updown-5m-1793881800` en cours** (token Up `8298…7857`, 12:31 UTC) [VÉRIFIÉ appel réel] :
```
GET /fee-rate?token_id=…        → {"base_fee":1000}
GET /clob-markets/0xdefab1e2…   → {"r":{"mi":50,"ma":4.5,"moas":30},"t":[{"t":"8298…7857","o":"Up"},{"t":"9168…5948","o":"Down"}],
                                   "c":"0xdefab1e2…","mos":5,"mts":0.01,"mbf":1000,"tbf":1000,"ao":true,"aot":"2026-11-04T12:37:42Z",
                                   "itode":true,"fd":{"r":0.07,"e":1,"to":true},"v":"v1"}
GET /midpoint?token_id=…        → {"mid":"0.355"}
GET /price?token_id=…&side=BUY  → {"price":"0.35"}      (side=SELL → {"price":"0.35"})
GET /spread?token_id=…          → {"spread":"0.02"}
GET /tick-size?token_id=…       → {"minimum_tick_size":0.01}
GET /neg-risk?token_id=…        → {"neg_risk":false}
GET /last-trade-price?token_id=…→ {"price":"0.31","side":"BUY"}
GET /markets/0xdefab1e2…        → {..."minimum_order_size":5,"minimum_tick_size":0.01,"maker_base_fee":1000,"taker_base_fee":1000,"seconds_delay":0,"neg_risk":false,...}
```
Les clés courtes de `/clob-markets` selon l'OpenAPI : `mos` = taille min, `mts` = tick, `mbf`/`tbf` = base fees, `itode` = taker delay actif, `fd` = fee details `{r, e, to}`, `r` = rewards `{mi, ma, moas}` (min size, max spread, min order age s), `v` = version de marché. Les champs `rfqe`, `ibce` et `oas` sont omis quand ils valent false ou 0 [VÉRIFIÉ doc officielle].

**`GET /markets/live-activity/{cid}`** est public et renvoie des métadonnées minimales (question, slugs, tags `["Crypto","Bitcoin",…,"5M"]`). Ce n'est **pas** un flux de trades [VÉRIFIÉ appel réel]. Il n'existe **pas de `/trades` CLOB public** : `/data/trades` exige L2 [VÉRIFIÉ OpenAPI]. Les trades publics viennent de **Data API `/v2/trades`** (A.6).

### A.3 Types d'ordres, post-only, annulation, heartbeat, batch

Toutes ces informations sont [VÉRIFIÉ doc officielle] ([Place Orders](https://docs.polymarket.com/trading/place-orders.md), [Manage Orders](https://docs.polymarket.com/trading/manage-orders.md), [Order Lifecycle](https://docs.polymarket.com/concepts/order-lifecycle.md), [Matching Engine](https://docs.polymarket.com/trading/matching-engine.md), consultés le 2026-11-05).

- **GTC** : reste dans le carnet jusqu'au fill ou à l'annulation.
- **GTD** : l'ordre expire **1 min avant** son `expiration`, et `expiration` doit être à au moins **3 min** dans le futur. Durée de vie effective minimale d'environ 2 min, donc **inutilisable pour des quotes de quelques secondes** : il faut annuler activement.
- **FOK / FAK** : les ordres « market » (le montant d'un BUY est en pUSD, celui d'un SELL en shares).
- **Post-only** (depuis le 6 janvier 2026) : uniquement en GTC ou GTD. L'ordre est rejeté s'il croiserait le carnet. Pour FOK/FAK, le SDK lève `ValueError`.
- **Statuts de réponse** : `live`, `matched`, `delayed` (marketable soumis au taker delay), `unmatched`. Pendant le délai, l'ordre **ne peut pas être annulé**.
- **Taker delay crypto** : 250 ms jusqu'au 17 août 2026 → 50 ms → **150 ms depuis le 4 sept. 2026, 14:00 UTC** ([changelog](https://docs.polymarket.com/changelog/predictions.md)). [Order Lifecycle](https://docs.polymarket.com/concepts/order-lifecycle.md) et l'OpenAPI (`itode` : « held for the 250 ms ») sont restés à 250 ms. **La valeur faisant foi est 150 ms** [DÉDUIT : le changelog est daté et le plus récent]. `GET /markets/{cid}` renvoie `seconds_delay: 0` sur ce marché : ce champ ne reflète pas le taker delay crypto [VÉRIFIÉ appel réel].
- **Annulations** : `DELETE /order`, `DELETE /orders` (liste d'IDs), `DELETE /cancel-all`, `DELETE /cancel-market-orders` (par `market` et/ou `asset_id`). Un ordre partiellement rempli garde ses fills.
- **Heartbeat / dead-man switch** : `POST /v1/heartbeats {"heartbeat_id": ""}` toutes les **5 s**, avec la même clé API que les ordres. Le premier heartbeat accepté **arme** l'annulation de tous les ordres de cette clé, **sans endpoint de désarmement**. Après 10 s sans heartbeat, un cancel-all est mis en file (best effort, scan toutes les 5 s). Le keepalive WebSocket ne compte pas comme heartbeat.
- **Batch** : `POST /orders` (`PostOrdersV2Args`). Il faut vérifier `ok` pour chaque entrée.
- **Redémarrages du moteur** : annoncés environ 2 jours avant sur Telegram (`t.me/polytradingapis`) et Discord. Pendant 2 min après le redémarrage, le moteur est en **mode post-only** : `503 {"code":"post_only_mode","retry_after_seconds":…}`.
- **Fin du cutover V2 du 28 avril** : les ordres V1 ont été effacés et les clients V1 ne sont plus supportés.

**Latence de placement / annulation** :
- La doc ne publie pas de SLA. Serveurs principaux en **`eu-west-2` (Londres)** ; la région non géo-restreinte la plus proche est `eu-west-1` (Irlande). Une **co-location directe en `eu-west-2`** est offerte après un formulaire KYC/KYB, aux market makers et traders individuels, pas aux builders [VÉRIFIÉ doc [Geographic Restrictions](https://docs.polymarket.com/api-reference/geoblock.md)].
- Le pipeline de commit asynchrone du 24 juillet 2026 a été introduit pour « cuts matching latency » [VÉRIFIÉ changelog].
- Mes GET depuis la sandbox (US/OH) prennent entre **0,17 et 0,49 s** au total (TLS inclus, via proxy), ce qui n'est pas représentatif [VÉRIFIÉ appel réel].
- Un bot sur Wi-Fi domestique (≥ 150 ms) serait désavantagé face à un VPS en datacenter (~5 ms) [SUPPOSÉ, blogs vendeurs, p. ex. [polybot.trading](https://polybot.trading/blog/polymarket-taker-delay-250ms-to-50ms)].
- Ordre de grandeur Zurich ↔ Londres : environ 15 à 25 ms de RTT [SUPPOSÉ].

**Tick size et taille minimale** :
- Le tick du marché 5 m BTC est **0,01** et la taille min **5 shares** [VÉRIFIÉ appel réel]. Les rewards exigent `rewardsMinSize: 50` et `rewardsMaxSpread: 4.5` (¢).
- Le tick devient **0,001 près des extrémités** : carnet à 0,999/0,001, `"tick_size":"0.001"`, observé à 252 s dans la fenêtre 5 m et à 803 s dans la fenêtre 15 m [VÉRIFIÉ appel réel]. L'événement WS `tick_size_change` le signale [VÉRIFIÉ doc]. La doc ne publie pas de seuil exact ; le seuil communautaire courant est p > 0,96 ou p < 0,04 [SUPPOSÉ].
- Table de précision selon le tick : 0,01 → 2 décimales prix / 2 taille / 4 montant ; 0,001 → 3/2/5 ; 0,005 → 3/2/5 ; 0,0025 → 4/2/6 [VÉRIFIÉ doc officielle].

### A.4 Rate limits

Deux couches [VÉRIFIÉ doc officielle] : [Rate Limits](https://docs.polymarket.com/api-reference/rate-limits.md) (Cloudflare, par IP) et [Trading Rate Limits](https://docs.polymarket.com/api-reference/trading-rate-limits.md) (par signer).

**Couche Cloudflare (IP)** : l'excès est throttlé, c'est-à-dire mis en file, plutôt que rejeté.

| Domaine | Limites |
| - | - |
| CLOB général | 9 000 req / 10 s |
| CLOB market data | `/book` 1 500 / 10 s ; `/books` 500 ; `/price` et `/midpoint` 1 500 ; `/prices-history` 1 000 ; tick-size 200 |
| CLOB trading | `POST /order` 5 000 / 10 s en burst, 120 000 / 10 min en soutenu ; `DELETE /order` idem ; `POST /orders` 2 000 / 10 s, 21 000 / 10 min ; `DELETE /orders` 2 000 / 10 s, 15 000 / 10 min ; `DELETE /cancel-all` 250 / 10 s, 6 000 / 10 min ; `DELETE /cancel-market-orders` 1 500 / 10 s, 21 000 / 10 min |
| Gamma | 4 000 / 10 s ; `/markets` 300 ; `/events` 500 |
| Data API v2 | 800 / 10 s ; `/v2/trades` 300 ; `/v2/positions` et `/v2/activity` 200 ; `/v2/prices-history` 200 |

**Couche par signer** (token-bucket, depuis le 24 juillet 2026, d'abord en *warning mode* avec le header `Poly-RateLimit-Warning`) :

| Palier | Volume 30 j | Ordres (rate/s / burst) | Cancels (rate/s / burst) |
| - | - | - | - |
| Standard | — | 40 / 60 | 80 / 120 |
| Copper | ≥ 30 k$ | 60 / 90 | 120 / 180 |
| Bronze | ≥ 50 k$ | 80 / 120 | 160 / 240 |
| Silver | ≥ 100 k$ | 200 / 300 | 400 / 600 |
| Gold | ≥ 500 k$ | 400 / 600 | 800 / 1 200 |
| Platinum | ≥ 2,5 M$ | 450 / 675 | 900 / 1 350 |
| Diamond | ≥ 5 M$ | 525 / 787 | 1 050 / 1 575 |
| Elite | ≥ 10 M$ | 600 / 900 | 1 200 / 1 800 |

Un batch coûte un token par ordre. Les headers `Poly-RateLimit-Remaining`, `-Reset` et `-Tier` indiquent l'état du bucket, et un dépassement renvoie `429` avec `Retry-After`. Je n'ai trouvé aucune annonce de passage en enforcement live ; elle est peut-être faite sur Telegram ou Discord [SUPPOSÉ].

### A.5 Historique de prix : CLOB `/prices-history` et Data API `/v2/prices-history`

Tests sur le marché **résolu** `btc-updown-5m-1793878200` (fenêtre 11:30–11:35 UTC, résolu Up), token Up `2625…6137`. Fichiers `raw/clob_priceshist_*.json` et `raw/dv2_priceshist_*.json` [VÉRIFIÉ appel réel].

| Requête | Points | Espacement réel |
| - | - | - |
| CLOB `?market=…&interval=1h&fidelity=1` | 5 | 41 à 71 s (médiane 63,5 s) |
| CLOB `?startTs=S−600&endTs=E+600&fidelity=1` | 18 | médiane 60 s (41 à 71 s) |
| CLOB idem sans `fidelity` | 18 | identique (le défaut est 1 min) |
| CLOB idem `fidelity=0.1` | 18 | identique : une valeur < 1 est ignorée silencieusement, pas d'erreur |
| CLOB `interval=1d&fidelity=1` | 1 308 | médiane 60 s (19 à 450 s) |
| CLOB `interval=max` | 133 | médiane 600 s |
| Data v2 `?start=…&end=…` (sans bucket) | 19 | 60 s pile, avec `resolution_seconds:60` et un point terminal de settlement `{"price":1.0,"resolution_seconds":0}` |
| Data v2 `bucket_seconds=60` | 19 | 60 s |
| Data v2 `bucket_seconds=30` ou `1` | — | **HTTP 400** `{"error":"bucket_seconds must be between 60 and 86400","code":"invalid_request","parameter":"bucket_seconds",…}` |
| Data v2 `as_of=S+150` | 1 | `{"timestamp":1793878350,"price":0.965,"resolution_seconds":0}` |
| Data v2 `interval=max` | 4 | grain 12 h + point terminal |

Conclusions :
- La **résolution minimale est 1 minute** sur les deux routes, soit **environ 5 points par fenêtre de 5 min**. Ces historiques ne suffisent pas pour backtester du scalping intra-fenêtre [DÉDUIT].
- Pour du tick-by-tick, il faut soit `/v2/trades?condition=…` (timestamps à la seconde, voir A.6), soit enregistrer soi-même le WS `market`.
- La rétention v2 est graduée : 1 min ≥ 7 j, 5 min ≥ 60 j, 30 min ≥ 90 j ; les grains 3 h et 12 h sont permanents (depuis 2022-11-18). `start`/`end` est plafonné à **15 jours** [VÉRIFIÉ doc officielle, OpenAPI v2]. Le changelog du 2026-09-04 dit que « `GET /v2/prices-history` replaces the CLOB-hosted route », mais **la route CLOB répond toujours** [VÉRIFIÉ appel réel].
- Format CLOB : `{"history":[{"t":1793878396,"p":0.985},…]}`. Format v2 : `{"data":[{"timestamp":…,"price":…,"resolution_seconds":60}],"pagination":{…}}`.

### A.6 Data API v2 (`https://data-api.polymarket.com/v2`)

**Calendrier** [VÉRIFIÉ doc officielle, [changelog](https://docs.polymarket.com/changelog/predictions.md)] :
- v2 sortie le **2026-09-04**.
- v1 gelée puis **retirée le 2026-11-02**, avec `/v1/accounting/snapshot` (ZIP/CSV) qui n'a pas de remplaçant.
- La route `/v2/tokens` a été ajoutée le 2026-10-07.

**Retrait v1 confirmé** [VÉRIFIÉ appel réel] : `/activity`, `/positions`, `/value`, `/holders`, `/trades` et `/v1/leaderboard` renvoient tous
```
HTTP 410 {"error":"Data API v1 has been retired","migration":"https://data-api.polymarket.com/v2/","docs":"https://docs.polymarket.com/api-reference/data-api/overview"}
```

**Contrat v2** [VÉRIFIÉ doc officielle + appel réel] :
- Envelope `data` plus `pagination: {limit, offset (affichage seulement), has_more, next_cursor}`.
- Pagination par **curseur uniquement**. `offset` → `400 "'offset' is not a query param on this API: pages are cursor-only…"` et `market` → `400 "'market' is not a query param on this API: filter by condition id with 'condition'…"` [VÉRIFIÉ appel réel].
- Paramètres acceptés en snake_case ou camelCase ; réponses en snake_case. `condition` accepte jusqu'à 20 IDs.
- Montants en nombres JSON : `size` en shares, `_usdc` en USD.
- `outcome_index: 999` signifie « non étiqueté ». C'est le cas sur le **flux global** `/v2/trades` (avec `event_slug` vide), mais pas quand on filtre par `condition` (`outcome_index` 0 ou 1) [VÉRIFIÉ appel réel].
- Erreurs `{error, code, retryable, trace_id}` ; `429` ou `503` avec `Retry-After` ; header `x-trace-id`.

**Endpoints** ([OpenAPI v2](https://data-api.polymarket.com/v2/openapi.json), version 0.1.0) [VÉRIFIÉ appel réel du fichier] :
- `/v2/trades` : `user`, `condition`, `event_id`, `side`, `taker_only` (true par défaut), `filter_type` CASH|TOKENS, `filter_amount`, `start`, `end`, `limit` ≤ 1000, `cursor`.
- `/v2/activity` : `user`, `type`, `condition`, `event_id`, `side`, `start`, `end`, `sort_by`, `sort_direction`, `exclude_deposits_withdrawals`.
- `/v2/positions` : `status` OPEN | REDEEMABLE | REDEEMABLE_LOST | MERGEABLE | CLOSED, plus `title`, `sort_by`, `start`/`end`, `include_archived`.
- `/v2/value`, `/v2/holders` (`include_pnl`), `/v2/oi`, `/v2/live-volume`, `/v2/leaderboard`, `/v2/biggest-winners`, `/v2/builders/{leaderboard,volume}`, `/v2/user-pnl`, `/v2/user-stats`, `/v2/user-volume`, `/v2/prices-history`, `/v2/resolutions`, `/v2/tokens`, `/v2/approvals`, `/v2/status`.

**Profondeur historique** [VÉRIFIÉ doc officielle] :
- `/v2/trades?user=` : `start=1` donne tout l'historique ; un `start` omis ou à 0 remonte à 3 ans.
- `condition` ou `event_id` : fenêtre fixe de 3 ans.
- **Flux global** (sans filtre) : mois courant plus mois précédent.
- Keyset stable par `(block_timestamp, sequence_id)`.

**Test réel sur le marché résolu `btc-updown-5m-1793878200`** [VÉRIFIÉ appel réel] :
- `taker_only=true` : **949 trades** en une page. `taker_only=false` : plus de 1 000 lignes, avec `next_cursor`.
- 104 trades (1,6 k$) **avant** l'ouverture de la fenêtre, le premier 2 000 s avant. **843 trades (14,9 k$) pendant les 300 s.** 2 trades à 0,999 dans les 54 s qui suivent la fin.
- 185 timestamps distincts : les **timestamps sont à la seconde** (temps de bloc).
- Évolution du prix Up par tranches de 30 s : 0,60–0,66 → 0,60–0,64 → 0,60–0,73 → 0,60–0,86 → 0,85–0,97 → 0,94–0,99 → 0,98–0,99 → 0,99 → 0,999.
- Ligne type : `{"proxy_wallet","side":"SELL","token_id","condition_id","size":37.83,"price":0.999,"timestamp":1793878554,"title","slug":"btc-updown-5m-1793878200","icon","event_slug","outcome":"Up","outcome_index":0,"name","pseudonym","bio","profile_image","profile_image_optimized","transaction_hash"}`.
- Des prix non arrondis au tick existent (`0.5997001499`, `0.9299999888`). Ce sont probablement des matchs par mint/merge de la paire complémentaire, dont le prix effectif est 1 − prix opposé [SUPPOSÉ].

Autres routes testées [VÉRIFIÉ appel réel] :
- `/v2/resolutions?condition=…` → `{"status":"resolved","was_disputed":false,"payouts":[1000000,0],"resolution_source":"reported","resolved_at":"2026-11-05T11:36:19Z","resolved_block":96782082,…}`.
- `/v2/tokens?condition=…` → `module:"v1_ctf"`, `opposite_token_id`, `final_price`.
- `/v2/status` → `lag_seconds:1`, `max_synced_block` (fraîcheur d'indexation d'environ 1 à 2 s).
- `/v2/user-stats` d'un trader 5 m actif → `volume_usdc 260 241`, `fees_paid −3 243`, `maker_rebate +295`, `taker_rebate +165,6`, `realized_pnl −4 135`. Anecdotique (un seul wallet public), mais les frais pèsent 1,25 % du volume, plus que son `trade_pnl` négatif (−913 $).

---

## B. WebSockets

> Non connectés depuis la sandbox (hôtes hors de la liste autorisée). Tout ce qui suit est [VÉRIFIÉ doc officielle], consulté le 2026-11-05 : [Real-Time Data](https://docs.polymarket.com/market-data/realtime-data.md), [Real-Time Order Updates](https://docs.polymarket.com/trading/realtime-order-updates.md), [PolyBolt overview](https://docs.polymarket.com/api-reference/live-data/overview.md), [RTDS → PolyBolt](https://docs.polymarket.com/migrate/rtds-to-polybolt.md), AsyncAPI `https://docs.polymarket.com/asyncapi.json` et `https://ws-live-v2.polymarket.com/asyncapi.json`.

### B.1 Canal `market` : `wss://ws-subscriptions-clob.polymarket.com/ws/market` (public)

**Abonnement** : `{"assets_ids":["<token_id>",…],"type":"market"}`, avec en option `"custom_feature_enabled": true` (pour recevoir `best_bid_ask`, `new_market`, `market_resolved`) et `"initial_dump": false` (pour ne pas recevoir le snapshot initial). Ajout ou retrait à chaud : `{"assets_ids":[…],"operation":"subscribe"|"unsubscribe"}`.

**Heartbeat** : envoyer la trame texte **`PING` toutes les 10 s** ; le serveur répond `PONG`.

**Événements (forme « wire »)** :
- `book` : `{event_type, market (condition_id), asset_id, timestamp (ms, string), hash, bids[{price,size}], asks[…]}`.
- `price_change` : `{event_type, market, price_changes[{asset_id, price, size, side, hash, best_bid, best_ask}], timestamp}`. Format en vigueur depuis le changement du 15 sept. 2025.
- `last_trade_price` : `{event_type, market, asset_id, price, size, fee_rate_bps, side, timestamp, transaction_hash}`.
- `tick_size_change` : `{…, old_tick_size, new_tick_size, timestamp}`.
- `best_bid_ask` : `{…, best_bid, best_ask, spread, timestamp}`. Nécessite `custom_feature_enabled`.
- `new_market` : `{id, question, market, slug, assets_ids[], outcomes[], timestamp}`. Nécessite `custom_feature_enabled`.
- `market_resolved` : `{id, market, assets_ids[], winning_asset_id, winning_outcome, timestamp}`. Nécessite `custom_feature_enabled`.

Le SDK unifié normalise ces messages en `{topic:"market", type, payload:{conditionId, assetId, …}}` ; le marché V2 utilise `assetId` = position ID.

### B.2 Canal `user` : `wss://ws-subscriptions-clob.polymarket.com/ws/user` (authentifié)

- **Abonnement**, à envoyer **immédiatement** après la connexion : `{"auth":{"apiKey","secret","passphrase"},"type":"user","markets":["<condition_id>"]}`. `markets` est optionnel ; `operation: subscribe/unsubscribe` permet de modifier la liste. Heartbeat `PING` toutes les 10 s.
- **Événement `order`** : `type` PLACEMENT | UPDATE | CANCELLATION, `status` LIVE | MATCHED | DELAYED | UNMATCHED | CANCELED, avec `original_size`, `size_matched`, `price`, `order_type`, `expiration`, `timestamp` (ms).
- **Événement `trade`** : `status` MATCHED → MINED → CONFIRMED, ou RETRYING / FAILED (aussi MATCHED_NOT_BROADCASTED). Champs `taker_order_id`, `maker_orders[]`, `trader_side` TAKER|MAKER, `fee_rate_bps`, `match_time`, `transaction_hash` (null au moment du match), `bucket_index`.

### B.3 Prix de référence : RTDS (legacy) → **PolyBolt**

- **RTDS** `wss://ws-live-data.polymarket.com` : sorti le 24 sept. 2025, avec des topics Binance (`crypto_prices`) et Chainlink (`crypto_prices_chainlink`), public, `PING` toutes les 5 s. Il est **legacy pour les prix depuis le 15 sept. 2026**. Le SDK TS annonce le retrait des topics de prix RTDS « one month after the 0.11.0 release » (paquet Python 0.11.0 : 2026-09-23). Seul le topic `activity` reste sur RTDS, et le flux de commentaires est retiré sans remplacement [VÉRIFIÉ doc officielle]. Je n'ai **pas vérifié** si les topics de prix RTDS répondent encore aujourd'hui [SUPPOSÉ : probablement coupés ou en cours de coupure].
- **PolyBolt** `wss://ws-live-v2.polymarket.com/ws` (depuis le 15 sept. 2026) :
  - **Authentification obligatoire avec les credentials CLOB API** : `{"op":"auth","rid":"a1","auth":{"apiKey","secret","passphrase"}}` → `{"op":"authed"}`. Un compte et une clé API sont donc nécessaires même pour de la lecture seule de prix.
  - Abonnement : `{"op":"subscribe","rid":"s1","subscriptions":[{"channel":"price.crypto","filter":{"symbol":"btcusd"}}]}`.
  - Canaux : `price.crypto` (symboles `btcusd ethusd solusd xrpusd dogeusd hypeusd bnbusd zecusd`, **Chainlink par défaut depuis le 2 oct. 2026**, `filter.provider` = `chainlink` ou `pyth` ; **Binance n'est plus proposé**), `price.crypto.twap` (Chainlink seulement, `window_seconds: 60` ; c'est **le flux qui alimente la résolution 5 m / 15 m / 4 h**), `price.equity` et `price.equity.twap`.
  - Envelope : `{"v":1,"channel","seq","ts"(ms),"snapshot"?,"dropped"?,"payload":{"symbol","value"(float),"full_accuracy_value"(string décimale),"timestamp"(ms),"source"}}`. Chaque abonnement reçoit un snapshot des **2 minutes précédentes**. `seq` est dense par connexion et par canal ; `dropped` compte les trames perdues quand le client est trop lent.
  - Le **pas des données** du snapshot d'exemple est de **1 s** pour `price.crypto` (timestamps …057000, …058000, …059000) [VÉRIFIÉ doc, exemple]. La doc ne donne pas de fréquence garantie [DÉDUIT : environ 1 Hz].
  - Limites : 64 abonnements par connexion, 20 trames de (dé)abonnement par seconde, 64 KB par trame, 8 trames d'auth. Le serveur envoie un ping WS toutes les 25 s ; deux pongs manqués → close `4002`. Close codes `4001` (auth), `4002` (consommateur lent), `4003` (draining → reconnecter après un délai aléatoire de 0 à 10 s), `4008` (violation de politique).
  - Correspondance RTDS → PolyBolt : `crypto_prices` (Binance `btcusdt`) → `price.crypto` `btcusd` (**la source passe de Binance à Chainlink**) ; `crypto_prices_chainlink` → `price.crypto` ; `crypto_prices_twap_sixty` → `price.crypto.twap` ; `crypto_prices_twap_thirty` n'a **pas** de remplaçant. Les anciennes trames TWAP étaient en E18 ; PolyBolt envoie une chaîne décimale.

**Conséquence pour le bot** : les marchés 1 h et daily se résolvent sur la **bougie Binance BTC/USDT**, qui n'est plus servie par Polymarket. Il faut un flux Binance direct (WS public Binance) pour ces durées. Pour 5 m / 15 m / 4 h, la référence est `price.crypto.twap` de PolyBolt [DÉDUIT].

---

## C. Marchés crypto « Up or Down » court terme

### C.1 Actifs et durées existant aujourd'hui

Séries Gamma trouvées via `GET /series?slug=<asset>-up-or-down-<rec>` [VÉRIFIÉ appel réel, 2026-11-05]. `vol24h` = `volume24hr` de la série, en $.

| Actif | 5m | 15m | hourly | 4h | daily | monthly |
| - | - | - | - | - | - | - |
| BTC | ✓ (id 10684, créée 2025-11-21, **vol24h 13,66 M$**) | ✓ (10192, 2025-08-09, 3,10 M$) | ✓ (10114, 2025-05-27, 611 k$) | ✓ (10331, 2025-09-24, 68 k$) | ✓ (41, 2023-03-14, 97 k$) | — |
| ETH | ✓ (443 k$) | ✓ (352 k$) | ✓ (133 k$) | ✓ (10 k$) | ✓ (29 k$) | ✓ (0) |
| SOL | ✓ (106 k$) | ✓ (91 k$) | ? | ✓ (2,8 k$) | ? | — |
| XRP | ✓ (38 k$) | ✓ (75 k$) | ✓ (47 k$) | ✓ (1,7 k$) | ✓ (0,4 k$) | — |
| DOGE, BNB, HYPE | ✓ (créées 2026-03-04 / 03-11) | ✓ | ✓ | ✓ | BNB, HYPE | — |
| ZEC | ✓ (2026-08-04, vol 0) | ✓ | — | ✓ | — | — |

- « ? » = slug non trouvé sous ce motif. Ma sonde n'a pas trouvé de « weekly » ; un changelog mentionne pourtant des marchés weekly (2026-03-01) [SUPPOSÉ : slug différent].
- Les marchés « Up or Down » forex et actions existent aussi, résolus sur Pyth (changelog du 2026-10-21) [VÉRIFIÉ doc].
- **BTC 5 m concentre l'essentiel de la liquidité** : 13,7 M$/24 h, soit environ 47 k$ par fenêtre [DÉDUIT].

**Historique** :
- Série BTC 5 m créée le 2025-11-21. Des événements de test existent en déc. 2025 et janv. 2026 : 13 événements restés `closed:false` et `acceptingOrders:null`, des artefacts que Gamma liste encore [VÉRIFIÉ appel réel].
- **Lancement public : 12–13 février 2026**, avec taker fees [VÉRIFIÉ changelog du 2026-02-12, et presse [SUPPOSÉ] : CoinMarketCap, Fortune].
- **Taker fees** : marchés 15 m dès le 2026-01-05 ; tous les marchés crypto (1 h, 4 h, daily, weekly) dès le **2026-03-06** ; « Fee Structure V2 » le 2026-03-30 ; le coefficient lu dans les feeSchedule est 0,072 fin avril (fixture polycopy du 2026-04-25) et **0,07 aujourd'hui** [VÉRIFIÉ appel réel].
- **TWAP Chainlink depuis le 2026-08-07** (30 s pour le 5 m, 60 s pour 15 m et 4 h), puis **60 s aussi pour le 5 m depuis le 2026-08-14, 00:00 UTC** [VÉRIFIÉ changelog]. Le changement suit une étude Stanford/SMU qui estime à environ 8,2 M$ les gains de manipulation du prix de settlement ponctuel [SUPPOSÉ, presse : [crypto.news](https://crypto.news/stanford-study-exposes-polymarket-flaw-rewards-bitcoin/), [cryptodaily](https://cryptodaily.co.uk/2026/08/polymarket-replaces-snapshot-with-chainlink-twap)].
- Le taker delay a varié trois fois (A.3).
- Polymarket US propose aussi des marchés 5 m depuis fin octobre 2026 (voir D) [SUPPOSÉ].

### C.2 Découverte : slugs, séries, cadence de création

| Durée | Format de slug | Exemple vérifié | Source de résolution |
| - | - | - | - |
| 5 m | `{asset}-updown-5m-{ts_start}` | `btc-updown-5m-1793881800` | Chainlink TWAP 60 s |
| 15 m | `{asset}-updown-15m-{ts_start}` | `btc-updown-15m-1793882700` | Chainlink TWAP 60 s |
| 4 h | `{asset}-updown-4h-{ts_start}` | `btc-updown-4h-1793883600` (13:00–17:00 UTC) | Chainlink TWAP 60 s |
| **1 h** | `bitcoin-up-or-down-{month}-{d}-{yyyy}-{h}{am/pm}-et` | `bitcoin-up-or-down-november-5-2026-8am-et` | **Binance BTC/USDT, bougie 1H** |
| **daily** | `bitcoin-up-or-down-on-{month}-{d}-{yyyy}` | `bitcoin-up-or-down-on-november-6-2026` | **Binance BTC/USDT, close 1 m à 12:00 ET** |

`ts_start` est le timestamp Unix du **début** de la fenêtre, multiple de 300 ou de 900. La série et l'événement portent `startTime` / `eventStartTime`, et le marché porte `endDate` [VÉRIFIÉ appel réel].

**Avance de création** (`createdAt` → `eventStartTime`) [VÉRIFIÉ appel réel] :
- 5 m, 15 m, 4 h : environ **24 h moins 7 à 8 min**. Exemple : `btc-updown-5m-1793881800` créé le 2026-11-04 à 12:37:29, `acceptingOrdersTimestamp` 12:37:42 (13 s après), pour une fenêtre qui démarre le 2026-11-05 à 12:30.
- 1 h : **48 h** avant (créé le 2026-11-03 à 13:00 pour le 05 à 13:00).
- Daily : environ 24 h avant le début de la période noon-to-noon ET.
- Le marché est **tradable dès sa création**, mais il est quasi vide avant la fenêtre : `volume:"2"` sur le marché en cours, et 104 trades sur les 33 min qui précèdent la fenêtre, pour l'exemple résolu [VÉRIFIÉ appel réel].
- Environ 96 à 100 événements 5 m sont ouverts en même temps par actif [VÉRIFIÉ appel réel, `/events?series_id=10684&closed=false`].

**Requêtes utiles** [VÉRIFIÉ appel réel] :
- `GET gamma-api.polymarket.com/markets?slug=btc-updown-5m-<ts>` : le marché actif.
- Pour un marché **clos**, il faut ajouter `&closed=true`. Sinon la réponse est `[]` : `closed` vaut `false` par défaut depuis le 2026-04-09.
- `GET /events?slug=…` (inclut `markets[]` et `series[]`), `GET /events?series_id=10684&closed=false&limit=200`, `GET /series?slug=btc-up-or-down-5m`.
- `GET /markets/keyset` et `/events/keyset` (pagination par curseur, `limit` ≤ 100 depuis le 2026-05-14) répondent `{"markets":[…],"next_cursor"}`.
- `clobTokenIds`, `outcomes` et `outcomePrices` restent des **chaînes JSON**. Les marchés `version:"v2"` (Protocol V2) utilisent `positionIds`, un vrai tableau ; tous les marchés crypto observés sont en `version:"v1"` [VÉRIFIÉ appel réel + [doc V2](https://docs.polymarket.com/migrate/polymarket-v2/api-integrations.md)].

**Réponse brute Gamma, marché 5 m en cours** (extrait, `raw/excerpt_gamma_current.json`) [VÉRIFIÉ appel réel, 12:30 UTC] :
```json
{"id":"6675407","question":"Bitcoin Up or Down - November 5, 7:30AM-7:35AM ET",
 "conditionId":"0xdefab1e2881efc28017e616f41a8704c60628311c8444ef397272347509dd9b2","slug":"btc-updown-5m-1793881800",
 "resolutionSource":"https://data.chain.link/streams/btc-usd-twap-60s-streams",
 "startDate":"2026-11-04T12:39:14.482073Z","endDate":"2026-11-05T12:35:00Z","eventStartTime":"2026-11-05T12:30:00Z",
 "createdAt":"2026-11-04T12:37:29.982105Z","acceptingOrdersTimestamp":"2026-11-04T12:37:42Z",
 "outcomes":"[\"Up\", \"Down\"]","outcomePrices":"[\"0.605\", \"0.395\"]",
 "clobTokenIds":"[\"8298250612127404285662398859465419755040566656122291224346404000106470102785 7\", \"9168814990911584038338323164725674576733417051987352409643709881202586345948\"]",
 "active":true,"closed":false,"acceptingOrders":true,"restricted":true,"enableOrderBook":true,
 "orderPriceMinTickSize":0.01,"orderMinSize":5,"negRisk":false,
 "feesEnabled":true,"feeType":"crypto_fees_v2","feeSchedule":{"exponent":1,"rate":0.07,"takerOnly":true,"rebateRate":0.2},
 "makerBaseFee":1000,"takerBaseFee":1000,"makerRebatesFeeShareBps":10000,"rewardsMinSize":50,"rewardsMaxSpread":4.5,
 "cryptoMarketConfigId":"btc-5m-twap-60","cryptoMarketConfig":{"id":"btc-5m-twap-60","asset":"btc","duration":"5m","twapEnabled":true,"twapLookbackSeconds":60},
 "resolutionMechanism":"oracle","fallbackResolutionType":"none","umaResolutionStatuses":"[]","clearBookOnStart":false,
 "rfqEnabled":false,"holdingRewardsEnabled":false,"tradingEligible":true,
 "volume":"2","liquidity":"16431.343","bestBid":0.52,"bestAsk":0.53,"spread":0.01,"lastTradePrice":0.54,"version":"v1"}
```
(Dans l'extrait, l'espace dans le premier tokenId est une coupure de mise en page. La valeur exacte est `82982506121274042856623988594654197550405666561222912243464040001064701027857`.)

### C.3 Résolution

**Description Gamma, mot pour mot (5 m, 15 m et 4 h identiques)** [VÉRIFIÉ appel réel] :
> This market will resolve to "Up" if the time-weighted average price (TWAP) of Bitcoin, generated by Chainlink, of the time range specified in the title is greater than or equal to the price at the beginning of that range. Otherwise, it will resolve to "Down".
> The resolution source for this market is information from Chainlink, specifically the BTC/USD TWAP data stream available at https://data.chain.link/streams/btc-usd-twap-60s-streams.
> Please note that this market is about the price according to the TWAP Chainlink data stream for the asset pair BTC/USD, not according to any other sources or spot markets.

**Ancienne description (5 m, déc. 2025, avant le TWAP)** [VÉRIFIÉ appel réel sur un événement résiduel] : « …if the Bitcoin price at the end of the time range … is greater than or equal to the price at the beginning … Chainlink … BTC/USD data stream https://data.chain.link/streams/btc-usd ».

**1 h (mot pour mot)** [VÉRIFIÉ appel réel] :
> This market will resolve to "Up" if the close price is greater than or equal to the open price for the BTC/USDT 1 hour candle that begins on the time and date specified in the title. Otherwise, this market will resolve to "Down". The resolution source for this market is information from Binance, specifically the BTC/USDT pair (https://www.binance.com/en/trade/BTC_USDT). The close « C » and open « O » displayed at the top of the graph for the relevant "1H" candle will be used once the data for that candle is finalized. …

**Daily** : comparaison de la clôture de la **bougie Binance 1 m de 12:00 ET** du jour J−1 avec celle du jour J. En cas d'**égalité exacte, résolution 50-50** [VÉRIFIÉ appel réel].

**Price to beat et règle d'égalité** :
- « The TWAP at the start sets the **price to beat**. When the duration ends, the TWAP at that time sets the **final price**. … resolves **Up** when the final price is **equal to or greater** than the price to beat. » [VÉRIFIÉ doc [Resolution](https://docs.polymarket.com/concepts/resolution.md)]
- L'égalité donne **Up** sur 5 m, 15 m, 4 h et 1 h (≥), mais **50-50** sur le daily.
- Avec `twapLookbackSeconds: 60`, je comprends le price to beat comme le TWAP sur [start−60 s, start] et le final comme le TWAP sur [end−60 s, end] [DÉDUIT de la doc, non formulé explicitement].

**Chaînage vérifié** [VÉRIFIÉ appel réel] :
- Gamma `events[0].eventMetadata` = `{"priceToBeat": …, "finalPrice": …}`. Sur 12 fenêtres consécutives de 11:35 à 12:35 UTC, **priceToBeat(N) = finalPrice(N−1)** au bit près. Exemple : `btc-updown-5m-1793878500` a `priceToBeat` 80261.08159416831, qui est exactement le `finalPrice` de `…1793878200`.
- **Ces champs n'apparaissent qu'après la fin de la fenêtre** : à 219 s dans la fenêtre en cours, `eventMetadata` vaut `None`, et `priceToBeat` n'est apparu sur la fenêtre précédente qu'une fois celle-ci terminée.
- En temps réel, il faut donc reconstruire le price to beat depuis `price.crypto.twap` (PolyBolt).
- Endpoint frontend **non documenté** `GET https://polymarket.com/api/crypto/crypto-price?symbol=BTC&eventStartTime=…&variant=fiveminute&endDate=…` → `{"openPrice":79990.935…,"closePrice":79892.155…,"completed":true,…}`. Ses valeurs **ne correspondent pas** au `priceToBeat` et au `finalPrice` TWAP de Gamma (79993.98 / 79852.09 pour la même fenêtre), probablement parce qu'il donne un spot Chainlink. Il ne faut **pas** s'en servir comme référence de résolution [VÉRIFIÉ appel réel ; sémantique SUPPOSÉE].

**Mécanique** :
- `resolutionMechanism:"oracle"`, `automaticallyResolved:true`, `umaResolutionStatuses:"[]"` : pas d'UMA, donc pas de proposition ni de dispute pour ces marchés [VÉRIFIÉ appel réel + doc].
- **Délai de résolution mesuré : 79 s dans 10 cas, 81 s dans 2 cas, après `endDate`** (`closedTime` Gamma). Même horodatage dans `/v2/resolutions.resolved_at` [VÉRIFIÉ appel réel].
- Entre la fin et la résolution, le carnet reste ouvert (trades à 0,999 jusqu'à +54 s).
- Contrats on-chain : `ChainlinkReporterModule` et `AutoRedeemer` (Poly v2). L'indexeur Data API montre des sources `auto_redeem_*`, et `/v2/positions` renvoie le statut `REDEEMABLE` [VÉRIFIÉ doc [Contracts](https://docs.polymarket.com/resources/contracts.md) + `/v2/status`].
- L'auto-redeem semble actif pour le compte via les wallets Polymarket [SUPPOSÉ : non testé sans compte]. Sinon, le redeem manuel passe par le CTF ou le Router.
- Je n'ai pas pu ouvrir `data.chain.link` (hôte hors liste).

### C.4 Frais

**Formule** [VÉRIFIÉ doc [Fees](https://docs.polymarket.com/trading/fees.md) + code `fees.py` du SDK 1.2.1] : `fee = C × feeRate × p × (1 − p)`, avec C en shares et p le prix du trade.
- Crypto : `feeRate = 0.07`, exponent 1, taker only.
- Fees « set at match time », pas de `feeRateBps` dans l'ordre.
- Arrondi à 5 décimales ; le minimum facturé est 0,00001 pUSD.
- Le maker ne paie jamais.

**Lecture par l'API** [VÉRIFIÉ appel réel] :
- `GET /clob-markets/{cid}` → `"fd":{"r":0.07,"e":1,"to":true}`.
- Gamma → `"feeSchedule":{"exponent":1,"rate":0.07,"takerOnly":true,"rebateRate":0.2}`, plus `feesEnabled:true` et `feeType:"crypto_fees_v2"`.
- `GET /fee-rate?token_id=` → `{"base_fee":1000}`, un champ hérité qui n'est pas un taux exploitable. L'OpenAPI l'appelle « base fee rate ». Depuis le 2026-03-31, la doc dit de calculer les frais avec `feeSchedule`.

**Tableau des frais taker (crypto, rate 0,07)** [DÉDUIT par calcul, recoupé avec le tableau officiel pour 100 shares : 0,33 $ à p = 0,05 et 1,75 $ à p = 0,50]

| p | Frais $/share | **Frais ¢/share** | **Frais % du notional** = 7 %·(1−p) | A/R taker/taker au même prix (¢/share ; % du notional) | A/R maker/taker (¢/share) | A/R maker/maker | Rebate maker estimé ≈ 20 % (¢/share) |
| - | - | - | - | - | - | - | - |
| 0,05 | 0,003325 | **0,333** | **6,65 %** | 0,665 ; 13,3 % | 0,333 | 0 (+ rebates) | ≈ 0,067 |
| 0,15 | 0,008925 | **0,893** | **5,95 %** | 1,785 ; 11,9 % | 0,893 | 0 | ≈ 0,179 |
| 0,20 | 0,011200 | **1,120** | **5,60 %** | 2,240 ; 11,2 % | 1,120 | 0 | ≈ 0,224 |
| 0,50 | 0,017500 | **1,750** | **3,50 %** | 3,500 ; 7,0 % | 1,750 | 0 | ≈ 0,350 |
| 0,60 | 0,016800 | **1,680** | **2,80 %** | 3,360 ; 5,6 % | 1,680 | 0 | ≈ 0,336 |
| 0,85 | 0,008925 | **0,893** | **1,05 %** | 1,785 ; 2,1 % | 0,893 | 0 | ≈ 0,179 |
| 0,95 | 0,003325 | **0,333** | **0,35 %** | 0,665 ; 0,7 % | 0,333 | 0 | ≈ 0,067 |

**Seuils de rentabilité d'un aller-retour taker/taker** [DÉDUIT] : la sortie doit être meilleure de **≈ 3,5 ¢ à p = 0,5**, ≈ 2,3 ¢ à p = 0,2 et ≈ 2,15 ¢ à p = 0,8, **en plus du spread** payé deux fois (1 tick, soit 1 ¢ observé). À p ≈ 0,5, il faut donc environ **4,5 ¢ de mouvement favorable** pour finir à zéro. En maker/maker, le coût en frais est nul et l'on touche une part des rebates, mais on reste exposé à l'adverse selection et au taker delay de 150 ms qui protège les makers.

**Rebates, rewards, builder** [VÉRIFIÉ doc officielle] :
- **Maker Rebates** ([doc](https://docs.polymarket.com/programs/maker-rebates.md)) : pour le crypto, **20 % des taker fees** du marché, répartis au prorata de votre `fee_equivalent = C × 0.07 × p(1−p)` sur vos fills maker, **par marché** (chaque marché 5 m est un pool à part). Payés chaque jour en pUSD, minimum 1 $. Lecture via `GET /rebates/current?date=&maker_address=` (public). Gamma affiche aussi `makerRebatesFeeShareBps:10000`, champ non documenté [SUPPOSÉ : 100 % du pool reversé aux makers].
- Historique des rebates : sports passés de 25 % à 15 % le 2026-07-10, avec un taux sports porté de 0,03 à 0,05.
- **Taker Rebate Program** (depuis le **2026-05-28**, [doc](https://docs.polymarket.com/programs/taker-rebates.md)) : `wV = taille($) × (1 − prix d'entrée) × poids de catégorie (Crypto 2,3)`. Paliers sur le wV des 30 derniers jours : Bronze ≥ 2 k$ → 3 %, Silver ≥ 20 k$ → 8 %, Gold ≥ 200 k$ → 18 %, Platinum ≥ 1 M$ → 32 %, Diamond ≥ 4 M$ → 44 %, Obsidian ≥ 10 M$ → 50 %, avec des bonus de palier de 10 $ à 25 k$. Payé quotidiennement. Exclu en cas de wash trading ou de self-matching. Le % porte vraisemblablement sur les taker fees payées [SUPPOSÉ : la doc ne le dit pas noir sur blanc]. Exemple : 1 k$/jour de taker à p ≈ 0,5 donne environ 34 k$ de wV sur 30 j, donc Silver (8 %), et des frais nets d'environ 3,22 % au lieu de 3,5 % [DÉDUIT].
- **Liquidity Rewards** ([doc](https://docs.polymarket.com/programs/liquidity-rewards.md)) : score quadratique `S = ((v − s)/v)²` sur les ordres dans `max_spread` (4,5 ¢) et au-dessus de `min_size` (50 shares). Le **double-sided** est obligatoire si le mid est < 0,10 ou > 0,90 ; en single-sided, le score est divisé par c. Échantillonnage chaque minute, 1 440 échantillons par jour, paiement à minuit UTC, minimum 1 $. Sur les marchés crypto, le taker delay **n'impose pas** d'âge minimum d'ordre. `/clob-markets` indique `r.moas: 30` (min order age 30 s ?) : **contradiction possible avec la doc** [VÉRIFIÉ appel réel ; interprétation SUPPOSÉE].
- **Builder** ([fees](https://docs.polymarket.com/programs/builders/fees.md), [tiers](https://docs.polymarket.com/programs/builders/tiers.md)) : un builder code bytes32 sur l'ordre permet de facturer un **builder fee** en plus de la fee plateforme (taker ≤ 100 bps, maker ≤ 50 bps ; 0 par défaut). Paliers Unverified (100 tx relayer/jour), Verified (10 k) et Partner. Pour un bot perso, un builder code sur ses propres ordres n'apporte rien de direct, sauf le classement au leaderboard. L'estimation de polycopy de 50 à 150 $/an de « fee rebates » via builder n'est **pas étayée** par la doc actuelle [DÉDUIT].

**Changements de frais en 2026** [VÉRIFIÉ changelog] :
- 01-05 : fees sur les 15 m crypto (pic 1,56 %).
- 02-12 : 5 m lancés avec fees.
- 03-06 : tous les marchés crypto.
- 03-30 : Fee Structure V2 (catégories).
- 03-31 : calcul des frais à partir de `feeSchedule`.
- 04-28 : fees fixées au moment du match (V2).
- 07-10 : sports à 0,05.
- Le crypto à **0,07** est le tableau actuel. Le changement 0,072 → 0,07 n'est pas daté dans le changelog [DÉDUIT].
- Le « 1,56 % au pic » de janvier–février est l'ancienne courbe (rate 0,25, exponent 2 dans la formule avec facteur p). La courbe actuelle donne **3,5 % du notional au pic**, soit environ 2,2 fois plus [DÉDUIT].

### C.5 Microstructure : carnets réels du marché 5 m en cours

4 prélèvements espacés de 61 s via `GET /book?token_id=` sur les deux tokens. Fichiers `raw/books/*.json` et `raw/book_samples_condensed.json` [VÉRIFIÉ appel réel] :

| # | UTC (epoch) | Marché | s dans la fenêtre | Up : bid / ask (spread) | Down : bid / ask | Niveaux Up (bids/asks) | Profondeur à ±5 ¢ du mid, Up (bids \| asks) | tick / min / neg_risk |
| - | - | - | - | - | - | - | - | - |
| 1 | 1793882052 | `…1793881800` | **252** | — / **0,001** | **0,999** / — | 0 / 121 | n/a (marché décidé) | **0,001** / 5 / false |
| 2 | 1793882113 | `…1793882100` | 13 | 0,54 / 0,55 (0,01) | 0,45 / 0,46 | 54 / 45 | 2 346 sh / 1 211 $ \| 4 612 sh / 2 615 $ | 0,01 / 5 / false |
| 3 | 1793882174 | `…1793882100` | 74 | 0,21 / 0,22 (0,01) | 0,78 / 0,79 | 21 / 78 | 4 408 sh / 815 $ \| 4 457 sh / 1 064 $ | 0,01 / 5 / false |
| 4 | 1793882235 | `…1793882100` | 135 | 0,26 / 0,27 (0,01) | 0,73 / 0,74 | 26 / 73 | 4 254 sh / 1 035 $ \| 1 379 sh / 396 $ | 0,01 / 5 / false |

**Top 5 bruts** :
- #2 Up — bids `0.54×237.97, 0.53×354, 0.52×576, 0.51×594.78, 0.50×583.39` ; asks `0.55×301.06, 0.56×2489.9, 0.57×809.23, 0.58×315, 0.59×696.47`.
- #3 Up — bids `0.21×118.93, 0.20×408.55, 0.19×1774.01, 0.18×1273.55, 0.17×832.91` ; asks `0.22×1165.14, 0.23×689, 0.24×594, 0.25×1530, 0.26×479`.
- #4 Up — bids `0.26×924.2, 0.25×519.75, 0.24×2180, 0.23×269, 0.22×361.09` ; asks `0.27×123.18, 0.28×632.14, 0.29×265, 0.30×205, 0.31×154`.
- #1 (fin de fenêtre) Down — bids `0.999×4847.4, 0.998×200, 0.997×220, 0.996×237.5, 0.995×418.14`.

**Observations** [VÉRIFIÉ appel réel sauf mention contraire] :
- **Carnets miroir** : Up bid p ⇔ Down ask 1−p, avec des tailles identiques (#2 : Up 54/45 niveaux ⇔ Down 45/54). C'est un carnet unique, matché par complémentarité.
- Le champ `last_trade_price` du book est **identique sur les deux tokens** (0,460 sur Up comme sur Down, alors que le mid Up valait 0,545). Il reflète le dernier trade du **marché**, pas celui du token [DÉDUIT : ne pas l'utiliser comme prix du token].
- L'ordre brut renvoyé par `/book` met les **bids croissants et les asks décroissants : le meilleur prix est en fin de liste**. Il faut trier côté client.
- `timestamp` en ms (string) et `hash` sont présents.
- Le spread est toujours **1 tick**. La profondeur à ±5 ¢ va d'environ 0,4 k$ à 5 k$ par côté, et la presse cite 5 à 15 k$ par côté en séance active [SUPPOSÉ, presse].
- Le volume par fenêtre 5 m BTC va de **32 k$ à 73 k$, 46 k$ en moyenne** (11 fenêtres complètes de 11:35 à 12:30 UTC, `volumeNum` Gamma). La fenêtre la plus récente n'affichait encore que 2,6 k$ : le compteur de volume Gamma est en retard.
- **Mouvements violents** : le mid Up passe de 0,545 à 0,215 en 61 s (#2 → #3). Dans le marché résolu analysé (A.6), le prix converge vers 0,99 dès environ 180 s sur 300. Le gros du risque directionnel se joue dans la première moitié de la fenêtre, et la fenêtre TWAP finale (240–300 s) est souvent déjà décidée [DÉDUIT de 2 fenêtres : échantillon minuscule].
- Pour comparaison, le 15 m `…1793881800` à 803 s sur 900 était déjà à 0,999/0,001 avec un tick de 0,001.

---

## D. Accès légal (Suisse) — pas un conseil juridique

**Liste officielle de geoblock** ([Geographic Restrictions](https://docs.polymarket.com/api-reference/geoblock.md), consulté le 2026-11-05) [VÉRIFIÉ doc officielle] :
- **Blocage complet (OFAC)** : IR, SY, CU, KP, UA-43 (Crimée), UA-14 (Donetsk), UA-09 (Louhansk).
- **Close-only sur le frontend et l'API** : AR, AU, BY, BE, BI, BR, CA-BC, CA-ON, CA-AB, CA-QC, CF, CD, ET, **FR, DE, IT, PL, SK, GB**, IQ, LB, LY, MM, NZ, NI, RU, SG, SO, SS, SD, TW, TH, **US**, UM, VE, YE, ZW.
- **Close-only sur le frontend uniquement (l'API n'est pas restreinte)** : IE, JP, MT (sport), NL, KR.
- **La Suisse (CH) n'y figure pas.** Ni l'Autriche, ni le Liechtenstein.

**Endpoint** `GET https://polymarket.com/api/geoblock` [VÉRIFIÉ appel réel] → `{"blocked":true,"ip":"160.79.106.132","country":"US","region":"OH"}`. C'est l'IP de la sandbox, située aux États-Unis. La doc précise : « Orders submitted from blocked regions will be rejected ».

**Terms of Use** (`https://polymarket.com/tos`, « Effective as of August 11, 2026 ») [VÉRIFIÉ appel réel] :
- Interdiction de trader pour les personnes situées ou résidant aux « UNITED STATES OF AMERICA, ALBERTA, AUSTRALIA, BELGIUM, BRITISH COLUMBIA, FRANCE, GERMANY, HUNGARY, IRELAND, ITALY, ONTARIO, POLAND, QUEBEC, RUSSIA, SINGAPORE, SLOVAKIA, SLOVENIA, TAIWAN, THAILAND, THE NETHERLANDS, NEW ZEALAND, THE UNITED KINGDOM », plus toute juridiction de la liste geoblock.
- **Divergence** : les ToS citent la Hongrie, la Slovénie, l'Irlande et les Pays-Bas, absents de la liste geoblock ou seulement close-only frontend. **CH n'est pas citée.**
- « USE OF A VIRTUAL PRIVATE NETWORK ("VPN") OR ANY SIMILAR TOOL TO … CIRCUMVENT THE RESTRICTIONS … IS STRICTLY PROHIBITED. ANY PERSON IN VIOLATION … MAY HAVE THEIR WALLETS PLACED IN CLOSE-ONLY MODE ».
- **Automatisation** :
  - L'API et les bots de trading ne sont pas interdits en tant que tels (il existe un programme builder, des docs de market making et une co-location).
  - Sont interdits : le spoofing (« placing any buy or sell order without a bona fide intent to transact and with the intent to cancel before execution »), le wash trading, le self-matching, le front-running, le scraping par « robots, crawlers » du **site**, et le fait de « overburden » l'interface.
  - Restriction notable sur les **Data** : interdiction d'accéder aux données « directly or through an API » pour les « Capital Market Clients » (prop trading firms, hedge funds, market makers professionnels…) sans accord écrit. C'est à prendre en compte si le développeur opère via une structure professionnelle [VÉRIFIÉ ToS].
  - Polymarket peut demander des informations (KYC) et couper l'accès à sa discrétion.
- Un quote-and-cancel agressif près de la limite du spoofing est un **risque de compte** (close-only, retrait des rebates) [DÉDUIT].

**Suisse — Gespa, LJAr/BGS** :
- Polymarket.com figure sur la **liste de blocage de la Gespa** (Interkantonale Geldspielaufsicht) **depuis le 26.11.2024**. Le 25.08 (2026 selon la liste Gespa citée, l'année est ambiguë selon d'autres sources), les clones `polymarket-swiss.ch`, `polymarketschweiz.ch`, `polymarketsuisse.ch` et `polymarketswitzerland.ch` ont été ajoutés. Kalshi est aussi bloqué [SUPPOSÉ : WebSearch, sources [SRF](https://www.srf.ch/news/wirtschaft/boom-von-prognosemaerkten-wie-mit-kriegswetten-milliarden-verdient-werden), [bluewin](https://www.bluewin.ch/de/news/schweiz/polymarket-10-millionen-schweiz-li.3279945), [20 Minuten](https://www.20min.ch/story/polymarket-und-kalshi-100-000-dollar-netz-wettet-auf-nein-zur-10-millionen-initiative-103568749), [jamma.it](https://www.jamma.it/attualita/gespa-aggiorna-la-blacklist-polymarket-tra-i-52-nuovi-siti-di-gioco-bloccati-357532), [sigma.world](https://sigma.world/news/swiss-prediction-market-guide-sites-blocked/) ; la liste elle-même est [blocklist.gespa.ch](https://blocklist.gespa.ch/comlot_blacklist.pdf), que je n'ai pas pu ouvrir].
- Le blocage est **DNS, au niveau des FAI** (art. 86 al. 3 BGS / LJAr, listes Gespa et ESBK). Fin 2025, la liste Gespa comptait 671 domaines selon son rapport annuel [SUPPOSÉ, WebSearch]. Le Tribunal fédéral a confirmé en 2026 le principe du blocage de domaine pour un autre opérateur [SUPPOSÉ].
- **Joueur** : selon la Gespa, SRF et un merkblatt du canton de Schwyz, jouer sur un site bloqué **n'est pas punissable pour le joueur**. Les sanctions de la LJAr visent l'organisateur. En revanche, il n'y a **aucune protection juridique** en cas de perte [SUPPOSÉ, presse et merkblätter cantonaux].
- Le blocage DNS se contourne techniquement, par exemple avec un autre résolveur. C'est **légalement gris côté CH** et **contraire aux ToS si l'on utilise un VPN pour contourner un geoblock Polymarket**. Or **CH n'est pas geobloquée par Polymarket**, le blocage est uniquement suisse [DÉDUIT].
- **ESBK** (jeux de casino) et **Gespa** (jeux de grande envergure, loteries et paris) tiennent chacune leur liste. Polymarket est sur celle de la Gespa [SUPPOSÉ].

**KYC** :
- Le site international ne demande pas de KYC systématique pour un wallet (Deposit Wallet ou Safe), mais Polymarket « may request additional information » [VÉRIFIÉ ToS].
- La **co-location** exige un formulaire KYC/KYB [VÉRIFIÉ doc].
- Les dépôts via bridge passent par Fun.xyz, avec de possibles « compliance-held » [VÉRIFIÉ changelog du 2026-04-13].

**Polymarket US** :
- Application régulée CFTC (via QCX LLC), réservée aux résidents US.
- 15 m BTC Up/Down depuis le 22 sept. 2026, 5 m BTC/ETH/SOL/XRP depuis le 27–28 oct. 2026, d'après la presse [SUPPOSÉ : [cryptobriefing](https://cryptobriefing.com/polymarket-us-five-minute-crypto-markets/), [predictionnews](https://predictionnews.com/story/polymarket-launches-5-minute-crypto-up-down-markets-on-us-app), [coindesk du 2026-10-29](https://www.coindesk.com/markets/2026/10/29/polymarket-brings-ultra-short-crypto-prediction-markets-to-u-s-platform)].
- **Sans objet pour un résident suisse.**

**Fiscalité suisse (aperçu, pas un conseil)** :
- Selon les merkblätter cantonaux (SZ, SG, TG, ZH) trouvés par WebSearch, les **gains de jeux d'argent chez des opérateurs étrangers ou non autorisés sont entièrement imposables** au titre du revenu (art. 16 al. 1 DBG). Les exonérations de l'art. 24 let. i/iter DBG ne visent que les jeux autorisés selon la LJAr. Pas d'impôt anticipé [SUPPOSÉ : sources cantonales via WebSearch, p. ex. [Merkblatt SZ](https://www.sz.ch/public/upload/assets/92415/Merkblatt_Besteuerung_von_Geldspielgewinnen_ME-NP-22.pdf?fp=4), [ESTV](https://www.estv.admin.ch/de/geldspielgewinne-und-geldspielgesetz), [TG StP 25 Nr. 6](https://steuerpraxis.tg.ch/steuerpraxis/2025-10/stp-25-nr-6-gewinne-aus-geldspielen)].
- Une lecture alternative assimile les gains à des gains en capital privé, exonérés hors activité de « commerçant professionnel ». Des blogs l'avancent, sans fondement officiel pour ce cas précis [SUPPOSÉ].
- Un bot de scalping à haute fréquence a de fortes chances d'être vu comme une **activité lucrative indépendante** ou comme des gains de jeu imposables, d'où l'intérêt d'un ruling cantonal. Les pertes ne sont en principe pas déductibles en tant que gains de jeu [SUPPOSÉ].
- La fortune en pUSD/USDC est imposable au titre de l'impôt sur la fortune [SUPPOSÉ].

---

## E. Écarts vs les hypothèses de polycopy

| Hypothèse polycopy (CLAUDE.md / code) | État au 2026-11-05 | Statut | Preuve |
| - | - | - | - |
| `py-clob-client-v2==1.0.0` | 1.2.1 (2026-10-15) ; paquet **déprécié** au profit de `polymarket-client` 0.16.0. 1.0.0 n'a ni les ticks 0.005/0.0025, ni la résolution des tx hash depuis `tradeIDs` (réponses FAK/FOK modifiées le 24 juillet), ni `position_id` | **Changé (risque)** | PyPI, diff des wheels, changelog du 2026-07-17 |
| `OrderType` = classe à attributs | Toujours vrai (GTC/FOK/GTD/FAK) | OK | `clob_types.py` 1.2.1 |
| `PartialCreateOrderOptions(tick_size, neg_risk)` | Toujours vrai, plus un champ `version: Optional[int]` (V1/V2/V3) | OK, avec ajout | idem |
| `create_or_derive_api_key` | Toujours vrai | OK | `client.py` 1.2.1 |
| Signature types 0/1/2 | Nouveau type **3 = DEPOSIT_WALLET (POLY_1271)**, par défaut pour les comptes créés depuis le 4 mai 2026 | **Ajout** | doc Wallets |
| `/fee-rate?token_id=` → `{"base_fee": …}` binaire | Toujours `{"base_fee":1000}` ; à ne pas utiliser comme taux | OK | appel réel |
| `/clob-markets/{cid}` → `fd:{r,e}` | `fd:{r:0.07,e:1,to:true}` ; **r = 0,07 (et non 0,072)**. Autres clés réelles : `c`, `t[{t,o}]`, `mos`, `mts`, `mbf`, `tbf`, `ao`, `aot`, `itode`, `r{mi,ma,moas}`, `v`. La fixture polycopy `clob_v2_market_crypto_sample.json` est **synthétique** (`cid`, `t[{id,o}]`, `ms`, `qid`, `nr`, `cs`, `tr` ne correspondent pas au réel) | **Changé (valeur + fixture)** | appel réel |
| **Calcul des frais** : `fee = notional × r × p(1−p)` (`pipeline.py`) | Officiel : `fee = shares × r × p(1−p)`. **Sous-estimation ×1/p** (à p = 0,5, polycopy compte 0,875 ¢/share au lieu de 1,75 ¢) | **Faux** | doc Fees (tableau 100 shares), `fees.py` du SDK |
| Fallback `0.018` (1,8 %) worst-case | Le pic réel est **3,5 % du notional** à p = 0,5, et jusqu'à 6,65 % à p = 0,05 | **Faux** | idem |
| `/midpoint` → `{"mid": "…"}` | Toujours vrai (`{"mid":"0.355"}`) | OK | appel réel |
| WS market channel `wss://ws-subscriptions-clob…/ws/market` | URL inchangée. Nouveautés : `custom_feature_enabled`, `initial_dump`, `operation subscribe/unsubscribe`, `PING` 10 s ; `price_change.price_changes[]` avec `best_bid`/`best_ask` | OK, avec ajouts | doc |
| Gamma `clobTokenIds` JSON-stringifié | Toujours vrai sur les marchés `version:"v1"`. Les marchés `"v2"` utilisent `positionIds` (vrai tableau). Gamma `/markets` exclut les clos par défaut (`closed=true` requis) | OK, avec piège | appel réel + doc |
| **Data API v1** `/activity`, `/trades`, `/positions`, `/value`, `/holders` (camelCase) | **HTTP 410 depuis le 2026-11-02**. v2 : `/v2/…`, snake_case, curseur, `condition` au lieu de `market`, `offset` interdit. Utilisé dans polycopy par `watcher/data_api_client.py`, `executor/wallet_state_reader.py`, `discovery/data_api_client.py`, `dashboard/routes.py` et `dashboard/health_check.py` | **Cassé** | appel réel |
| Piège « `/trades` sans `usdcSize` » | `/v2/activity` a `usdc_size` ; `/v2/trades` a `size` + `price` (toujours pas de `usdc_size`) ; filtre `filter_type=CASH` | Changé | appel réel |
| pUSD + onramp `0x93070a847efEf7F70739046A929D47a521F5B8ee` | Inchangé. pUSD `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` ; offramp `0x2957922E…5854` ; ExchangeV3 `0xe3333700…00Aa` pour les marchés V2 | OK | doc Contracts |
| `/prices-history` (CLOB) | Répond toujours (grain 1 min, `fidelity` < 1 ignoré) mais remplacé par **`/v2/prices-history`** (data host, `bucket_seconds` 60–86400, curseur, plafond de 15 j sur start/end) | Déprécié | appel réel |
| RTDS crypto prices (Binance/Chainlink), public | **Legacy depuis le 2026-09-15.** PolyBolt `ws-live-v2` **avec auth CLOB** ; plus de Binance ; `price.crypto.twap` 60 s | **Changé** | doc |
| Taker delay crypto (non modélisé) | **150 ms** depuis le 2026-09-04 (la doc secondaire dit encore 250 ms) ; ordre `delayed` non annulable | Nouveau | changelog |
| Rate limits « ~100 req/min Data API » | v2 : 800 / 10 s général, `/v2/trades` 300 / 10 s ; buckets par signer côté trading | Changé | doc |
| Builder code → « rebates ~50–150 $/an » | Le builder fee est un frais que **le builder facture** (≤ 100 bps taker) ; pas de rebate automatique documenté | Non étayé | doc Builder Fees |
| `DELETE /orders` sans limite | ≤ 1000 IDs (changelog du 2026-06-15) contre 3 000 (page Manage Orders) | Nouveau, doc incohérente | doc |
| Résolution des marchés crypto par UMA ou M8 | Les marchés Up/Down sont résolus **automatiquement par l'oracle Chainlink en environ 80 s** (UMA seulement pour les autres) ; pas de neg_risk | Précisé | appel réel |

---

## F. Tableau des sources

| # | Source | Date de la source / consultation | Usage |
| - | - | - | - |
| 1 | https://docs.polymarket.com/llms.txt (index) | consulté le 2026-11-05 | cartographie de la doc |
| 2 | https://docs.polymarket.com/changelog/predictions.md | entrées du 2025-08-26 au **2026-11-02** | chronologie de tous les changements |
| 3 | https://docs.polymarket.com/changelog/sdks.md | jusqu'au SDK 0.16.0 | SDK unifié |
| 4 | https://docs.polymarket.com/migrate/data-api-v1-to-v2.md | consulté le 2026-11-05 | mapping v1 → v2 |
| 5 | https://data-api.polymarket.com/v2/openapi.json | v0.1.0, consulté le 2026-11-05 | paramètres v2 |
| 6 | https://docs.polymarket.com/api-reference/data-api/overview.md | consulté le 2026-11-05 | contrat v2, rétention |
| 7 | https://docs.polymarket.com/api-spec/clob-openapi.yaml | consulté le 2026-11-05 | routes CLOB, clés de `/clob-markets` |
| 8 | https://docs.polymarket.com/trading/fees.md | consulté le 2026-11-05 | formule et tableaux de frais |
| 9 | https://docs.polymarket.com/programs/maker-rebates.md, taker-rebates.md, liquidity-rewards.md, builders/{fees,tiers}.md | consultés le 2026-11-05 (taker rebates live depuis le 2026-05-28) | programmes |
| 10 | https://docs.polymarket.com/api-reference/rate-limits.md, trading-rate-limits.md | consultés le 2026-11-05 | limites |
| 11 | https://docs.polymarket.com/trading/{place-orders,manage-orders,matching-engine,realtime-order-updates,wallets-auth}.md, concepts/{order-lifecycle,resolution,pusd}.md | consultés le 2026-11-05 | ordres, heartbeat, WS user, résolution |
| 12 | https://docs.polymarket.com/market-data/realtime-data.md, api-reference/live-data/overview.md, migrate/rtds-to-polybolt.md | consultés le 2026-11-05 | WS market, PolyBolt |
| 13 | https://docs.polymarket.com/api-reference/geoblock.md | consulté le 2026-11-05 | pays restreints, eu-west-2 |
| 14 | https://docs.polymarket.com/resources/contracts.md | consulté le 2026-11-05 | adresses |
| 15 | https://polymarket.com/tos | « Effective as of August 11, 2026 » | ToS |
| 16 | https://polymarket.com/api/geoblock | appel réel du 2026-11-05 | geoblock |
| 17 | https://pypi.org/pypi/{py-clob-client-v2,py-clob-client,polymarket-client}/json + wheels files.pythonhosted.org | consultés le 2026-11-05 | versions, diff de code |
| 18 | https://raw.githubusercontent.com/Polymarket/py-clob-client-v2/main/{README.md,setup.py,…} | consultés le 2026-11-05 | bannière de dépréciation |
| 19 | gamma-api.polymarket.com `/markets`, `/events`, `/series`, `/markets/keyset`, `/events/keyset` | appels réels du 2026-11-05 entre 12:30 et 12:45 UTC | marchés, slugs, eventMetadata |
| 20 | clob.polymarket.com `/book`, `/midpoint`, `/price`, `/spread`, `/tick-size`, `/neg-risk`, `/fee-rate`, `/clob-markets`, `/markets`, `/last-trade-price`, `/prices-history`, `/markets/live-activity`, `/version`, `/time` | appels réels du 2026-11-05 | CLOB |
| 21 | data-api.polymarket.com v1 (410) et v2 `/trades`, `/activity`, `/positions`, `/value`, `/user-stats`, `/holders`, `/oi`, `/tokens`, `/resolutions`, `/status`, `/prices-history` | appels réels du 2026-11-05 | Data API |
| 22 | polymarket.com/api/crypto/crypto-price (non documenté) | appel réel du 2026-11-05 | ne correspond pas aux valeurs TWAP |
| 23 | Presse via WebSearch : SRF, bluewin, 20 Minuten, jamma.it, sigma.world (Gespa) ; crypto.news, cryptodaily, SCCG (TWAP / Stanford) ; cryptobriefing, predictionnews, coindesk (Polymarket US) ; polybot.trading (taker delay) ; merkblätter SZ / TG / ESTV (fiscalité) | publications de 2024-11 à 2026-10, résumés consultés le 2026-11-05 | [SUPPOSÉ] |

---

## G. Annexes — extraits bruts supplémentaires

**Marché résolu `btc-updown-5m-1793878200`** (Gamma `closed=true`) [VÉRIFIÉ appel réel] :
```json
{"slug":"btc-updown-5m-1793878200","outcomePrices":"[\"1\", \"0\"]","closed":true,"acceptingOrders":false,
 "closedTime":"2026-11-05 11:36:19+00","umaResolutionStatus":"resolved","automaticallyResolved":true,"resolutionMechanism":"oracle",
 "volumeNum":31634.54546800002,"lastTradePrice":0.999,
 "events[0].eventMetadata":{"finalPrice":80261.08159416831,"priceToBeat":80175.41447808895}}
```

**Chaîne priceToBeat / finalPrice** (12 fenêtres, extrait) [VÉRIFIÉ appel réel] :
```
btc-updown-5m-1793878500 {'finalPrice': 80238.38264019894, 'priceToBeat': 80261.08159416831} ["0","1"]  closed +79 s
btc-updown-5m-1793878800 {'finalPrice': 80263.92510519891, 'priceToBeat': 80238.38264019894} ["1","0"]  +79 s
btc-updown-5m-1793879400 {'finalPrice': 80280.62275843302, 'priceToBeat': 80269.56173303009} ["1","0"]  +81 s
btc-updown-5m-1793881800 {'finalPrice': 79852.09032898836, 'priceToBeat': 79993.98054953119} ["0","1"]  +79 s
```

**`/v2/resolutions`** [VÉRIFIÉ appel réel] :
```json
{"data":[{"condition_id":"0xc11905739e19269d47ca9b1f2a3bdc32dc0b662b24b2ccad5016505855eafc23","status":"resolved","extended_review":false,
 "was_disputed":false,"new_version_q":false,"transaction_hash":"0x6f483b3d…f89a","log_index":"587",
 "last_update_timestamp":"2026-11-05T11:36:19Z","payouts":[1000000,0],"resolution_source":"reported","resolved_block":96782082,"resolved_at":"2026-11-05T11:36:19Z"}]}
```

**`/v2/prices-history` (marché résolu, sans bucket)** [VÉRIFIÉ appel réel] :
```json
{"data":[{"timestamp":1793877600,"price":0.505,"resolution_seconds":60}, … ,
 {"timestamp":1793878620,"price":0.9995,"resolution_seconds":60},{"timestamp":1793878680,"price":1.0,"resolution_seconds":0}],
 "pagination":{"limit":10000,"offset":0,"has_more":false,"next_cursor":null}}
```

**Book brut (extrait du début de liste, ordre natif de l'API)** [VÉRIFIÉ appel réel] :
```json
{"market":"0xdefab1e2…d9b2","asset_id":"8298…7857","timestamp":"1793882020492","hash":"4662c39e2915a42e448aef02f45104e87c6c03d1",
 "bids":[],"asks":[{"price":"0.99","size":"4280.46"},{"price":"0.98","size":"1237.56"},{"price":"0.97","size":"1403.15"}, …],
 "min_order_size":"5","tick_size":"0.01","neg_risk":false,"last_trade_price":"…"}
```

**Frontend crypto-price (non documenté ; ne correspond PAS au TWAP)** [VÉRIFIÉ appel réel] :
```json
GET https://polymarket.com/api/crypto/crypto-price?symbol=BTC&eventStartTime=2026-11-05T12:30:00Z&variant=fiveminute&endDate=2026-11-05T12:35:00Z
{"openPrice":79990.93516872857,"closePrice":79892.1550062,"timestamp":1793882492395,"completed":true,"incomplete":false,"cached":true}
(Gamma TWAP pour la même fenêtre : priceToBeat 79993.98054953119, finalPrice 79852.09032898836)
```

**Erreurs v2 typiques** [VÉRIFIÉ appel réel] :
```
400 {"error":"'market' is not a query param on this API: filter by condition id with 'condition' (aliases 'condition_id', 'conditionId')","code":"invalid_request","retryable":false,…}
400 {"error":"'offset' is not a query param on this API: pages are cursor-only, pass 'cursor' from a prior response's next_cursor",…}
400 {"error":"bucket_seconds must be between 60 and 86400","code":"invalid_request","parameter":"bucket_seconds",…}
```
