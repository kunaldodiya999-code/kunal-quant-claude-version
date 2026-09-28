"""
Read-only audit of the 30 contracts repaired for the bounded 2026 sample.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path
from collections import defaultdict

HERE=Path(__file__).resolve().parent
PROPOSAL_ROOT=HERE.parent
CANONICAL_ROOT=HERE.parents[1]
for root in (PROPOSAL_ROOT,CANONICAL_ROOT):
    if str(root) not in sys.path: sys.path.insert(0,str(root))
from config.settings import DATABASE_PATH

EXPECTED_EXPIRIES={"2026-08-25":7,"2026-09-01":14,"2026-09-08":9}

def load(path):
    p=json.loads(Path(path).read_text(encoding="utf-8"))
    rows=list(p.get("fyers_found",[]))
    if len(rows)!=30: raise RuntimeError(f"Expected 30 audit contracts, got {len(rows)}")
    return rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--json",type=Path,default=Path.home()/"Desktop"/"missing_expiry_contracts.json")
    ap.add_argument("--report",type=Path,default=Path.home()/"Desktop"/"missing_expiry_candle_coverage.json")
    a=ap.parse_args()
    records=load(a.json)
    conn=sqlite3.connect(DATABASE_PATH)
    conn.row_factory=sqlite3.Row
    results=[]; failures=[]
    for x in sorted(records,key=lambda z:(z["expiry"],int(z["strike"]),z["option_type"])):
        sym=x["fyers_symbol"]
        inst=conn.execute("""SELECT id,symbol,expiry_date,strike,option_type FROM instruments
                             WHERE broker='FYERS' AND symbol=?""",(sym,)).fetchone()
        if not inst:
            results.append({**x,"status":"MISSING_INSTRUMENT","candle_count":0})
            failures.append(sym); continue
        rows=conn.execute("""SELECT timestamp FROM candles WHERE instrument_id=? ORDER BY timestamp""",(inst["id"],)).fetchall()
        ts=[r["timestamp"] for r in rows]
        first=ts[0] if ts else None; last=ts[-1] if ts else None
        dates=sorted(set(str(t)[:10] for t in ts))
        expected_start=x["first_event_date"]; expected_end=x["expiry"]
        missing_dates=[]
        # Only assess dates between first_event and expiry that have an underlying market day
        # by using dates actually represented by the NIFTY 1m table.
        udates=[r[0] for r in conn.execute("""SELECT DISTINCT substr(timestamp,1,10) FROM candles c
                     JOIN instruments i ON i.id=c.instrument_id
                     WHERE i.broker='FYERS' AND i.symbol LIKE 'NSE:NIFTY%' AND i.instrument_type NOT IN (14)
                     AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY 1""",(expected_start,expected_end))]
        for d in udates:
            if d not in dates: missing_dates.append(d)
        results.append({**x,"status":"OK" if ts else "NO_CANDLES","candle_count":len(ts),
                        "first_candle":first,"last_candle":last,"trading_dates":len(dates),
                        "missing_underlying_dates":missing_dates})
        if not ts: failures.append(sym)
    conn.close()
    report={"contracts":results,"failure_count":len(failures),"failures":failures}
    a.report.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    print("="*100); print("KUNAL QUANT — REPAIRED EXPIRY CANDLE COVERAGE AUDIT"); print("="*100)
    print(f"Contracts examined : {len(results)}")
    print(f"Total candles      : {sum(int(r['candle_count']) for r in results):,}")
    print(f"Contracts with candles : {sum(r['status']=='OK' for r in results)}")
    print(f"Failures           : {len(failures)}")
    print()
    for e in sorted(EXPECTED_EXPIRIES):
        subset=[r for r in results if r['expiry']==e]
        print(f"{e} | contracts={len(subset)} | candles={sum(int(r['candle_count']) for r in subset):,} | failures={sum(r['status']!='OK' for r in subset)}")
    print()
    for r in results:
        print(f"{r['fyers_symbol']} | {r['candle_count']:>5} | {r.get('first_candle')} -> {r.get('last_candle')} | {r['status']}")
    print(f"\nJSON report written to: {a.report}")
    print("NO DATABASE CHANGES WERE MADE.")
    raise SystemExit(1 if failures else 0)
if __name__=="__main__": main()
