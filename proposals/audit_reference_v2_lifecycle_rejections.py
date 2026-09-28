"""
Read-only V2 lifecycle accounting audit.
Uses the exact V2 reference runner; no database or canonical-code changes.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
CANONICAL=HERE.parents[1]
for p in (ROOT,CANONICAL):
    if str(p) not in sys.path: sys.path.insert(0,str(p))
import proposals.generate_reference_backtest_v2 as v2

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--days",type=int,default=20)
    ap.add_argument("--report",type=Path,default=Path.home()/"Desktop"/"reference_v2_lifecycle_audit.json")
    args=ap.parse_args()
    bars=v2.load_all_complete_3m_bars()
    sample=v2.select_last_days(bars,args.days)
    cfg=v2.build_trigger_config(argparse.Namespace(
        disable_speed_sources=False, disable_momentum=False,
        long_speed_ce_trigger=0.50, short_speed_pe_trigger=0.50,
        momentum_ce_trigger=0.50, momentum_pe_trigger=-0.50))
    result=v2.run_reference(all_bars=bars,sample_bars=sample,trigger_config=cfg)
    report={
        "sample_start":str(sample[0].timestamp),
        "sample_end":str(sample[-1].timestamp),
        "selected_events":len(result["selected_events"]),
        "counts":result["counts"],
        "note":"Uses exact V2 reference runner. Detailed rejection-reason enrichment is not exposed by the current V2 runner yet."
    }
    args.report.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    print("="*100)
    print("KUNAL QUANT — V2 LIFECYCLE ACCOUNTING AUDIT")
    print("="*100)
    print(f"Events in window : {report['selected_events']}")
    for k,v in sorted(result["counts"].items()):
        print(f"{k:24s}: {v}")
    print(f"Report: {args.report}")
    print("NO DATABASE CHANGES WERE MADE.")

if __name__=="__main__":
    main()
