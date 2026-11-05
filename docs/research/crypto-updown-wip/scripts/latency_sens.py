import sys; sys.argv=['x','W_btc5m.pkl']; sys.path.insert(0,'scripts')
from backtest import *
cases = [('S3h FV gap 0.12 hold', sig_fvgap(0.12), (1,1,300), True),
         ('S3 FV gap 0.12 active', sig_fvgap(0.12), (0.4,0.1,285), False),
         ('S1c unjustified drop', sig_unjustified_drop(0.25,15,0.0), (0.4,0.1,285), False),
         ('S1b fade+FV', sig_fade(0.25,5,0.08), (0.2,0.1,240), False),
         ('S1 fade brut', sig_fade(0.25,5,None), (0.1,0.1,240), False)]
for name, sg, ex, hold in cases:
    e = entries(TEST, sg)
    line = []
    for lat in (1,2,3,4,5,6,8):
        r = summarize(simulate(e, *ex, lat=lat, hold=hold, slip=0.01))
        line.append(f"lat{lat}:{r['pnl_share']:+.3f}[{r['ci'][0]:+.3f},{r['ci'][1]:+.3f}]")
    print(name, '(slip 1c, TEST)', ' '.join(line), flush=True)
