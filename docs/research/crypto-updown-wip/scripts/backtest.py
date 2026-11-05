"""Backtest stratégies intra-fenêtre (jetable). Exécution taker sur prix de trades observés."""
import sys, pickle, numpy as np, itertools, collections
DUR = 300; FEE = 0.07
W = pickle.load(open(sys.argv[1] if len(sys.argv) > 1 else 'W_btc5m.pkl', 'rb'))
ws = sorted(W.values(), key=lambda w: w['start'])
t_split = ws[0]['start'] + int(0.64 * (ws[-1]['start'] - ws[0]['start']))
TRAIN = [w for w in ws if w['start'] < t_split]; TEST = [w for w in ws if w['start'] >= t_split]
def fee(p): return FEE * p * (1 - p)
def side_arrays(w, side):
    if side == 0:  # Up
        return w['ask'], w['ask_age'], w['bid'], w['bid_age'], w['P'], w['up']
    return 1 - w['bid'], w['bid_age'], 1 - w['ask'], w['ask_age'], 1 - w['P'], not w['up']
def fresh_px(px, age, t, maxage=1):
    return px[t] if 0 <= t < DUR and age[t] <= maxage and np.isfinite(px[t]) else None
def entries(windows, signal, max_entry_t=270):
    """Première occurrence du signal par fenêtre (une position max par fenêtre)."""
    out = []
    for w in windows:
        hit = None
        for t in range(15, max_entry_t):
            for side in (0, 1):
                A = side_arrays(w, side)
                if signal(w, side, t, A): hit = (w, side, t); break
            if hit: break
        if hit: out.append(hit)
    return out
def simulate(ents, tp, sl, t_exit, lat=1, slip=0.0, hold=False):
    res = []
    for w, side, t in ents:
        ask, aage, bid, bage, P, won = side_arrays(w, side)
        te = t + lat; pe = fresh_px(ask, aage, te)
        if pe is None:   # pas de prix exécutable observé à t+lat : tolère 1s de plus, sinon pas de trade
            te += 1; pe = fresh_px(ask, aage, te)
        if pe is None or pe >= 0.99 or pe <= 0.005: continue
        pe = min(0.99, pe + slip); cost = pe + fee(pe); pnl = None; reason = 'res'
        if not hold:
            for u in range(te + 1, min(t_exit, DUR)):
                b = fresh_px(bid, bage, u)
                if b is None: continue
                if b >= pe + tp or b <= pe - sl:
                    bx = fresh_px(bid, bage, u + lat, 2)
                    if bx is None: bx = b - 0.02
                    bx = max(0.0, bx - slip); pnl = bx - fee(bx) - cost; reason = 'tp' if b >= pe + tp else 'sl'; break
            if pnl is None and t_exit < DUR:
                bx = None
                for u in range(t_exit, min(t_exit + 4, DUR)):
                    bx = fresh_px(bid, bage, u, 2)
                    if bx is not None: break
                if bx is not None:
                    bx = max(0.0, bx - slip); pnl = bx - fee(bx) - cost; reason = 'time'
        if pnl is None: pnl = float(won) - cost; reason = 'res'
        res.append((w['start'], side, t, pe, pnl, reason, pnl / cost))
    return res
def run(windows, signal, tp, sl, t_exit, lat=1, slip=0.0, hold=False, max_entry_t=270):
    return simulate(entries(windows, signal, max_entry_t), tp, sl, t_exit, lat, slip, hold)
def summarize(res, label=''):
    if not res: return dict(n=0)
    pnl = np.array([r[4] for r in res]); ret = np.array([r[6] for r in res])
    rng = np.random.default_rng(0); bs = [rng.choice(pnl, len(pnl)).mean() for _ in range(1000)]
    rs = collections.Counter(r[5] for r in res)
    return dict(n=len(res), pnl_share=pnl.mean(), ci=(np.percentile(bs, 2.5), np.percentile(bs, 97.5)), ret=ret.mean(),
                win=(pnl > 0).mean(), reasons=dict(rs))
def fmt(d):
    if d['n'] == 0: return 'n=0'
    return f"n={d['n']:5d} pnl/share={d['pnl_share']:+.4f} IC95=[{d['ci'][0]:+.4f},{d['ci'][1]:+.4f}] ret/$={d['ret']:+.3f} win={d['win']:.2f} {d['reasons']}"
# ---------------- signaux ----------------
def mid_hist(A, t, lb):
    ask, aage, bid, bage, P, _ = A
    lo = max(0, t - lb); m = (ask[lo:t + 1] + bid[lo:t + 1]) / 2
    ok = (aage[lo:t + 1] <= 3) & (bage[lo:t + 1] <= 3)
    return m[ok]
def sig_fade(D, lb, fv_gap=None, maxp=0.6):
    def f(w, side, t, A):
        ask, aage, bid, bage, P, _ = A
        if aage[t] > 1 or not np.isfinite(ask[t]) or ask[t] > maxp: return False
        h = mid_hist(A, t - 1, lb)
        if len(h) < 3 or np.max(h) - ask[t] < D: return False
        if fv_gap is not None and not (P[t] - ask[t] >= fv_gap): return False
        return True
    return f
def sig_unjustified_drop(D, lb, max_fv_drop):
    """Chute du prix >= D sur lb s alors que la FV a baissé de moins de max_fv_drop (candidat 'manipulation')."""
    def f(w, side, t, A):
        ask, aage, bid, bage, P, _ = A
        if aage[t] > 1 or not np.isfinite(ask[t]) or t - lb < 0: return False
        h = mid_hist(A, t - 1, lb)
        if len(h) < 3 or np.max(h) - ask[t] < D: return False
        return (P[t - lb] - P[t]) <= max_fv_drop
    return f
def sig_momo(D, lb, minp=0.3, maxp=0.8):
    def f(w, side, t, A):
        ask, aage, bid, bage, P, _ = A
        if aage[t] > 1 or not np.isfinite(ask[t]) or not (minp <= ask[t] <= maxp): return False
        h = mid_hist(A, t - 1, lb)
        return len(h) >= 3 and ask[t] - np.min(h) >= D
    return f
def sig_fvgap(e, tmin=15, tmax=270, pmin=0.05, pmax=0.95):
    def f(w, side, t, A):
        ask, aage, bid, bage, P, _ = A
        if not (tmin <= t <= tmax) or aage[t] > 1 or not np.isfinite(ask[t]) or not (pmin <= ask[t] <= pmax): return False
        return P[t] - ask[t] >= e
    return f
def sig_cheap(pmax, tmin, tmax):
    def f(w, side, t, A):
        ask, aage, bid, bage, P, _ = A
        return tmin <= t <= tmax and aage[t] <= 1 and np.isfinite(ask[t]) and ask[t] <= pmax
    return f
def sig_late_fav(pmin, pmax, tmin, fvmin):
    def f(w, side, t, A):
        ask, aage, bid, bage, P, _ = A
        return t >= tmin and aage[t] <= 1 and np.isfinite(ask[t]) and pmin <= ask[t] <= pmax and P[t] >= fvmin
    return f
if __name__ == '__main__':
    print('train', len(TRAIN), 'test', len(TEST))
    out = []
    def grid(name, sigf, params, exits, hold=False, max_entry_t=270):
        best = None
        for p in params:
            e = entries(TRAIN, sigf(*p), max_entry_t)
            for (tp, sl, tx) in exits:
                r = summarize(simulate(e, tp, sl, tx, hold=hold))
                if r['n'] >= 60 and (best is None or r['pnl_share'] > best[0]['pnl_share']): best = (r, p, (tp, sl, tx))
        if best is None: print(name, 'aucun paramétrage avec n>=60'); return
        r, p, ex = best
        e = entries(TEST, sigf(*p), max_entry_t)
        rt = summarize(simulate(e, *ex, hold=hold)); rt1 = summarize(simulate(e, *ex, hold=hold, slip=0.01)); rt3 = summarize(simulate(e, *ex, hold=hold, lat=3))
        print(f'\n== {name} best params={p} exits={ex}\n   TRAIN {fmt(r)}\n   TEST  {fmt(rt)}\n   TEST slip=1c {fmt(rt1)}\n   TEST lat=3s {fmt(rt3)}', flush=True)
    EX = [(tp, sl, tx) for tp in (0.05, 0.10, 0.20, 0.40) for sl in (0.05, 0.10, 0.20, 1.0) for tx in (240, 285)]
    grid('S1 fade (chute brute, achat du côté qui vient de chuter)', sig_fade, [(D, lb, None) for D in (0.10, 0.15, 0.25) for lb in (5, 15, 30)], EX)
    grid('S1b fade + FV confirme sous-évaluation', sig_fade, [(D, lb, g) for D in (0.10, 0.15, 0.25) for lb in (5, 15, 30) for g in (0.03, 0.08)], EX)
    grid('S1c chute NON justifiée par le spot (candidat manipulation)', sig_unjustified_drop, [(D, lb, f) for D in (0.10, 0.15, 0.25) for lb in (5, 15) for f in (0.0, 0.03)], EX)
    grid('S2 momentum', sig_momo, [(D, lb) for D in (0.10, 0.15, 0.25) for lb in (5, 15, 30)], EX)
    grid('S3 écart FV-marché, sortie active', sig_fvgap, [(e,) for e in (0.03, 0.05, 0.08, 0.12)], EX)
    grid('S3h écart FV-marché, garde jusqu\'à résolution', sig_fvgap, [(e,) for e in (0.03, 0.05, 0.08, 0.12)], [(1, 1, 300)], hold=True)
    grid('S4 longshot gardé', sig_cheap, [(pm, a, b) for pm in (0.05, 0.10, 0.15, 0.20) for (a, b) in ((15, 120), (120, 240), (240, 290))], [(1, 1, 300)], hold=True, max_entry_t=295)
    grid('S5 favori tardif gardé', sig_late_fav, [(a, b, t0, fv) for (a, b) in ((0.85, 0.95), (0.90, 0.97), (0.95, 0.99)) for t0 in (240, 270, 285) for fv in (0.0, 0.97, 0.99)], [(1, 1, 300)], hold=True, max_entry_t=298)
