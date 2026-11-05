"""Collecteur temps réel jetable : carnet CLOB (BTC 5m + 15m) + RTDS (Chainlink + Binance)."""
import asyncio, json, time, gzip, sys, urllib.request, os
import websockets
OUT = sys.argv[1]; DURATION = int(sys.argv[2])
T_END = time.time() + DURATION
fh = gzip.open(OUT, "at")
def w(src, payload):
    fh.write(json.dumps({"r": time.time_ns(), "s": src, "d": payload}) + "\n")
def gamma(slug):
    for _ in range(5):
        try:
            with urllib.request.urlopen(f"https://gamma-api.polymarket.com/markets?slug={slug}", timeout=15) as r:
                d = json.load(r)
                if d: return d[0]
        except Exception as e:
            print("gamma err", slug, e, flush=True)
        time.sleep(2)
    return None
async def window_task(slug, start, end):
    await asyncio.sleep(max(0, start - 150 - time.time()))
    m = await asyncio.to_thread(gamma, slug)
    if not m: print("no market", slug, flush=True); return
    toks = json.loads(m["clobTokenIds"])
    w("meta", {"slug": slug, "start": start, "end": end, "condition_id": m["conditionId"], "tokens": toks,
               "outcomes": m["outcomes"], "tick": m.get("orderPriceMinTickSize"), "min_size": m.get("orderMinSize"),
               "fee": m.get("feeSchedule"), "cfg": m.get("cryptoMarketConfig")})
    stop = min(end + 100, T_END)
    while time.time() < stop:
        try:
            async with websockets.connect("wss://ws-subscriptions-clob.polymarket.com/ws/market", max_size=None, ping_interval=10) as ws:
                await ws.send(json.dumps({"type": "market", "assets_ids": toks, "custom_feature_enabled": True}))
                w("sub", {"slug": slug})
                while time.time() < stop:
                    try: msg = await asyncio.wait_for(ws.recv(), 5)
                    except asyncio.TimeoutError: continue
                    w("clob:" + slug, json.loads(msg))
        except Exception as e:
            print("clob err", slug, repr(e), flush=True); await asyncio.sleep(1)
    print("done", slug, flush=True)
async def rtds():
    while time.time() < T_END:
        try:
            async with websockets.connect("wss://ws-live-data.polymarket.com", max_size=None) as ws:
                await ws.send(json.dumps({"action": "subscribe", "subscriptions": [
                    {"topic": "crypto_prices_chainlink", "type": "update"},
                    {"topic": "crypto_prices", "type": "update"}]}))
                last = time.time()
                while time.time() < T_END:
                    if time.time() - last > 4: await ws.send("PING"); last = time.time()
                    try: msg = await asyncio.wait_for(ws.recv(), 2)
                    except asyncio.TimeoutError: continue
                    if not msg.strip() or msg.strip() == "PONG": continue
                    d = json.loads(msg); p = d.get("payload", {})
                    if isinstance(p, dict) and p.get("symbol") in ("btc/usd", "btcusdt", "eth/usd", "ethusdt"):
                        w("rtds", d)
        except Exception as e:
            print("rtds err", repr(e), flush=True); await asyncio.sleep(1)
async def flusher():
    while time.time() < T_END + 200:
        await asyncio.sleep(10); fh.flush()
async def main():
    now = time.time(); tasks = [asyncio.create_task(rtds()), asyncio.create_task(flusher())]
    s5 = int(now) // 300 * 300 + 300
    while s5 < T_END:
        tasks.append(asyncio.create_task(window_task(f"btc-updown-5m-{s5}", s5, s5 + 300))); s5 += 300
    s15 = int(now) // 900 * 900 + 900
    while s15 < T_END:
        tasks.append(asyncio.create_task(window_task(f"btc-updown-15m-{s15}", s15, s15 + 900))); s15 += 900
    await asyncio.gather(*tasks, return_exceptions=True)
    fh.close(); print("collector finished", flush=True)
asyncio.run(main())
