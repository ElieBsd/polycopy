"""Chargement + reconstruction seconde par seconde (jetable)."""
import json, gzip, numpy as np
D = None
def load(path='data_btc5m', dur=300):
    M = json.load(open(f'{path}/markets.json'))
    T = {}
    with gzip.open(f'{path}/trades.jsonl.gz', 'rt') as f:
        for line in f:
            r = json.loads(line); T[r['slug']] = r['trades']
    spot = {}
    try:
        with gzip.open(f'{path}/spot_1s.jsonl.gz', 'rt') as f:
            for line in f:
                t, o, c, v = json.loads(line); spot[t] = c
    except FileNotFoundError: pass
    return M, T, spot
PRE, POST = 120, 120
def window_arrays(m, trades, dur=300):
    """Retourne dict d'arrays indexés par seconde relative (−PRE .. dur+POST).
    ask_up : dernier prix auquel un taker a ACHETÉ Up (BUY Up p, ou SELL Down q -> 1-q)
    bid_up : dernier prix auquel un taker a VENDU Up (SELL Up p, ou BUY Down q -> 1-q)
    + volumes/trades par seconde."""
    s0 = m['start']; n = PRE + dur + POST
    ask = np.full(n, np.nan); bid = np.full(n, np.nan); ask_t = np.full(n, -1e9); bid_t = np.full(n, -1e9)
    ask_sz = np.zeros(n); bid_sz = np.zeros(n); ntr = np.zeros(n); notional = np.zeros(n)
    ev = []
    for ts, is_up, is_buy, p, sz, w in trades:
        i = ts - s0 + PRE
        if i < 0 or i >= n: continue
        up_eq = p if is_up else 1 - p
        side_ask = (is_up and is_buy) or ((not is_up) and (not is_buy))
        ev.append((i, side_ask, up_eq, sz))
        ntr[i] += 1; notional[i] += p * sz
    ev.sort()
    la = np.nan; lb = np.nan; lat = -1e9; lbt = -1e9; k = 0
    for i in range(n):
        # min ask / max bid observés dans la seconde i
        sa = []; sb = []
        while k < len(ev) and ev[k][0] == i:
            _, a, pr, sz = ev[k]
            (sa if a else sb).append((pr, sz)); k += 1
        if sa: la = min(x[0] for x in sa); lat = i; ask_sz[i] = sum(x[1] for x in sa)
        if sb: lb = max(x[0] for x in sb); lbt = i; bid_sz[i] = sum(x[1] for x in sb)
        ask[i] = la; bid[i] = lb; ask_t[i] = lat; bid_t[i] = lbt
    return dict(ask=ask, bid=bid, ask_age=np.arange(n) - ask_t, bid_age=np.arange(n) - bid_t,
                ask_sz=ask_sz, bid_sz=bid_sz, ntr=ntr, notional=notional, ev=ev)
