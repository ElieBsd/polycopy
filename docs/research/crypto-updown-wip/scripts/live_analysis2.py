"""Live 2 : décalage horodatage Data API vs WS, lead-lag ms Binance->carnet, durée de vie des écarts FV (jetable)."""
import gzip, json, zlib, collections, numpy as np, urllib.request, sys, pickle
from math import erf, sqrt
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
F = sys.argv[1]
meta = {}; tok = {}; bba = collections.defaultdict(list); ltp = []; bn = []; cl = []
f = gzip.open(F, 'rt')
try:
    for line in f:
        r = json.loads(line); d = r['d']; rs = r['r'] / 1e9
        if r['s'] == 'meta':
            meta[d['slug']] = d
            for i, t in enumerate(d['tokens']): tok[t] = (d['slug'], i)
        elif r['s'] == 'rtds':
            p = d['payload']
            if p['symbol'] == 'btcusdt': bn.append((rs, p['timestamp'] / 1000, p['value']))
            elif p['symbol'] == 'btc/usd': cl.append((rs, p['timestamp'] / 1000, p['value']))
        elif r['s'].startswith('clob:'):
            for e in (d if isinstance(d, list) else [d]):
                et = e.get('event_type')
                if et == 'best_bid_ask' and e['asset_id'] in tok:
                    bba[e['asset_id']].append((rs, int(e['timestamp']) / 1000, float(e['best_bid'] or 0), float(e['best_ask'] or 1)))
                elif et == 'price_change':
                    ts = int(e['timestamp']) / 1000
                    for c in e['price_changes']:
                        if c['asset_id'] in tok and c.get('best_bid') is not None:
                            bba[c['asset_id']].append((rs, ts, float(c['best_bid'] or 0), float(c['best_ask'] or 1)))
                elif et == 'last_trade_price' and e['asset_id'] in tok:
                    ltp.append((rs, int(e['timestamp']) / 1000, e['transaction_hash'], e['asset_id'], float(e['price']), float(e['size']), e['side']))
except (EOFError, json.JSONDecodeError, zlib.error) as ex:
    print('fin de lecture', repr(ex)[:60])
print('fenêtres', len(meta), 'bba', sum(len(v) for v in bba.values()), 'ltp', len(ltp), 'binance', len(bn), 'chainlink', len(cl))
# ---- 1. latence serveur -> réception ----
lat = np.array([x[0] - x[1] for v in bba.values() for x in v]); print('\n[1] délai réception WS carnet - timestamp serveur : médiane %.3fs p90 %.3fs p99 %.3fs' % tuple(np.percentile(lat, [50, 90, 99])))
lt = np.array([x[0] - x[1] for x in ltp]); print('    last_trade_price : médiane %.3fs p90 %.3fs' % tuple(np.percentile(lt, [50, 90])))
# ---- 2. décalage timestamps Data API v2 vs WS (même transaction_hash) ----
def get(u):
    with urllib.request.urlopen(u, timeout=30) as r: return json.load(r)
api = {}
for slug, m in meta.items():
    cur = None
    for _ in range(10):
        u = f"https://data-api.polymarket.com/v2/trades?condition={m['condition_id']}&limit=1000" + (f"&cursor={cur}" if cur else '')
        try: d = get(u)
        except Exception as e: print('api err', slug, e); break
        for t in d['data']: api.setdefault(t['transaction_hash'], t['timestamp'])
        cur = d['pagination'].get('next_cursor')
        if not d['pagination'].get('has_more') or not cur: break
off = np.array([api[x[2]] - x[1] for x in ltp if x[2] in api])
print('\n[2] trades appariés par tx hash', len(off), '/', len(ltp), ': timestamp Data API - timestamp WS (s) médiane %.2f p10 %.2f p90 %.2f' % tuple(np.percentile(off, [50, 10, 90])) if len(off) else 'aucun')
# ---- 3. lead-lag Binance (reçu) -> mid carnet (reçu), bins 100 ms ----
B = 0.1
def series(points, key_t=0):
    s = {}
    for p in points: s[int(p[key_t] / B)] = p
    return s
bn_s = {}
for rs, ts, v in bn: bn_s[int(rs / B)] = v
keys = sorted(bn_s); bn_ff = {}; last = None; k0, k1 = keys[0], keys[-1]
for k in range(k0, k1 + 1):
    if k in bn_s: last = bn_s[k]
    bn_ff[k] = last
print('\n[3] corr(Δ Binance reçu sur 1 s finissant à t−lag, Δ mid Up sur [t, t+0.1s]) — fenêtres 5m, t in [10,280]s')
res = {}
for lagb in (-10, -5, 0, 2, 5, 8, 10, 15, 20, 25, 30, 40, 60):
    xs = []; ys = []
    for a, L in bba.items():
        slug, idx = tok[a]
        if idx != 0 or '-5m-' not in slug: continue
        st = meta[slug]['start']; mid = {}
        for rs, ts, b, k in L:
            if 10 <= rs - st < 280 and b > 0 and k < 1: mid[int(rs / B)] = (b + k) / 2
        ks = sorted(mid); mff = {}; lastm = None
        for k in range(ks[0], ks[-1] + 1) if ks else []:
            if k in mid: lastm = mid[k]
            mff[k] = lastm
        for k in range(ks[0] + 1, ks[-1]) if ks else []:
            kb = k - lagb
            if kb in bn_ff and kb - 10 in bn_ff and k + 1 in mff and bn_ff[kb] and bn_ff[kb - 10]:
                xs.append(bn_ff[kb] - bn_ff[kb - 10]); ys.append(mff[k + 1] - mff[k])
    if len(xs) > 100: res[lagb] = np.corrcoef(xs, ys)[0, 1]; print(f'   lag {lagb * B:+.1f}s : corr={res[lagb]:.3f} n={len(xs)}')
# ---- 4. durée de vie d'un écart FV vs carnet (Binance seulement) ----
# K des fenêtres live via Gamma (closed=true)
Kmap = {}
for slug in meta:
    try:
        d = get(f"https://gamma-api.polymarket.com/markets?closed=true&slug={slug}")
        if d: Kmap[slug] = (d[0]['events'][0]['eventMetadata']['priceToBeat'], json.loads(d[0]['outcomePrices'])[0] == '1')
    except Exception: pass
print('\n[4] fenêtres résolues avec priceToBeat', len(Kmap))
cl_s = {}
for rs, ts, v in cl: cl_s[int(rs)] = v
bn_sec = {}
for rs, ts, v in bn: bn_sec[int(rs)] = v
pickle.dump(dict(meta=meta, bba=dict(bba), ltp=ltp, bn=bn, cl=cl, Kmap=Kmap, api_offsets=off.tolist()), open('live2.pkl', 'wb'))
