# YT Research Catalog

| Idea | Classification | Proposed use | Assessment |
|---|---|---|---|
| Structural Leg Profiler | Indicator / exit | ATR-adaptive structural trailing | BEST trailing candidate |
| Smart Money Concepts | Indicator | BOS/CHoCH/OB/FVG context | Secondary exit/context |
| Anchored Volume Profile | Indicator | VAL/VAH reclaim | Exit confirmation |
| Order Block Strength | Indicator | Structural strength | Stop tightening/context |
| Sweep & Engulf | Strategy | Independent reversal strategy | Separate research |
| Session Range Sweep + CHoCH | Strategy | Session reversal | Separate research |
| AMD Power of Three | Indicator/strategy | Session regime | Separate research |
| Oscillator Matrix | Indicator | Momentum/money flow | Exit confirmation |
| CVD Absorption | Indicator | Absorption/divergence | Requires reliable delta |
| Liquidity Delta Profiler | Indicator | Liquidity reversal | Requires real delta |
| Session Volume MA | Indicator | Volume/session context | Filter candidate |
| Peak Activity Range | Indicator | Volume support/resistance | Context candidate |
| Cluster Volume Profile | Indicator | K-means volume profile | Regime/context |
| Gamma Exposure | Indicator | Dealer gamma/flip | Options regime/exit context |
| Volume Surprise | Indicator | Same-clock volume anomaly | Regime filter |
| Machine Learning MA | Indicator | GP MA/bands | Experimental |
| Log Regression Channel | Indicator | Long-term regime | Poor intraday trailing fit |
| RSI Divergence Optimizer | Strategy/indicator | Divergence + walk-forward | Overfit risk |
| Universal Signal Backtester | Research tool | Signal screening | NOT an options backtester |
| OL/OH Sweep | Strategy | Opening candle sweep | Independent strategy |

Critical caveats from the supplied research package: synthetic tests prove causality/determinism, not usefulness; OHLC-derived delta is weak evidence versus real bid/ask delta; and the generic signal backtester does not model option premiums, Greeks, lot sizes or broker costs.
