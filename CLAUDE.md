# Notes for Claude (read first, every session)

## The owner
- Kunal Quant owner, about 10% coding knowledge, on Windows + VS Code + PowerShell.
- Explain step by step, in plain words. One small step at a time.
- Always say WHICH folder a command runs in, with the full path.
- Never ask the owner to paste or re-share the KTMI code: it is in this repo.

## Folders on the owner's PC
- `C:\Users\USER\Desktop\Kunal\kunal-quant-claude-version`: the working copy. Use this one.
  It has its own `.venv`. Activate: `.\.venv\Scripts\Activate.ps1` (prompt must show `(.venv)`).
- `C:\Users\USER\Desktop\Kunal\KunalQuant`: the original repo. Read-only for Claude.
  It holds the real price database `data\database\kunal_quant.db`; this working copy has none
  (that is why 5 tests skip here).
- Tests: `python -m pytest tests -q --ignore=tests/expiry_isolation_test.py`

## LOCKED: KTMI Uni Lite (the strategy indicator)
- `indicators/ktmi_uni_lite/`; read `LOCKED.md` there.
- `KTMI_Uni_Lite_FINAL.pine` must never be edited (SHA-256 test).
- Current trading rule = profile `UNI_LITE_CORE`:
  Long Speed crosses above +0.5 -> BUY CE; Short Speed crosses above +0.5 -> BUY PE.
  Arrow = cross above trigger AND speed > signal AND speed > 0 (Pine `ta.crossover`).
  Everything else silent until the owner says otherwise.
- Bearish signal = BUY PUT (long premium). Never short-sell options.

## Other locked things
- `backtest/option_trade_lifecycle.py`: byte-for-byte unchanged.
- `indicators/ktmi/` (KTMI Universal engine): do not change calculations.
- No real orders. Paper mode only. Live trading needs an explicit owner approval gate.

## Where things are
- Full specification from the owner: `docs/KUNAL_QUANT_MASTER_SPEC.md`.
- Project handover and roadmap: `docs/KUNAL_QUANT_PROJECT_HANDOVER.md`.
- Change log of Claude's work: `docs/CLAUDE_CHANGELOG.md` (append, newest first).
- Paper engine: `paper_trading/` (session.py is the composition root).
