"""Modèle de juste valeur TWAP (jetable)."""
import numpy as np
from math import erf, sqrt, log
def Phi(x): return 0.5 * (1 + erf(x / sqrt(2)))
def build_spot_path(spot, s0, dur, pre=1800, post=120):
    """Array spot Binance par seconde de s0-pre à s0+dur+post (ffill)."""
    n = pre + dur + post; a = np.full(n, np.nan); last = np.nan
    for i in range(n):
        v = spot.get(s0 - pre + i)
        if v is not None: last = v
        a[i] = last
    return a
def fair_values(S, K, s_idx0, dur=300, L=60, vol_window=1800):
    """S: spot (Binance) par seconde, index s_idx0 = début de fenêtre. K = price to beat (Chainlink TWAP).
    Retourne P(Up) pour t = 0..dur-1 (information jusqu'à t inclus), sigma utilisée, basis."""
    pre = S[s_idx0 - vol_window: s_idx0]
    r = np.diff(np.log(pre)); r = r[np.isfinite(r)]
    sig = np.std(r) if len(r) > 100 else np.nan   # vol par seconde (log) estimée AVANT la fenêtre
    basis = np.nanmean(S[s_idx0 - L + 1: s_idx0 + 1]) - K    # TWAP Binance à l'ouverture vs K (Chainlink)
    P = np.full(dur, np.nan)
    E = s_idx0 + dur
    for t in range(dur):
        i = s_idx0 + t; c = S[i] - basis; tau = dur - t
        sd_abs = sig * c
        if tau >= L:
            mean = c; var = sd_abs ** 2 * (tau - L + L / 3.0)
        else:
            known = S[E - L + 1: i + 1] - basis      # secondes déjà dans la fenêtre TWAP
            mean = (known.sum() + tau * c) / L
            var = sd_abs ** 2 * tau ** 3 / (3.0 * L * L)
        P[t] = Phi((mean - K) / sqrt(var)) if var > 0 else (1.0 if mean >= K else 0.0)
    return P, sig, basis
