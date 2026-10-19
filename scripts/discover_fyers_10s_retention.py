from __future__ import annotations
import argparse, json, sqlite3
from datetime import date, timedelta
from pathlib import Path

from api.fyers_client import FyersClient
from config.hft_data import HFT_RESOLUTION
from config.settings import DATABASE_PATH

INDEX_SYMBOL = "NSE:NIFTY50-INDEX"

def db_rows():
    with sqlite3.connect(DATABASE_PATH) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("""
            SELECT symbol, instrument_type, underlying, expiry_date, strike, option_type
            FROM instruments
            WHERE broker='FYERS' AND underlying='NIFTY'
            ORDER BY expiry_date, symbol
        """)]

def representative(rows, instrument_type, year):
    candidates = []
    for r in rows:
        t = str(r["instrument_type"] or "").upper()
        if instrument_type == "FUT" and t not in {"FUT","FUTURE","FUTURES"}: continue
        if instrument_type == "OPT" and t not in {"OPT","OPTION","OPTIONS"}: continue
        if not r["expiry_date"]: continue
        try: y = int(str(r["expiry_date"])[:4])
        except ValueError: continue
        if y == year: candidates.append(r)
    if not candidates: return None
    if instrument_type == "OPT":
        candidates.sort(key=lambda r: (abs(float(r["strike"] or 0)-25000), r["expiry_date"]))
    return candidates[0]

def probe(client, symbol, mode, day):
    try:
        if mode == "standard":
            r = client.history(symbol=symbol, resolution=HFT_RESOLUTION,
                               range_from=day, range_to=day,
                               date_format="1", cont_flag="0")
        else:
            r = client.expired_history(symbol=symbol, resolution=HFT_RESOLUTION,
                                       range_from=day, range_to=day,
                                       include_oi="1", include_greeks="1",
                                       date_format="1")
        candles = r.get("candles") or []
        return {"status":"ok", "candles":len(candles),
                "first_timestamp":candles[0][0] if candles else None,
                "last_timestamp":candles[-1][0] if candles else None}
    except Exception as e:
        return {"status":"error", "error":str(e)[:1000]}

def main():
    p=argparse.ArgumentParser(description="Empirically discover FYERS 10s historical coverage.")
    p.add_argument("--years", default="2021,2022,2023,2024,2025,2026")
    p.add_argument("--json", default="data/reports/hft_10s_retention.json")
    p.add_argument("--option-symbol")
    p.add_argument("--futures-symbol")
    args=p.parse_args()

    rows=db_rows()
    client=FyersClient()
    today=date.today()
    years=[int(x) for x in args.years.split(",") if x.strip()]
    results=[]

    # Index coverage: probe one weekday near each calendar year's start/end.
    for y in years:
        for d in (date(y,1,15), date(y,7,15), date(y,12,15)):
            if d > today: continue
            if d.weekday() >= 5: d -= timedelta(days=d.weekday()-4)
            results.append({"dataset":"NIFTY_INDEX","symbol":INDEX_SYMBOL,"mode":"standard",
                            "date":d.isoformat(),"probe":probe(client,INDEX_SYMBOL,"standard",d.isoformat())})

    # F&O coverage: use real symbols already present in the local registry.
    for y in years:
        fut = {"symbol":args.futures_symbol} if args.futures_symbol else representative(rows,"FUT",y)
        opt = {"symbol":args.option_symbol} if args.option_symbol else representative(rows,"OPT",y)
        for label, item in (("NIFTY_FUTURES",fut),("NIFTY_OPTION",opt)):
            if not item or not item.get("symbol"): continue
            expiry = item.get("expiry_date")
            if expiry:
                d=date.fromisoformat(str(expiry)[:10]) - timedelta(days=3)
                while d.weekday() >= 5: d -= timedelta(days=1)
            else:
                d=date(y,12,15)
            if d > today: d=today-timedelta(days=1)
            results.append({"dataset":label,"symbol":item["symbol"],"mode":"expired",
                            "expiry_date":expiry,"date":d.isoformat(),
                            "probe":probe(client,item["symbol"],"expired",d.isoformat())})

    out={"resolution":HFT_RESOLUTION,"generated_at":date.today().isoformat(),
         "note":"Empirical probes only; FYERS does not publish a separate 10s retention guarantee for every expired F&O contract.",
         "results":results}
    path=Path(args.json); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps(out,indent=2)); print(f"JSON written to: {path}")

if __name__=="__main__": main()
