# KTMI Uni Lite: LOCKED

Saved 2026-10-24 from the owner's TradingView source (pasted in chat).

| File | What it is | Rule |
|---|---|---|
| `KTMI_Uni_Lite_FINAL.pine` | Official source. Source of truth. | **Never edit.** `tests/test_ktmi_uni_lite.py` checks its SHA-256 (`47fcdf24...`). |
| `KTMI_Uni_Lite_Compact.pine` | Same indicator, 139 lines instead of 866. | Same 32 inputs (names, order, defaults), plots, fills, arrows and alerts. A test compares them with the original. |
| `KTMI_Uni_Lite_FYERS_SmartScript.pine` | Compact copy for FYERS Smart Script (27 Oct 2026): no `switch`, triggers = the owner's chart (Long 0.5, Short 0.5, Momentum off), 2 extra alerts. | A test keeps its maths equal to the Compact. |
| `KTMI_Uni_Lite_FYERS_Arrows.pine` | Backup for FYERS: only the BUY CALL / BUY PUT arrows, on the price candles (overlay). | A test keeps its maths equal to the Compact. |
| `config.py`, `signals.py` | Python mirror used by the paper engine. | Tested against a line-by-line transcription of the Pine logic. |

## What the indicator does

Three lines, each `TRIX` (percent change of a triple EMA) x 100, with an EMA
"signal" line:

| Line | Source | Speed / Signal | Note |
|---|---|---|---|
| Momentum | Close | 5 / 9 | |
| Long Momentum | **High** | 5 / 9 | |
| Short Momentum | **Low** | 5 / 9 | flipped negative, so a falling market makes it rise |

An arrow fires when ALL are true on a closed candle, e.g. Long Momentum Buy:
Long Speed crosses above the trigger (was at or below, now above), Long Speed
is above its Signal line, and Long Speed is above 0. An empty trigger box
switches that arrow off.

## The owner's current trading rule (profile `UNI_LITE_CORE`)

- Long Speed crosses above **+0.5** -> **BUY CALL (CE)**
- Short Speed crosses above **+0.5** -> **BUY PUT (PE)**
- Every other arrow is silent (calculated, never traded).

This matches the TradingView screenshots of 2026-10-24: Momentum Buy/Sell
triggers empty, Long Buy 0.5, Short Buy 0.5.

Note: the Pine *defaults* have Momentum Buy 0.5 / Sell -0.5 filled in. The
owner's chart has them empty. Profile `UNI_LITE_DEFAULTS` = Pine defaults.

## Changing it

Changing the formula or `KTMI_Uni_Lite_FINAL.pine` needs the owner's explicit
approval, then a new hash in `config.py` in the same commit. Changing a
*setting* (trigger value, source, lengths) needs no code change: it is a
`UniLiteConfig` value.

## Checking the compact version yourself

TradingView: Pine Editor -> paste `KTMI_Uni_Lite_Compact.pine` -> Save as a
new name -> add it to the chart next to the original. The lines and arrows
must sit exactly on top of each other.
