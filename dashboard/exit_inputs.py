"""The exit inputs every strategy form uses (owner rule 25 Oct 2026): Reward 1 : [box], TSL method.

An EMPTY reward box = no fixed target: the trailing stop (TSL) takes the trade out when a candle
closes beyond it. A number (1.5, 2, 2.5, 3 or any other) = exit the whole trade at 1:number.
"""

from __future__ import annotations

from strategies.exit_plan import TSL_CHOICES, TSL_LABELS

REWARD_HELP = ("Type the reward for 1 of risk: 1.5, 2, 2.5, 3 or any other number. "
               "Leave EMPTY for no fixed target: the trailing stop (TSL) takes you out when a candle closes beyond it.")


def reward_box(container, value, *, key: str, label: str = "Reward  1 :"):
    """Number box that may stay empty (None)."""
    return container.number_input(label, min_value=0.1, max_value=50.0, value=None if value is None else float(value),
                                  step=0.5, format="%.2f", placeholder="empty = TSL exit", key=key, help=REWARD_HELP)


def tsl_select(container, value: str, *, key: str, label: str = "TSL method", choices=TSL_CHOICES):
    choices = list(choices)
    return container.selectbox(label, choices, index=choices.index(value) if value in choices else 0,
                               format_func=TSL_LABELS.get, key=key)


__all__ = ["REWARD_HELP", "reward_box", "tsl_select"]
