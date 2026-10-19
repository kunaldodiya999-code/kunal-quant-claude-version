from __future__ import annotations
import argparse, csv, json, sqlite3
from pathlib import Path
from config.hft_data import HFT_RESOLUTION,HFT_SOURCE
from config.settings import DATABASE_PATH

def main():
    p=argparse.ArgumentParser(description="Validate acquired HFT 10s coverage against the manifest.")
    p.add_argument("--manifest",required=True); p.add_argument("--json",default="data/reports/hft_10s_coverage.json")
    args=p.parse_args()
    with open(args.manifest,encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
    jobs=sorted({(r["symbol"],r["trade_date"],r["kind"]) for r in rows if r["kind"] in {"OPTION","FUTURES"}})
    with sqlite3.connect(DATABASE_PATH) as c:
        report=[]
        for sym,day,kind in jobs:
            n=c.execute("""
              SELECT COUNT(*) FROM candles c JOIN instruments i ON i.id=c.instrument_id
              WHERE i.broker='FYERS' AND i.symbol=? AND c.resolution=? AND c.source=?
                AND c.timestamp BETWEEN strftime('%s',?||' 00:00:00') AND strftime('%s',?||' 23:59:59')
            """,(sym,HFT_RESOLUTION,HFT_SOURCE,day,day)).fetchone()[0]
            report.append({"symbol":sym,"trade_date":day,"kind":kind,"candles":n,
                           "ok":n>0})
    summary={"resolution":HFT_RESOLUTION,"source":HFT_SOURCE,"jobs":len(report),
             "ok":sum(x["ok"] for x in report),"missing":sum(not x["ok"] for x in report),
             "report":report}
    Path(args.json).parent.mkdir(parents=True,exist_ok=True); Path(args.json).write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k!="report"},indent=2))
    if summary["missing"]: raise SystemExit(2)
if __name__=="__main__": main()
