# Allocation rejection handling — proposal

## Observed behavior

The current real option runner reaches Option Trade Lifecycle V1 and can raise:

`ValueError: Allocation cannot purchase one complete lot`

The locked V1 config is:
- allocation = 15000
- lot_size = 65
- maximum executable premium for one lot = 230.769230...

In the 2,500-bar / 300-event sample, 284 option entries were accepted by the
entry bridge and 51 were unaffordable under that allocation.

## Proposed behavior

Do not change the allocation, lot size, stop, target, lifecycle, resolver,
KTMI, or strategy rules.

Instead, treat the specific allocation exception as a normal
non-executable/risk rejection:
- increment a dedicated `allocation_rejected_events` counter
- skip that event
- continue processing later events
- do not create a position
- do not create a trade P&L record
- preserve all existing behavior for every other exception

The runner's result object should expose the count with a default of zero
for compatibility.

## Guardrail

Catch only the exact lifecycle error message:

`Allocation cannot purchase one complete lot`

Do not catch all ValueError exceptions, because programming/data errors must
remain fatal.

## Why

A backtest should evaluate the complete signal stream. One non-executable
signal should not abort the entire run. The allocation constraint remains
enforced; the signal is simply skipped because the defined risk allocation
cannot buy one complete lot.

## Separate issue

The diagnostic shows repeated-looking unaffordable rows. The current output
does not prove they are duplicate events because the diagnostic may contain
different strategy IDs at the same timestamp/symbol. We should add a unique
event count before using the 51 figure for performance statistics.

This proposal has not been applied to canonical KunalQuant.
