"""Analyse 1 : microstructure, dynamique, calibration, FV, lead-lag, mark-out makers (jetable)."""
import sys, json, numpy as np, collections, pickle
sys.path.insert(0, 'scripts')
from load import load, window_arrays, PRE
from fv import build_spot_path, fair_values
DUR = 300
M, T, spot = load('data_btc5m')
print('windows', len(M), 'with trades', len(T), 'spot secs', len(spot))
rows = []; W = {}
for slug in sorted(M, key=lambda s: M[s]['start']):
    m = M[slug]; tr = T.get(slug, [])
    if not tr: continue
    a = window_arrays(m, tr, DUR)
    S = build_spot_path(spot, m['start'], DUR)
    if np.isnan(S[1800 - 1800]) or np.isnan(S[1800 + DUR]): continue
    K = m['meta']['priceToBeat']; up_won = m['prices'][0] == '1'
    P, sig, basis = fair_values(S, K, 1800, DUR)
    W[slug] = dict(start=m['start'], up=up_won, K=K, final=m['meta']['finalPrice'], sig=sig, basis=basis, P=P,
                   S=S[1800:1800 + DUR + 1].copy(), ask=a['ask'][PRE:PRE + DUR], bid=a['bid'][PRE:PRE + DUR],
                   ask_age=a['ask_age'][PRE:PRE + DUR], bid_age=a['bid_age'][PRE:PRE + DUR],
                   ask_sz=a['ask_sz'][PRE:PRE + DUR], bid_sz=a['bid_sz'][PRE:PRE + DUR],
                   ntr=a['ntr'], notional=a['notional'], trades=tr)
pickle.dump(W, open('W_btc5m.pkl', 'wb'))
print('usable windows', len(W))
# ---------- 1. Microstructure ----------
ntr = np.array([len(w['trades']) for w in W.values()]); notl = np.array([w['notional'].sum() for w in W.values()])
wal = np.array([len(set(t[5] for t in w['trades'])) for w in W.values()])
q = lambda x: np.percentile(x, [10, 50, 90]).round(1)
print('\n[1] trades/fenêtre p10/50/90', q(ntr), 'notional taker $', q(notl), 'wallets', q(wal))
# répartition temporelle du notional (secondes relatives : -120..420)
agg = np.zeros(PRE + DUR + 120)
for w in W.values(): agg += w['notional']
tot = agg.sum(); print('part du notional avant ouverture', round(agg[:PRE].sum() / tot, 3), 'après fin', round(agg[PRE + DUR:].sum() / tot, 3))
for a0, a1 in [(0, 60), (60, 120), (120, 180), (180, 240), (240, 270), (270, 290), (290, 300)]:
    print(f'   notional [{a0},{a1}) : {agg[PRE + a0:PRE + a1].sum() / tot:.3f}')
sz = np.array([t[4] * t[3] for w in W.values() for t in w['trades']]); print('taille trade $ p10/50/90/99', np.percentile(sz, [10, 50, 90, 99]).round(1))
# spread reconstruit : ask et bid frais (<=1s) simultanément
sp = collections.defaultdict(list)
for w in W.values():
    ok = (w['ask_age'] <= 1) & (w['bid_age'] <= 1)
    for t in np.where(ok)[0]:
        mid = (w['ask'][t] + w['bid'][t]) / 2; s = w['ask'][t] - w['bid'][t]
        b = 'mid 0.35-0.65' if 0.35 <= mid <= 0.65 else ('mid 0.15-0.35/0.65-0.85' if 0.15 <= mid <= 0.85 else 'extrêmes')
        sp[(b, 'early' if t < 240 else 'late')].append(s)
print('spread effectif reconstruit (ask-bid, obs <=1s) médiane/p90, n')
for k in sorted(sp): print('  ', k, np.round(np.median(sp[k]), 3), np.round(np.percentile(sp[k], 90), 3), len(sp[k]))
# ---------- 2. Dynamique intra-fenêtre ----------
def mid(w):
    m = np.where((w['ask_age'] <= 5) & (w['bid_age'] <= 5), (w['ask'] + w['bid']) / 2, np.nan)
    return m
rng = []; swings = collections.Counter(); nwin = 0
for w in W.values():
    m = mid(w)[5:290]
    if np.sum(np.isfinite(m)) < 50: continue
    nwin += 1; rng.append(np.nanmax(m) - np.nanmin(m))
    # aller-retour exécutable : acheter côté X à ask<=a puis vendre plus tard à bid>=b (Up ou Down)
    for side in ('up', 'down'):
        if side == 'up': ask, bid = w['ask'], w['bid']
        else: ask, bid = 1 - w['bid'], 1 - w['ask']
        for a, b in [(0.20, 0.40), (0.20, 0.60), (0.30, 0.50), (0.40, 0.60), (0.10, 0.30), (0.15, 0.60)]:
            hit = False
            ia = np.where((ask <= a) & (w['ask_age' if side == 'up' else 'bid_age'] <= 1))[0]
            ia = ia[ia < 290]
            if len(ia):
                t1 = ia[0]; later = bid[t1 + 1:295]; fresh = (w['bid_age' if side == 'up' else 'ask_age'][t1 + 1:295] <= 1)
                hit = bool(np.any((later >= b) & fresh))
                swings[(a, b, 'entry')] += 1
            if hit: swings[(a, b, 'hit')] += 1
rng = np.array(rng); print('\n[2] fenêtres avec mid exploitable', nwin, 'amplitude max-min du mid Up p10/50/90', np.percentile(rng, [10, 50, 90]).round(3))
print('   aller-retour exécutable (ask<=a puis bid>=b plus tard, même côté, avant t=295s) — par côté:')
for a, b in [(0.10, 0.30), (0.20, 0.40), (0.20, 0.60), (0.15, 0.60), (0.30, 0.50), (0.40, 0.60)]:
    e = swings[(a, b, 'entry')]; h = swings[(a, b, 'hit')]
    print(f'   a={a:.2f} b={b:.2f} : entrées {e}  hit {h}  p={h / max(e, 1):.3f}  (break-even gross p≈{(a + 0.07 * a * (1 - a)) / (b - 0.07 * b * (1 - b)):.3f} si sinon perte totale)')
# ---------- 3. Calibration ----------
print('\n[3] calibration : prix mid Up à tau secondes de la fin -> fréquence Up')
for tau in (240, 120, 60, 30, 10, 3):
    t = DUR - tau; xs = []; ys = []; fv = []
    for w in W.values():
        a, b = w['ask'][t], w['bid'][t]
        if w['ask_age'][t] <= 5 and w['bid_age'][t] <= 5:
            xs.append((a + b) / 2); ys.append(w['up']); fv.append(w['P'][t])
    xs = np.array(xs); ys = np.array(ys, float); fv = np.array(fv)
    out = []
    for lo, hi in [(0, .1), (.1, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01)]:
        k = (xs >= lo) & (xs < hi)
        if k.sum() >= 20:
            p = ys[k].mean(); se = np.sqrt(p * (1 - p) / k.sum())
            out.append(f'[{lo:.1f},{hi:.1f}) n={k.sum()} prix={xs[k].mean():.3f} réel={p:.3f}±{1.96 * se:.3f} FV={np.nanmean(fv[k]):.3f}')
    bm = np.mean((xs - ys) ** 2); bf = np.nanmean((fv - ys) ** 2)
    print(f' tau={tau}s n={len(xs)} Brier marché={bm:.4f} Brier FV={bf:.4f}'); [print('    ', o) for o in out]
# ---------- 4. Lead-lag spot -> mid ----------
print('\n[4] corrélation Δmid(t) vs ΔFV(t-k) (1s), fenêtres t in [10,280]')
for k in (-3, -2, -1, 0, 1, 2, 3, 5, 10):
    xs = []; ys = []
    for w in W.values():
        m = np.where((w['ask_age'] <= 2) & (w['bid_age'] <= 2), (w['ask'] + w['bid']) / 2, np.nan)
        P = w['P']
        for t in range(12, 280):
            if t - k - 1 < 0 or t - k >= DUR: continue
            dm = m[t] - m[t - 1]; df = P[t - k] - P[t - k - 1]
            if np.isfinite(dm) and np.isfinite(df): xs.append(df); ys.append(dm)
    print(f'   k={k:+d} corr={np.corrcoef(xs, ys)[0, 1]:.3f} n={len(xs)}')
# ---------- 5. Mark-out des takers (= -maker) ----------
print('\n[5] PnL taker à la résolution par share (hors frais), par tranche de temps et de prix')
mk = collections.defaultdict(lambda: [0.0, 0.0, 0]); FEE = collections.defaultdict(float)
for w in W.values():
    for ts, is_up, is_buy, p, sz, wa in w['trades']:
        t = ts - w['start']
        if t < -120 or t >= 300: continue
        won = (w['up'] if is_up else not w['up'])
        pnl = (won - p) if is_buy else (p - won)
        tb = 'pre' if t < 0 else ('0-120' if t < 120 else ('120-240' if t < 240 else ('240-290' if t < 290 else '290-300')))
        pb = 'p<.2' if p < .2 else ('p.2-.5' if p < .5 else ('p.5-.8' if p < .8 else 'p>=.8'))
        fee = 0.07 * p * (1 - p)
        for key in ((tb, pb), (tb, 'all'), ('all', pb), ('all', 'all')):
            mk[key][0] += pnl * sz; mk[key][1] += sz; mk[key][2] += 1; FEE[key] += fee * sz
for key in sorted(mk):
    v = mk[key]; print(f'   {key}: n={v[2]} pnl/share taker brut={v[0] / v[1]:+.4f} frais/share={FEE[key] / v[1]:.4f} net taker={(v[0] - FEE[key]) / v[1]:+.4f} | maker brut={-v[0] / v[1]:+.4f} maker+rebate20%={(-v[0] + 0.2 * FEE[key]) / v[1]:+.4f}')
