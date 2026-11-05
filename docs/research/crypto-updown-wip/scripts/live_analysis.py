"""Analyse collecteur temps réel (jetable) : carnet L2, spread, profondeur, lead-lag ms."""
import sys, gzip, json, numpy as np, collections, glob, pickle
f = sorted(glob.glob('live/live_*.jsonl.gz'))[-1]
meta = {}; books = collections.defaultdict(lambda: {'bids': {}, 'asks': {}}); snaps = collections.defaultdict(list)
rt_bn = []; rt_cl = []; nmsg = collections.Counter(); last_snap = {}
tok2slug = {}
def best(b):
    bb = max(b['bids']) if b['bids'] else None; ba = min(b['asks']) if b['asks'] else None
    return bb, ba
def depth(b, side, ref, width):
    if ref is None: return 0.0, 0.0
    lv = b[side]
    if side == 'bids': sel = [(p, s) for p, s in lv.items() if p >= ref - width - 1e-9]
    else: sel = [(p, s) for p, s in lv.items() if p <= ref + width + 1e-9]
    return sum(s for p, s in sel), sum(p * s for p, s in sel)
with gzip.open(f, 'rt') as fh:
    for line in fh:
        try: r = json.loads(line)
        except Exception: break
        src = r['s']; d = r['d']; rns = r['r']
        if src == 'meta':
            meta[d['slug']] = d
            for i, tk in enumerate(d['tokens']): tok2slug[tk] = (d['slug'], i)
            continue
        if src == 'rtds':
            p = d['payload']
            (rt_bn if d['topic'] == 'crypto_prices' else rt_cl).append((rns / 1e9, p['timestamp'] / 1000, p['symbol'], p['value'], d.get('timestamp', 0) / 1000))
            continue
        if not src.startswith('clob:'): continue
        evs = d if isinstance(d, list) else [d]
        for e in evs:
            et = e.get('event_type'); nmsg[et] += 1
            changed = set()
            if et == 'book':
                b = books[e['asset_id']]; b['bids'] = {float(x['price']): float(x['size']) for x in e['bids']}
                b['asks'] = {float(x['price']): float(x['size']) for x in e['asks']}; changed.add(e['asset_id'])
            elif et == 'price_change':
                for c in e['price_changes']:
                    b = books[c['asset_id']]; side = 'bids' if c['side'] == 'BUY' else 'asks'; p = float(c['price']); s = float(c['size'])
                    if s == 0: b[side].pop(p, None)
                    else: b[side][p] = s
                    changed.add(c['asset_id'])
            for a in changed:
                if a not in tok2slug: continue
                slug, idx = tok2slug[a]; m = meta[slug]; t_rel = rns / 1e9 - m['start']
                b = books[a]; bb, ba = best(b)
                # échantillonnage : au plus 1 snapshot / 200 ms par token
                key = (a, int(rns / 2e8))
                if key in last_snap: continue
                last_snap[key] = 1
                d1b = depth(b, 'bids', bb, 0.01); d1a = depth(b, 'asks', ba, 0.01)
                d5b = depth(b, 'bids', bb, 0.05); d5a = depth(b, 'asks', ba, 0.05)
                snaps[slug].append((rns / 1e9, t_rel, idx, bb, ba, d1b[1], d1a[1], d5b[1], d5a[1],
                                    b['bids'].get(bb, 0) if bb else 0, b['asks'].get(ba, 0) if ba else 0))
print('fichier', f, 'messages', dict(nmsg), 'rtds binance', len(rt_bn), 'chainlink', len(rt_cl))
pickle.dump(dict(meta=meta, snaps=dict(snaps), rt_bn=rt_bn, rt_cl=rt_cl), open('live_parsed.pkl', 'wb'))
# --------- stats carnet par tranche de temps (token Up, marchés 5m) -------
print('\nCarnet token Up, fenêtres 5m (snapshots 200ms) : médianes par tranche')
print(' tranche   n     spread  best_bid_sz$  best_ask_sz$  depth1c bid$ ask$   depth5c bid$ ask$   %spread<=1c')
for a0, a1 in [(-150, 0), (0, 60), (60, 120), (120, 180), (180, 240), (240, 270), (270, 290), (290, 300), (300, 400)]:
    rows = [s for slug, L in snaps.items() if '-5m-' in slug for s in L if s[2] == 0 and a0 <= s[1] < a1 and s[3] is not None and s[4] is not None]
    if not rows: continue
    A = np.array([[s[4] - s[3], s[9] * s[3], s[10] * s[4], s[5], s[6], s[7], s[8]] for s in rows])
    md = np.median(A, axis=0)
    print(f' [{a0:4d},{a1:4d}) {len(rows):6d}  {md[0]:.3f}   {md[1]:9.0f}  {md[2]:9.0f}     {md[3]:7.0f} {md[4]:7.0f}   {md[5]:7.0f} {md[6]:7.0f}    {np.mean(A[:, 0] <= 0.0101):.2f}')
# --------- stats par niveau de prix -------
print('\nPar niveau de mid (token Up+Down, 5m, t in [0,290)) : spread médian, profondeur 5c côté bid (= ce qu\'on peut REVENDRE)')
rows = [s for slug, L in snaps.items() if '-5m-' in slug for s in L if 0 <= s[1] < 290 and s[3] is not None and s[4] is not None]
for lo, hi in [(0, .1), (.1, .2), (.2, .35), (.35, .65), (.65, .8), (.8, .9), (.9, 1)]:
    R = [s for s in rows if lo <= (s[3] + s[4]) / 2 < hi]
    if len(R) < 20: continue
    A = np.array([[s[4] - s[3], s[7], s[8], s[5]] for s in R])
    print(f'  mid [{lo:.2f},{hi:.2f}) n={len(R):6d} spread={np.median(A[:, 0]):.3f} p90={np.percentile(A[:, 0], 90):.3f}  bid depth1c$={np.median(A[:, 3]):.0f} bid depth5c$ med={np.median(A[:, 1]):.0f} p10={np.percentile(A[:, 1], 10):.0f}  ask depth5c$={np.median(A[:, 2]):.0f}')
# --------- latence RTDS -------
bn = np.array([(r[0], r[1], r[3]) for r in rt_bn if r[2] == 'btcusdt']); cl = np.array([(r[0], r[1], r[3]) for r in rt_cl if r[2] == 'btc/usd'])
if len(bn) and len(cl):
    print('\nRTDS délai réception - timestamp source : Binance médiane %.3fs p90 %.3fs | Chainlink médiane %.3fs p90 %.3fs' % (
        np.median(bn[:, 0] - bn[:, 1]), np.percentile(bn[:, 0] - bn[:, 1], 90), np.median(cl[:, 0] - cl[:, 1]), np.percentile(cl[:, 0] - cl[:, 1], 90)))
    print('fréquence updates : Binance %.2f/s, Chainlink %.2f/s' % (len(bn) / (bn[-1, 0] - bn[0, 0]), len(cl) / (cl[-1, 0] - cl[0, 0])))
    # basis Binance - Chainlink, et décalage optimal (Chainlink suit-il Binance avec retard ?)
    bmap = {int(t): v for _, t, v in bn}; cmap = {int(t): v for _, t, v in cl}
    common = sorted(set(bmap) & set(cmap)); basis = np.array([bmap[t] - cmap[t] for t in common])
    print('basis Binance(USDT) - Chainlink(USD) $ : médiane %.1f  écart-type %.1f' % (np.median(basis), np.std(basis)))
    for lag in (-3, -2, -1, 0, 1, 2, 3, 5):
        xs = []; ys = []
        for t in common:
            if t - 1 in bmap and t + lag in cmap and t + lag - 1 in cmap:
                xs.append(bmap[t] - bmap[t - 1]); ys.append(cmap[t + lag] - cmap[t + lag - 1])
        if len(xs) > 50: print(f'   corr(ΔBinance(t), ΔChainlink(t{lag:+d})) = {np.corrcoef(xs, ys)[0, 1]:.3f}')
# --------- lead-lag Binance -> mid carnet (bins 250 ms) -------
print('\nLead-lag : corr(Δ Binance reçu, Δ mid Up carnet) par décalage (bins 250 ms, fenêtres 5m, t in [10,280])')
bins = 0.25
bin_bn = {}
for rt, ts, v in bn: bin_bn[int(rt / bins)] = v
for lagb in (-4, -2, -1, 0, 1, 2, 3, 4, 6, 8, 12):
    xs = []; ys = []
    for slug, L in snaps.items():
        if '-5m-' not in slug: continue
        mids = {}
        for s in L:
            if s[2] == 0 and s[3] is not None and s[4] is not None and 10 <= s[1] < 280: mids[int(s[0] / bins)] = (s[3] + s[4]) / 2
        keys = sorted(mids)
        # ffill binance
        for k in keys:
            if k - 1 in mids and (k - lagb) in bin_bn and (k - lagb - 1) in bin_bn:
                xs.append(bin_bn[k - lagb] - bin_bn[k - lagb - 1]); ys.append(mids[k] - mids[k - 1])
    if len(xs) > 100: print(f'   Binance mène de {lagb * bins:+.2f}s : corr={np.corrcoef(xs, ys)[0, 1]:.3f} n={len(xs)}')
