import asyncio, json, time, websockets
VARIANTS = {
 "cl_star_json": [{"topic":"crypto_prices_chainlink","type":"*","filters":"{\"symbol\":\"btc/usd\"}"}],
 "cl_star_nofilter": [{"topic":"crypto_prices_chainlink","type":"*","filters":""}],
 "cl_update": [{"topic":"crypto_prices_chainlink","type":"update"}],
 "bn_update_nofilter": [{"topic":"crypto_prices","type":"update"}],
 "bn_star": [{"topic":"crypto_prices","type":"*","filters":"btcusdt"}],
}
async def run(name, subs):
    n={}; ex={}
    try:
      async with websockets.connect("wss://ws-live-data.polymarket.com", max_size=None) as ws:
        await ws.send(json.dumps({"action":"subscribe","subscriptions":subs}))
        t0=time.time(); last=t0
        while time.time()-t0<15:
            if time.time()-last>4: await ws.send("PING"); last=time.time()
            try: m=await asyncio.wait_for(ws.recv(),2)
            except asyncio.TimeoutError: continue
            if not m.strip() or m.strip()=="PONG": n['pong']=n.get('pong',0)+1; continue
            try: d=json.loads(m)
            except Exception: n['raw']=n.get('raw',0)+1; ex['raw']=m[:150]; continue
            p=d.get('payload',{}); k=(d.get('topic'),d.get('type'),p.get('symbol') if isinstance(p,dict) else None)
            n[k]=n.get(k,0)+1; ex.setdefault(k, json.dumps(d)[:300])
    except Exception as e: n['err']=repr(e)
    print(name, n); [print('   ',k,v) for k,v in ex.items()]
async def main(): await asyncio.gather(*(run(k,v) for k,v in VARIANTS.items()))
asyncio.run(main())
