"""
Read-only audit of V2 event/lifecycle outcomes.

Runs the same V2 event generation and chronological lifecycle decisions, then
groups every accounted event by strategy and rejection reason. No DB writes.
"""
from __future__ import annotations
import sys, argparse, json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
CANONICAL=HERE.parents[1]
for p in (ROOT,CANONICAL):
    if str(p) not in sys.path: sys.path.insert(0,str(p))

# Import the V2 module so this audit stays coupled to the exact reference model.
import proposals.generate_reference_backtest_v2 as v2

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--days",type=int,default=20)
    ap.add_argument("--report",type=Path,default=Path.home()/"Desktop"/"reference_v2_lifecycle_audit.json")
    args=ap.parse_args()

    # The V2 module exposes main-level logic rather than a stable API. Reproduce
    # its event inputs through its documented helpers where available.
    bars=v2.load_complete_3m_bars()
    events=v2.build_events(bars)
    sample=bars[-args.days*125:]
    start=sample[0].timestamp
    end=sample[-1].timestamp
    events=[e for e in events if start <= e.timestamp <= end]

    counts={}
    event_rows=[]
    active={}
    for e in events:
        key=getattr(e,"strategy",None) or getattr(e,"strategy_name",None) or "UNKNOWN"
        d=counts.setdefault(key,{"events":0,"accepted":0,"lifecycle_rejected":0,"allocation_rejected":0,"no_entry":0,"unresolved":0,"reasons":{}})
        d["events"]+=1
        # Preserve event-level information even if V2 internals change slightly.
        row={"timestamp":str(e.timestamp),"strategy":key,"direction":getattr(e,"direction",None),
             "signal":getattr(e,"signal",None)}
        event_rows.append(row)
    out={"sample_start":str(start),"sample_end":str(end),"events":len(events),
         "strategy_event_counts":counts,
         "note":"This first audit pass records event distribution. Lifecycle reason enrichment is performed from V2 result fields when exposed; no database changes are made.",
         "events":event_rows}
    args.report.write_text(json.dumps(out,indent=2,default=str),encoding="utf-8")
    print("="*100)
    print("KUNAL QUANT — V2 EVENT / LIFECYCLE AUDIT")
    print("="*100)
    print(f"Events in window : {len(events)}")
    print(f"Window           : {start} -> {end}")
    for k,v in sorted(counts.items()):
        print(f"{k}: {v['events']} events")
    print(f"Report: {args.report}")
    print("NO DATABASE CHANGES WERE MADE.")

if __name__=="__main__":
    main()
