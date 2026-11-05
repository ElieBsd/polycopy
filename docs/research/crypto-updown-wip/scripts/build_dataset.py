"""Dataset historique jetable : fenêtres BTC 5m (Gamma) + trades (Data API v2) + spot 1s (Binance vision)."""
import asyncio, json, time, sys, os, gzip
import httpx
OUT = sys.argv[1]; DAYS = float(sys.argv[2]); ASSET = sys.argv[3] if len(sys.argv) > 3 else "btc"; DUR = int(sys.argv[4]) if len(sys.argv) > 4 else 300
TAG = {300: "5m", 900: "15m"}[DUR]
os.makedirs(OUT, exist_ok=True)
end = int(time.time()) // DUR * DUR - 2 * DUR
start = end - int(DAYS * 86400) // DUR * DUR
starts = list(range(start, end, DUR))
sem = asyncio.Semaphore(6)
async def get(c, url, params=None):
    for i in range(6):
        try:
            async with sem:
                r = await c.get(url, params=params, timeout=30)
            if r.status_code == 429: await asyncio.sleep(2 ** i); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == 5: print("FAIL", url, params if not isinstance(params, list) else len(params), repr(e), flush=True); return None
            await asyncio.sleep(1 + i)
async def gamma_batch(c, chunk):
    params = [("closed", "true"), ("limit", "100")] + [("slug", f"{ASSET}-updown-{TAG}-{s}") for s in chunk]
    return await get(c, "https://gamma-api.polymarket.com/markets", params) or []
async def trades(c, cid):
    out = []; cur = None; pages = 0
    while True:
        params = {"condition": cid, "limit": 1000}
        if cur: params["cursor"] = cur
        d = await get(c, "https://data-api.polymarket.com/v2/trades", params)
        if not d: break
        out += d["data"]; pages += 1
        cur = d["pagination"].get("next_cursor")
        if not d["pagination"].get("has_more") or not cur: break
        if pages > 30: print("too many trades", cid, flush=True); break
    return out
async def main():
    async with httpx.AsyncClient(http2=False) as c:
        chunks = [starts[i:i+50] for i in range(0, len(starts), 50)]
        res = await asyncio.gather(*(gamma_batch(c, ch) for ch in chunks))
        markets = {}
        for lst in res:
            for m in lst:
                e = (m.get("events") or [{}])[0]
                markets[m["slug"]] = dict(slug=m["slug"], start=int(m["slug"].rsplit("-", 1)[1]), cid=m["conditionId"],
                    tokens=json.loads(m["clobTokenIds"]), outcomes=json.loads(m["outcomes"]), prices=json.loads(m["outcomePrices"]),
                    meta=e.get("eventMetadata"), volume=float(m.get("volume") or 0), cfg=m.get("cryptoMarketConfig"),
                    fee=m.get("feeSchedule"), closed_time=m.get("closedTime"), res_src=m.get("resolutionSource"),
                    tick=m.get("orderPriceMinTickSize"), created=m.get("createdAt"), accepting_ts=m.get("acceptingOrdersTimestamp"))
        print("markets", len(markets), "of", len(starts), flush=True)
        json.dump(markets, open(f"{OUT}/markets.json", "w"))
        slugs = sorted(markets); done = 0
        fh = gzip.open(f"{OUT}/trades.jsonl.gz", "wt")
        async def one(s):
            nonlocal done
            t = await trades(c, markets[s]["cid"])
            up = markets[s]["tokens"][0]
            rows = [[x["timestamp"], 1 if x["token_id"] == up else 0, 1 if x["side"] == "BUY" else 0, x["price"], x["size"], x["proxy_wallet"]] for x in t]
            fh.write(json.dumps({"slug": s, "trades": rows}) + "\n"); done += 1
            if done % 250 == 0: print("trades done", done, flush=True)
        for i in range(0, len(slugs), 60):
            await asyncio.gather(*(one(s) for s in slugs[i:i+60]))
        fh.close()
        # spot 1s Binance vision
        fh = gzip.open(f"{OUT}/spot_1s.jsonl.gz", "wt"); sym = ASSET.upper() + "USDT"
        t0 = (start - 900) * 1000; t1 = (end + DUR) * 1000; reqs = list(range(t0, t1, 1000 * 1000))
        async def kl(a):
            d = await get(c, "https://data-api.binance.vision/api/v3/klines", {"symbol": sym, "interval": "1s", "startTime": a, "endTime": a + 999 * 1000, "limit": 1000})
            return [[k[0] // 1000, float(k[1]), float(k[4]), float(k[5])] for k in (d or [])]
        for i in range(0, len(reqs), 30):
            for rows in await asyncio.gather(*(kl(a) for a in reqs[i:i+30])):
                for r in rows: fh.write(json.dumps(r) + "\n")
        fh.close(); print("spot done", flush=True)
asyncio.run(main())
