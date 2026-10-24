"""Real broker orders (FYERS). OFF by default.

Nothing in this package sends an order unless ALL of these are true:
  1. the owner armed the live switch for today (scripts/live_switch.py), and
  2. the session was started with --live-orders.
Otherwise every order is a DRY RUN: written to the journal as "WOULD SEND".

Rules from the owner's spec: limit orders only, with a price buffer; never a
market order, not even as a fallback; a sent order is not a fill.
"""
