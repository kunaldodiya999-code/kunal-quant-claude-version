"""KTMI Uni Lite: the owner's locked strategy indicator.

- ``KTMI_Uni_Lite_FINAL.pine``: the official TradingView source. LOCKED,
  guarded by a SHA-256 test. Never edit it.
- ``KTMI_Uni_Lite_Compact.pine``: the same indicator in a shorter layout.
- ``config.py`` / ``signals.py``: the Python mirror used by the paper engine.

See LOCKED.md.
"""

from indicators.ktmi_uni_lite.config import (
    UNI_LITE_CORE,
    UNI_LITE_DEFAULTS,
    UniLiteConfig,
    UniLiteModule,
    parse_trigger,
)
from indicators.ktmi_uni_lite.signals import UniLiteBar, calculate_uni_lite

__all__ = [
    "UNI_LITE_CORE",
    "UNI_LITE_DEFAULTS",
    "UniLiteBar",
    "UniLiteConfig",
    "UniLiteModule",
    "calculate_uni_lite",
    "parse_trigger",
]
