import asyncio, json, time, sys, urllib.request
import websockets
def gamma(slug):
    with urllib.request.urlopen(f"https://gamma-api.polymarket.com/markets?slug={slug}", timeout=15) as r:
        return json.load(r)[0]
async def clob(tokens):
    async with websockets.connect("wss://ws-subscriptions-clob.polymarket.com/ws/market", max_size=None) as ws:
        await ws.send(json.dumps({"type":"market","assets_ids":tokens,"custom_feature_enabled":True}))
        t0=time.time(); n={}
        while time.time()-t0<12:
            m=await asyncio.wait_for(ws.recv(),15)
            d=json.loads(m)
            for e in (d if isinstance(d,list) else [d]):
                et=e.get('event_type'); n[et]=n.get(et,0)+1
                if n[et]<=1: print('CLOB',et,json.dumps(e)[:700])
        print('CLOB counts 12s',n)
async def rtds():
    async with websockets.connect("wss://ws-live-data.polymarket.com", max_size=None) as ws:
        await ws.send(json.dumps({"action":"subscribe","subscriptions":[
          {"topic":"crypto_prices_chainlink","type":"*","filters":json.dumps({"symbol":"btc/usd"})},
          {"topic":"crypto_prices","type":"update","filters":"btcusdt"}]}))
        t0=time.time(); n={}
        while time.time()-t0<12:
            try: m=await asyncio.wait_for(ws.recv(),6)
            except asyncio.TimeoutError: await ws.send("PING"); continue
            if not m.strip(): continue
            try: d=json.loads(m)
            except Exception: print('RTDS raw',m[:200]); continue
            k=(d.get('topic'),d.get('type')); n[k]=n.get(k,0)+1
            if n[k]<=2: print('RTDS',json.dumps(d)[:600])
        print('RTDS counts 12s',n)
async def main():
    ts=int(time.time())//300*300
    m=gamma(f"btc-updown-5m-{ts}"); toks=json.loads(m['clobTokenIds'])
    await asyncio.gather(clob(toks), rtds())
asyncio.run(main())
