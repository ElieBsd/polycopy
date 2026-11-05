ÉTAT : partiel — faits : mécanique/oracle/frais (vérifiés API), A (première passe), B repos GitHub, B wallets (8 actuels + noms historiques), mesures concurrence 24 h. Restants : papiers académiques complémentaires (FLB Kalshi/Polymarket), dashboards, Reddit/X, wallets historiques détaillés, relecture.

# Phase 3 A+B — « Manipulations » et concurrence sur les marchés Polymarket crypto Up/Down courts
Date de rédaction : 2026-11-05. Auteur : agent de recherche (lecture seule, aucune creds, aucun ordre).

Étiquettes : [VÉRIFIÉ] = constaté par moi (API publique Polymarket ou source primaire) ; [DÉDUIT] = raisonnement/calcul à partir de données vérifiées ; [SUPPOSÉ] = hypothèse plausible non vérifiée ; [ANECDOTIQUE] = post réseau social / blog vendeur non vérifié.

Limite d'outillage : WebFetch était bloqué (DNS hors allowlist) pour docs.polymarket.com, arxiv.org, predictionnews.com, cryptobriefing.com → les sources web ci-dessous viennent des extraits du moteur de recherche (pas lecture intégrale). Les faits marqués [VÉRIFIÉ] proviennent de gamma-api / data-api v2 / clob.polymarket.com / raw.githubusercontent.com interrogés directement.

---------------------------------------------------------------------
## 0. Faits de base (mécanique actuelle, nov. 2026)

| Fait | Valeur | Source / étiquette |
|---|---|---|
| Source de résolution | **Chainlink BTC/USD TWAP data stream 60 s** (`btc-usd-twap-60s-streams`), « Up » si TWAP de fin ≥ « price at the beginning » | Gamma `events?slug=btc-updown-5m-1793878200`, champ `description` + `cryptoMarketConfig={"id":"btc-5m-twap-60","twapEnabled":true,"twapLookbackSeconds":60}` [VÉRIFIÉ 2026-11-05] |
| Historique de l'oracle | snapshot instantané Chainlink jusqu'au 7 août 2026 ; puis TWAP 30 s (5 min) / 60 s (15 min, 4 h) ; ensuite tous les 5 min passés à 60 s | [@PolymarketDevs](https://x.com/PolymarketDevs/status/2082813706996772881) (juil. 2026), [CoinDesk 2026-08-07](https://www.coindesk.com/business/2026/08/07/how-a-five-second-trick-let-traders-drain-millions-from-polymarket), changelog [docs.polymarket.com/changelog/predictions](https://docs.polymarket.com/changelog/predictions) (extrait moteur) [VÉRIFIÉ pour l'état actuel via API ; dates = extraits] |
| `eventMetadata` | `priceToBeat` et `finalPrice` publiés (ex. 80175.41 → 80261.08) | Gamma [VÉRIFIÉ] |
| Frais taker | `feeType=crypto_fees_v2`, `feeSchedule={rate:0.07, exponent:1, takerOnly:true, rebateRate:0.2}` ; formule docs : **fee = C × 0.07 × p × (1−p)** (C = nb de shares) ⇒ 1,75 $ pour 100 shares à 0,50 (=3,5 % du notionnel), 1,12 $ pour 100 shares à 0,20 (=5,6 % du notionnel) | Gamma [VÉRIFIÉ] + formule [docs fees](https://docs.polymarket.com/trading/fees) via extrait moteur [VÉRIFIÉ partiel] ; calcul [DÉDUIT] |
| Rebate makers | 20 % des frais taker redistribués aux makers (types `MAKER_REBATE`, et aussi `TAKER_REBATE` visibles dans /v2/activity) | Gamma + activity [VÉRIFIÉ] |
| Historique des frais | taker fees 15 min crypto ~janv. 2026 ; 5 min lancés avec fees en fév. 2026 ; extension à toutes les durées crypto mars 2026 ; taux 0,072 → 0,07 (été 2026) | [Cointelegraph](https://cointelegraph.com/news/polymarket-quietly-adds-taker-fees-15-minute-crypto-markets), [Pine Analytics](https://pineanalytics.substack.com/p/polymarket-fee-rollout), [PolyTerminal](https://poly-terminal.com/learn/polymarket-fees), [StartPolymarket](https://startpolymarket.com/learn/polymarket-fees/) [extraits ; dates exactes non confirmées] |
| « Taker delay » (speed bump) | 500 ms supprimé ~18 fév. 2026 ; 250 ms réintroduit le 5 juin 2026 (crypto+finance up/down, ordre verrouillé pendant le délai) ; 50 ms le 17 août 2026 ; **150 ms depuis le 4 sept. 2026** | [X JesterTheGoose](https://x.com/Jesterthegoose/status/2024055036754686034) [ANECDOTIQUE], [@PolymarketDevs 5 juin](https://x.com/PolymarketDevs/status/2061930696323830158), [@PolymarketDevs 17 août](https://x.com/PolymarketDevs/status/2089295325660172578), changelog (extrait) [VÉRIFIÉ via comptes officiels/extraits] |
| Tick / taille min | tick 0,01 (0,001 aux extrêmes), min 5 shares (ordres reposants) | CLOB `/book` + Gamma [VÉRIFIÉ] |
| Création | marchés créés ~24 h à l'avance (`startDate` J-1, `eventStartTime`=début fenêtre) ; ~7 % du volume taker BTC 5 min se fait AVANT l'ouverture de la fenêtre | Gamma + mesure [VÉRIFIÉ] |
| Actifs | BTC, ETH, SOL, XRP + désormais BNB, DOGE, HYPE, XAU, XAG (slugs `bnb-updown-5m-*`, `xau-updown-15m-*`…) | Gamma [VÉRIFIÉ] |
| Volume | série `btc-up-or-down-5m` : volume24hr ≈ **13,8 M$** ; fenêtre BTC 5 min : volume taker médian ≈ 23 k$ (p10 16 k$, p90 35 k$) | Gamma + Data API v2 [VÉRIFIÉ] |
| Polymarket US | 5 min BTC/ETH/SOL/XRP lancés le 27 oct. 2026 sur l'app US (QCX, CFTC), résolution **CF Benchmarks** (moyenne de 60 observations sur 60 s) | [CoinDesk 2026-10-29](https://www.coindesk.com/markets/2026/10/29/polymarket-brings-ultra-short-crypto-prediction-markets-to-u-s-platform) [extrait] |

Data API : `data-api.polymarket.com/trades` v1 renvoie HTTP 410 « Data API v1 has been retired » [VÉRIFIÉ]. v2 : `/v2/trades?condition=<cid>&limit≤1000&taker_only=true|false&cursor=…` (param `market` refusé, `condition` requis) ; `/v2/activity?user=` (types TRADE, REDEEM, MERGE, SPLIT, MAKER_REBATE, TAKER_REBATE, REWARD, YIELD, REFERRAL_REWARD) ; `/v2/leaderboard?user=&time_period=day|week|month|all&sort_by=PNL|VOLUME&category=` [VÉRIFIÉ par messages d'erreur de l'API].

---------------------------------------------------------------------
## A. « Manipulation » : ce que disent les gens, et ce qui tient

### A.0 Mécanique : le prix d'une share est ~N(d) — pourquoi ça « saute »
Sous un brownien sans drift, la share Up vaut ≈ Φ( ln(S/K) / (σ√τ) ) où τ = temps restant. Pour BTC (σ annuelle ~45-55 %), σ sur 5 min ≈ 0,1 % ; sur les 30 dernières secondes ≈ 0,03 %. Un écart spot/strike de 0,03 % (≈ 25 $ à 80 k$) vaut donc ~±1σ à 30 s de la fin → la share passe de 0,50 à 0,84 ou 0,16 sur un mouvement de 25 $. Le « gamma » (dPrix/dSpot) explose en 1/√τ près de la fin [DÉDUIT]. Avec la TWAP 60 s, à partir de T−60 s une part croissante du fixing est déjà « figée », ce qui réduit la variance restante (la share converge plus tôt) mais n'enlève pas le phénomène [DÉDUIT].
**Mesure** (288 fenêtres BTC 5 min, 4-5 nov. 2026, trades takers) : 1,23 « swing » par fenêtre où le prix implicite Up bouge de ≥30 ¢ en ≤15 s ; 24 % de ces swings dans la dernière minute ; 50 % sont suivis d'un retour ≥20 ¢ en ≤30 s [VÉRIFIÉ]. Ces amplitudes sont exactement celles attendues d'un Φ(·) à τ court quand le spot oscille autour du strike → **l'essentiel des « retournements » s'explique par la gamma, pas par une manipulation** [DÉDUIT]. Argument clé : si le prix de la share est une martingale (ce qu'il doit être s'il est une probabilité risque-neutre bien calibrée), alors acheter à a et revendre à b>a « sinon tenir » a une espérance **nulle** avant frais : P(toucher b avant 0) = a/b (théorème d'arrêt), gain = (a/b)(b−a) − (1−a/b)·a = 0 [DÉDUIT, standard].

### A.1 Tableau hypothèses × réalité

| # | Hypothèse | Réelle ? | Mesurable ? | Détectable en temps réel ? | Exploitable aller-retour après frais ? |
|---|---|---|---|---|---|
| 1 | Gros ordres qui poussent le prix puis retour (surréaction → mean reversion) | Partiellement : carnets fins (top-of-book souvent 20-400 $), un ordre de quelques centaines de $ « marche » le carnet [VÉRIFIÉ snapshots `/book`] ; mais le retour est le plus souvent le spot qui revient (gamma) | Oui (trades + carnet) mais il faut le spot/Chainlink pour séparer « choc de flux » vs « choc de fair value » | Oui si on calcule une fair value Φ(·) temps réel à partir du spot ; sans ça, non | **Non démontré.** Backtest naïf « acheter ≤0,20, revendre ≥0,60 sinon tenir » sur 288 fenêtres BTC 5 min : P(toucher 0,60)=0,30 (martingale ≈0,33), PnL brut **+0,010 $/share ± ~0,015 (bruit)**, **−0,005 $/share** après frais taker 2 jambes ; BTC 15 min (96 f.) : −0,013 ; résultats légèrement positifs sur ETH 5m/SOL 15m mais n≈50-110, carnets de quelques centaines de $ → non exécutable [VÉRIFIÉ calcul, exécution optimiste au prix imprimé] |
| 2 | Spoofing / layering, carnets vides qui amplifient | Carnets vides réels (souvent un côté vide en fin de fenêtre, cf. 15 min à T−60 s : aucun bid, ask 0,001) [VÉRIFIÉ] ; spoofing non documenté publiquement sur ces marchés [SUPPOSÉ possible] | Partiellement (WS `book`/`price_change`, ordres annulés non publics on-chain) | Difficile : on voit les niveaux, pas l'identité ; « speed bump » 150 ms côté taker | Non : le carnet vide amplifie surtout le coût d'entrée/sortie (spread ±1-2 ¢, profondeur 5 ¢ = quelques centaines de $) |
| 3 | Divergence prix Polymarket vs spot CEX/Chainlink | **Oui, mais en millisecondes** : OpenMarket (727 M lignes, fév-mai 2026) mesure un lead-lag source ≈ **16 ms médian**, réponse des cotations Polymarket ≈ **347 ms** après un gros mouvement Binance ; modèle hors-échantillon **ne bat pas** le mid Polymarket, économie simulée **négative** après frais/slippage | [gregyoung14/openmarket README](https://raw.githubusercontent.com/gregyoung14/openmarket/main/README.md), papier [arXiv 2607.26245](https://arxiv.org/abs/2607.26245) [VÉRIFIÉ README] | Oui pour des acteurs colocalisés (Londres/Irlande, Rust) | Pour un particulier en Suisse : **non**. Les claims « Polymarket a 30-90 s de retard » [ANECDOTIQUE, blogs vendeurs] datent de 2025 / début 2026 et sont contredits par les données 2026 |
| 4 | Bots d'arbitrage de latence (0x8dxd, gabagool22, Account88888, distinct-baguette…) | Oui historiquement, très rentables fin 2025 – mi 2026 ; **tous inactifs aujourd'hui** (voir B.5) | Oui (leaderboard v2, activity) | — | Fenêtre fermée par : taker fees (janv.-mars 2026), suppression/réintroduction de speed bumps, TWAP (août 2026), concurrence |
| 5 | Activité fin de fenêtre (snipers dernières secondes, ordres 0,99) | Oui : ~16 % du volume taker BTC 5 min dans les 60 dernières s, 5 % dans les 30 dernières s [VÉRIFIÉ] ; à T−10 s, 100 % des fenêtres sont déjà à <0,1 ou >0,9 et le favori gagne 142/142 [VÉRIFIÉ] | Oui | Oui | Gain par share minuscule (0,01-0,04) vs risque de queue (un retournement = −0,96) ; marché très encombré ; avec TWAP 60 s la « dernière seconde » ne décide plus seule |
| 6 | Wash trading | Documenté sur Polymarket en général (étude Columbia 2025, ~25 % du volume historique suspect) [à confirmer, voir B.3] ; non spécifique aux up/down | Oui (graphes de wallets) | Non pertinent | Non (ne crée pas de mispricing exploitable ; gonfle juste le volume affiché) |
| 7 | Volatilité normale mal perçue / biais du survivant | **Explication dominante** (A.0) ; les « succès » publiés sont des wallets survivants (0x8dxd, gabagool…), alors que d'autres gros wallets up/down ont des PnL all-time de −3 à −11 M$ (B.5) | Oui | — | — |
| 8 | Manipulation du spot/oracle au snapshot | **Oui, documenté** : Dai, Jia, Yu (Stanford/SMU), *Settlement Manipulation in Prediction Markets*, [arXiv 2606.31675](https://arxiv.org/abs/2606.31675) (30 juin 2026) : après le lancement du 5 min (fév. 2026), flux d'ordres spot Binance ~+50 % dans les 10 dernières s (jusqu'à 3,9× le volume normal), renversements de prix après le fixing ; **821 wallets** (≈1/300 de ~243 000) classés manipulateurs potentiels, **+8,2 M$** dans les cycles manipulés, ~0 ailleurs ; 93 % des pertes sur le retail ; effet bien plus faible en 15 min. Réponse Polymarket : TWAP le 7 août 2026 | [X Ruizhe Jia](https://x.com/RuizheJia/status/2074615729333374981), [CoinDesk](https://www.coindesk.com/business/2026/08/07/how-a-five-second-trick-let-traders-drain-millions-from-polymarket), [crypto.news](https://crypto.news/polymarket-five-second-exploit-manipulation-twap-fix/), [ForkLog](https://forklog.com/en/researchers-find-signs-of-manipulation-in-polymarket-five-minute-bitcoin-contracts/) [VÉRIFIÉ via 4 sources concordantes ; chiffres d'après presse, papier non lu intégralement ; lien causal comptes Binance ↔ wallets non établi] | Mesurable a posteriori | Plus depuis la TWAP 60 s (coût de manipulation ×~60) | Non pour un particulier (et illégal/contraire aux règles). Pertinent seulement comme **risque** : un mouvement « anormal » de dernière minute peut être un manipulateur qui sait où sera le fixing → acheter le côté « déprimé » c'est lui servir de contrepartie |

### A.2 Discussion critique
- La notion de « prix anormalement déprimé » n'a de sens que **relativement à une fair value conditionnelle au spot/oracle**. Une share Up à 0,20 alors que le spot est 0,05 % sous le strike à 60 s de la fin n'est pas déprimée, elle est juste.
- Calibration mesurée (BTC 5 min, 288 f.) : à T−120 s, prix 0,0-0,1 → Up gagne 5 % ; 0,1-0,2 → 11 % ; 0,9-1,0 → 95 % ; à T−60 s : 0,0-0,1 → 1 % ; 0,9-1,0 → 96 % [VÉRIFIÉ]. Le marché est **globalement calibré** ; s'il y a un biais, c'est un léger surprix des « longshots » (favorite-longshot bias) → acheter les creux est plutôt **négatif** en tenant.
- L'effet « 20 ¢ → 60 ¢ » se produit ~30 % du temps, ce que prédit la martingale (33 %) ; il n'y a pas d'excès de retour à la moyenne visible dans les données.
- Les frais taker (0,07·p(1−p)/share) coûtent ~0,011 $ à l'entrée à 0,20 et ~0,017 $ à la sortie à 0,60 ⇒ ~0,028 $/aller-retour réussi ; l'edge brut mesuré (≤0,01 $/share) ne les couvre pas.
- Le seul profil où un aller-retour pourrait gagner : **maker** (pas de frais + rebate 20 %) qui fournit de la liquidité dans le creux, mais il subit l'**adverse selection** (il est rempli précisément quand le spot s'éloigne) et la course de vitesse d'annulation (speed bump taker 150 ms protège un peu les makers).

---------------------------------------------------------------------
## B. État de l'art et concurrence

### B.1 Repos GitHub (API search, 2026-11-05)
Beaucoup de repos récents ont des étoiles gonflées/spam (créés en 2016 et renommés, READMEs « polymarket trading bot » répétés, adresses de don). Sélection :

| Repo | ★ | Dernier push | Stratégie | Résultat revendiqué / qualité |
|---|---|---|---|---|
| [gregyoung14/openmarket](https://github.com/gregyoung14/openmarket) | 22 | 2026-07-31 | Corpus ms Polymarket×Binance, Rust, arXiv 2607.26245 | **Résultat nul** hors échantillon, économie négative après frais ; lag 16 ms / 347 ms. Meilleure source empirique. Archivé. [VÉRIFIÉ README] |
| [PricePepel/polymarket-tracker](https://github.com/PricePepel/polymarket-tracker) | 7 | 2026-11-02 | Copie des top 50 traders crypto sur BTC 5 min (paper) | 1 493 trades, hit rate 70,5 % vs **break-even 70,4 %** ⇒ zéro edge ; bankroll 20 $ → 0,10 $ (−99,5 %) avec sizing 10 %. [VÉRIFIÉ README] |
| [humanplane/cross-market-state-fusion](https://github.com/humanplane/cross-market-state-fusion) | 386 | 2026-01-03 | PPO (RL) Binance futures → 15 min, **paper**, fills au mid | « ~50 k$ PnL paper » ; reconnaît lui-même : pas de preuve live, pas de significativité. [VÉRIFIÉ README] |
| [Xuano47/Zero-Lag-PolymarketBot](https://github.com/Xuano47/Zero-Lag-PolymarketBot) | 14 | 2026-03-04 | Arb YES+NO<1 en Rust, batch FOK, serveur Irlande (moteur à Londres) | « prouve que 99 % des stratégies d'arb vendues sur X sont du BS » ; « latence = seul critère ». [VÉRIFIÉ README] |
| [KaustubhPatange/polymarket-trade-engine](https://github.com/KaustubhPatange/polymarket-trade-engine) | 323 | 2026-06-08 | Moteur + harness de stratégies BTC 5 min | Pas de PnL ; bon guide (frais en shares sur BUY, tailles min, arrondis on-chain). [VÉRIFIÉ] |
| [warproxxx/poly-maker](https://github.com/warproxxx/poly-maker) | 1 522 | 2026-07-09 | MM maker-only, marchés **politiques** | « competitive and can lose money ». [VÉRIFIÉ] |
| [Jonmaa/btc-polymarket-bot](https://github.com/Jonmaa/btc-polymarket-bot) | 77 | 2026-01-07 | Arb UP+DOWN<0,99 sur 15 min (« stratégie Jeremy Whittaker ») | Pas de résultats ; pré-fees. |
| [blockchainhansi/vola_scalping_polymarket](https://github.com/blockchainhansi/vola_scalping_polymarket) | 9 | 2026-01-05 | « box spread » : poser des pièges des deux côtés puis couvrir la jambe | Pas de résultats. |
| [coleschaffer/Gabagool](https://github.com/coleschaffer/Gabagool) / [strongca22-cpu/gabagool](https://github.com/strongca22-cpu/gabagool) | 44 / ? | 2025-12 | Clones « gabagool » (achat 2 côtés <1) | Pas de résultats audités. |
| [big-year/polymarket-btc5](https://github.com/big-year/polymarket-btc5) | 13 | 2026-04-30 | Sniper favori 10-50 s avant fin, take-profit 0,98, grille de paramètres « shadow » | Pas de PnL publié. |
| [ThinkEnigmatic/polymarket-bot-arena](https://github.com/ThinkEnigmatic/polymarket-bot-arena) | 83 | 2026-09-13 | Momentum/mean-rev/sentiment évolutifs, BTC 5 min, paper | Aucun résultat. |
| [djienne/POLYMARKET_UP_DOWN_DERIBIT_STRATEGY](https://github.com/djienne/POLYMARKET_UP_DOWN_DERIBIT_STRATEGY) | 29 | 2026-03-08 | Fair value via surface SSVI Deribit (journalier) | Backtest seulement. |
| [radioman/polymarket-arbitrage-trading-bot](https://github.com/radioman/polymarket-arbitrage-trading-bot) | 637 | 2026-06-19 | « arb BTC/ETH 5 min » | Repo créé en 2016 → étoiles suspectes. [DÉDUIT] |
| [CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot](https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot) | 257 | 2026-05-09 | Arb Polymarket ↔ Kalshi sur BTC horaire | Pas de résultats live. |
| [Gonzih/polymarket-arb](https://github.com/Gonzih/polymarket-arb) | ? | ? | Latence + oracle, Binance WS, Kelly, paper | Non évalué. |

Constat : **aucun repo public ne montre un PnL live audité positif** sur ces marchés après frais ; les deux seuls projets avec méthodologie sérieuse (OpenMarket, polymarket-tracker) concluent à **zéro edge** [VÉRIFIÉ].

### B.2 Stratégies connues — vivantes ou mortes ?
(a) **« gabagool » / YES+NO < 1** : acheter les 2 côtés (souvent à des moments différents) pour un coût de paire < 1. gabagool22 : PnL all-time **+813 k$ sur 144,8 M$ de volume (0,56 %)**, dernier trade avant juin 2026 (seuls des REFERRAL_REWARD en juin) [VÉRIFIÉ leaderboard/activity v2]. Les wallets dominants actuels (Bonereaper, GoodFallen, FairValueMachine, dangerously-skip-permissions) font une version **maker/hybride** : achats des 2 côtés dans 92-100 % des marchés, coût de paire médian 0,98-1,12, aucun SELL (tout tenu à résolution), 45-88 % des fills en taker [VÉRIFIÉ]. Marge brute observée ≈ 0 à +1,4 % des montants achetés sur ~1 jour ; la rentabilité dépend des **rebates** (FairValueMachine : 792 $ TAKER_REBATE + 134 $ MAKER_REBATE dans l'échantillon) [VÉRIFIÉ].
(b) **Arbitrage de latence vs Binance** : rentable fin 2025 (0x8dxd : claim 313 $ → 438 k$ déc. 2025 – janv. 2026 [ANECDOTIQUE]) ; aujourd'hui lag mesuré en ms (OpenMarket) + taker fees + speed bump 150 ms ⇒ mort pour qui n'est pas colocalisé, et marginal pour les autres [VÉRIFIÉ/DÉDUIT]. 0x8dxd et Account88888 ont cessé toute activité le **24-25 août 2026** (≈ 1 semaine après le passage 250→50 ms et 2,5 semaines après la TWAP) [VÉRIFIÉ dates ; causalité SUPPOSÉE].
(c) **Market making + maker rebates** : le modèle survivant. 20 % des taker fees redistribués + programmes de liquidity rewards (1 M$ en août 2026 [ANECDOTIQUE, X PolyAlertHub](https://x.com/PolyAlertHub/status/2082842133875331561)). Exige infra, gestion d'inventaire et capital.
(d) **Sniping fin de fenêtre 0,95-0,99** : encombré, gain ≤4 ¢, queue −96 ¢ ; TWAP 60 s réduit l'avantage « dernière seconde ».
(e) **Mean reversion / fade** : aucune preuve d'edge ; nos mesures = martingale. Les gros wallets qui font des allers-retours (médiane de détention 114-168 s : 0x9e3ed…, neutralwave23, suntori) ont des PnL all-time **−4,4 M$, −3,2 M$, −11,6 M$** (tous marchés confondus, dont sports) [VÉRIFIÉ leaderboard].
(f) **Momentum** : idem, pas de preuve publique ; anecdotes de pertes (layerx −37,8 % [ANECDOTIQUE](https://layerx.xyz/blog/polymarketbots) ; dev.to « 176 trades, ~2 $ de profit » [ANECDOTIQUE](https://dev.to/manja316/176-trades-on-polymarket-what-my-bot-actually-made-its-not-what-you-think-3iib)).

### B.5 Wallets (PnL = leaderboard v2 tous marchés ; comportement = /v2/activity derniers 4 000-6 000 records, nov. 2026)

| Wallet (nom) | PnL all-time / volume | PnL 30 j | Statut | Comportement mesuré |
|---|---|---|---|---|
| 0x63ce342161250d705dc0b16df89036c8e5f9ba9a (0x8dxd) | +2,05 M$ / 200,6 M$ (1,0 %) | ~0 | inactif depuis 2026-08-25 | latence (presse) [VÉRIFIÉ PnL] |
| 0x7f69983eb28245bba0d5083502a78744a8f66162 (Account88888) | +623 k$ / 120,4 M$ (0,52 %) | — | inactif depuis 2026-08-25 | BTC 5 min, redeem ~700 $ par marché |
| 0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d (gabagool22) | +813 k$ / 144,8 M$ (0,56 %) | — | inactif depuis ~juin 2026 | 2 côtés < 1 |
| 0xe00740bce98a594e26861838885ab310ec3b548c (distinct-baguette) | +702 k$ / 72,4 M$ (0,97 %) | — | inactif depuis 2026-03-26 | « buys dips, sells peaks, 142 s median hold » [ANECDOTIQUE polybot-arena] |
| 0xeebde7a0e019a63e6b476eb425505b7b3e6eba30 (Bonereaper) | **−140 k$** / 268 M$ | +73,6 k$ | actif (286/288 fenêtres BTC 5m, 4,3 % du volume taker) | BUY seul, 2 côtés 97 %, paire médiane 1,115, 88 % taker, 18 % des achats ≥0,90 |
| 0xc53375ff94e96100f2b30a4b5775db35218d69a9 (dangerously-skip-permissions) | +124 k$ / 26,5 M$ | +177 k$ | actif | BUY seul, 2 côtés 100 %, paire 0,983, 60 % taker |
| 0x0ca4e9d27ff826a109ecbf74754fb66b93f277a6 (GoodFallen) | +77 k$ / 14,2 M$ | +93 k$ | actif | idem, paire 1,013, 58 % taker |
| 0xd84403efd50b49a1d8a7181627e00307e6ea5908 (FairValueMachine) | +60 k$ / 8,4 M$ | +67 k$ | actif | idem, paire 1,015, 52 % taker, rebates significatifs |
| 0xb9587c373c773d023f47c2f85a30b3d5bddcf513 (blue.birds) | +8,6 k$ / 7,6 M$ | +61 k$ | actif | BTC/ETH/SOL 5m+15m, 2 côtés 81 %, 45 % taker |
| 0xe9076a87c5ed90ef16e6fe6529c943baeca0cff6 (suntori) | **−11,56 M$** / 776 M$ | −215 k$ | actif | multi-marchés (sports+crypto), allers-retours (42 % marchés avec SELL, détention médiane 163 s) |
| 0x9e3ed7b661a903fc97afcf49e0f014ebe869f882 | **−4,39 M$** / 150 M$ | −674 k$ | actif | allers-retours (détention médiane 168 s), −41 % sur l'échantillon ~17 h |
| 0x5b6331e7ff0831a3fe2ed12004747db1a9c911a4 (neutralwave23) | **−3,23 M$** / 165 M$ | −513 k$ | actif | allers-retours (détention 114 s) |

### B.6 Concurrence mesurée (Data API v2, trades takers, 4-5 nov. 2026)
| Série | Fenêtres | Trades takers/fenêtre (méd.) | Wallets takers distincts/fenêtre (méd.) | Volume taker/fenêtre (méd.) | Part top-5 wallets |
|---|---|---|---|---|---|
| BTC 5 min | 288 | 1 489 | 541 | 22,9 k$ | 31 % |
| BTC 15 min | 96 | 648 | 234 | 13,1 k$ | 42 % |
| ETH 5 min | 95 | 123 | 64 | 1,2 k$ | 54 % |
| SOL 15 min | 48 | 52 | 26 | 0,4 k$ | 69 % |
BTC 5 min : 7 506 wallets distincts en 24 h, 176 présents dans >50 % des fenêtres (bots) [VÉRIFIÉ]. Carnets : top-of-book ±1 ¢ souvent 20-400 $ ; ±5 ¢ quelques centaines à ~1 000 $ [VÉRIFIÉ snapshots].

(Sections B.3 papiers et B.4 dashboards : en cours.)
