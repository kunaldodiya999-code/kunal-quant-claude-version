from __future__ import annotations
import argparse, csv, json, sqlite3, time
from collections import defaultdict
from pathlib import Path

from api.fyers_client import FyersClient
from config.hft_data import HFT_RESOLUTION, HFT_FETCH_RESOLUTION, HFT_SOURCE
from config.settings import DATABASE_PATH, RAW_DATA_DIR

class HFTDownloader:
    def __init__(self, dry_run=False, attempts=3, delay=1.0):
        self.client=FyersClient(); self.dry_run=dry_run; self.attempts=attempts; self.delay=delay
        self.raw=RAW_DATA_DIR/"historical_hft_10s"; self.raw.mkdir(parents=True,exist_ok=True)
    def connect(self):
        c=sqlite3.connect(DATABASE_PATH); c.row_factory=sqlite3.Row; return c
    def instrument_id(self,c,symbol):
        r=c.execute("SELECT id FROM instruments WHERE broker='FYERS' AND symbol=?",(symbol,)).fetchone()
        if not r: raise ValueError(f"Instrument not registered: {symbol}")
        return int(r[0])
    def download_one(self,symbol,day,mode):
        if self.dry_run: return {"symbol":symbol,"day":day,"status":"DRY_RUN","received":0,"inserted":0}
        for attempt in range(1,self.attempts+1):
            try:
                if mode=="standard":
                    response=self.client.history(symbol=symbol,resolution=HFT_FETCH_RESOLUTION,
                        range_from=day,range_to=day,date_format="1",cont_flag="0")
                else:
                    response=self.client.expired_history(symbol=symbol,resolution=HFT_FETCH_RESOLUTION,
                        range_from=day,range_to=day,include_oi="1",include_greeks="1",date_format="1")
                break
            except Exception as e:
                if attempt==self.attempts: return {"symbol":symbol,"day":day,"status":"FAILED","error":str(e)}
                time.sleep(self.delay*attempt)
        candles=response.get("candles") or []
        if not candles:
            return {"symbol": symbol, "day": day, "status": "NO_DATA",
                    "received": 0, "inserted": 0, "duplicates": 0}
        safe=symbol.replace(":","_").replace("/","_")
        rp=self.raw/safe; rp.mkdir(parents=True,exist_ok=True)
        raw=rp/f"{day}_{HFT_FETCH_RESOLUTION}_{HFT_SOURCE}.json"
        raw.write_text(json.dumps(response,indent=2,default=str),encoding="utf-8")
        with self.connect() as c:
            iid=self.instrument_id(c,symbol)
            # FYERS historical API supports 5S, not 10S. Build complete 10S candles locally.
            buckets=defaultdict(list)
            for x in candles:
                if len(x)<6: continue
                ts=int(float(x[0])); buckets[ts-(ts % 10)].append(x)
            derived=[]
            for bucket, xs in sorted(buckets.items()):
                xs=sorted(xs,key=lambda z:int(float(z[0])))
                if len(xs) < 2: continue
                derived.append((bucket,float(xs[0][1]),max(float(z[2]) for z in xs),
                    min(float(z[3]) for z in xs),float(xs[-1][4]),
                    sum(float(z[5]) for z in xs if z[5] is not None),
                    int(float(xs[-1][6])) if len(xs[-1])>=7 and xs[-1][6] is not None else None))
            inserted=0; dup=0
            for ts,o,h,l,cl,vol,oi in derived:
                vals=(iid,int(ts),o,h,l,cl,int(vol),oi,HFT_RESOLUTION,HFT_SOURCE)
                cur=c.execute("INSERT OR IGNORE INTO candles"
                  "(instrument_id,timestamp,open,high,low,close,volume,open_interest,resolution,source)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?)",vals)
                if cur.rowcount: inserted+=1
                else: dup+=1
            c.commit()
        return {"symbol":symbol,"day":day,"status":"COMPLETED","received":len(candles),
                "inserted":inserted,"duplicates":dup}
    def run(self,manifest_path,limit=None):
        with open(manifest_path,encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
        jobs=sorted({(r["symbol"],r["trade_date"],"standard" if r["kind"]=="INDEX" else "expired")
                     for r in rows if r["kind"] in {"INDEX","OPTION","FUTURES"}})
        if limit: jobs=jobs[:limit]
        results=[]
        for i,(sym,day,mode) in enumerate(jobs,1):
            print(f"[{i}/{len(jobs)}] {sym} {day} {mode}")
            results.append(self.download_one(sym,day,mode))
        return results

def main():
    p=argparse.ArgumentParser(description="Targeted FYERS 5S download with local 10S derivation. Defaults to dry-run.")
    p.add_argument("--manifest",required=True); p.add_argument("--run",action="store_true")
    p.add_argument("--limit",type=int); p.add_argument("--json",default="data/reports/hft_10s_download.json")
    args=p.parse_args()
    d=HFTDownloader(dry_run=not args.run)
    results=d.run(args.manifest,args.limit)
    summary={"resolution":HFT_RESOLUTION,"source":HFT_SOURCE,"jobs":len(results),
             "completed":sum(x["status"]=="COMPLETED" for x in results),
             "failed":sum(x["status"]=="FAILED" for x in results),
             "no_data":sum(x["status"]=="NO_DATA" for x in results),
             "dry_run":not args.run,"results":results}
    Path(args.json).parent.mkdir(parents=True,exist_ok=True); Path(args.json).write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
if __name__=="__main__": main()
