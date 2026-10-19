# YT Strategies / Indicators — Experimental Research Pack

This folder is isolated research work derived from the uploaded YouTube videos and Claude-generated code supplied for KunalQuant.

**Status: EXPERIMENTAL.** Nothing here is wired into locked KTMI, Opening Breakout V2, Option Contract Resolver V2, or Option Trade Management V1.

- 17 uploaded MP4s were inventoried.
- 3 uploaded ZIP/code packs were inspected.
- The supplied research-filter self-test passed.
- The OL/OH Sweep supplied test suite passed 37/37.

## Main decision

The first trailing-stop candidate is **ATR-confirmed structural trailing**, based on the Structural Leg Profiler concept. It is causal, volatility-adaptive, produces an explicit stop price, and can be tested without changing the locked V2 entry logic.

See TRAILING_SL_RESEARCH.md and YT_RESEARCH_CATALOG.md.
