"""FYERS order calls, journaled. Field names follow the FYERS API v3 docs:
place_order / modify_order / cancel_order / orderbook(data={"id": ...}).
Status codes: 1 cancelled, 2 filled, 4 transit, 5 rejected, 6 pending, 7 expired.

``DryRunGateway`` has the same interface and never contacts the broker.
"""

from __future__ import annotations

import csv
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
FYERS_STATUS = {1: "CANCELLED", 2: "FILLED", 4: "TRANSIT", 5: "REJECTED", 6: "PENDING", 7: "EXPIRED"}
LOG_FIELDS = ("time", "mode", "action", "symbol", "side", "qty", "price", "order_id", "ok", "code", "message")


class OrderError(RuntimeError):
    """The broker refused or did not acknowledge a request."""


@dataclass(frozen=True)
class OrderState:
    order_id: str
    status: str
    filled_qty: int
    remaining_qty: int
    traded_price: float | None
    message: str = ""


class _Journal:
    def __init__(self, path: Path, mode: str) -> None:
        self.path, self.mode = Path(path), mode
        self._lock = threading.Lock()

    def write(self, **row: Any) -> None:
        row = {"time": datetime.now(IST).isoformat(timespec="seconds"), "mode": self.mode, **row}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.exists() or self.path.stat().st_size == 0
            with self.path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS, extrasaction="ignore")
                if new:
                    writer.writeheader()
                writer.writerow({k: row.get(k, "") for k in LOG_FIELDS})


def _tag(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch.isalnum())[:30]
    return cleaned or "KQ"


class FyersOrderGateway:
    mode = "LIVE"

    def __init__(self, model: Any, *, journal_path: Path, product_type: str = "INTRADAY",
                 min_interval: float = 0.15, sleep=time.sleep, clock=time.monotonic) -> None:
        self.model = model
        self.journal = _Journal(journal_path, self.mode)
        self.product_type = product_type
        self.min_interval, self._sleep, self._clock = min_interval, sleep, clock
        self._last_call = 0.0

    def _pace(self) -> None:   # stays far below FYERS' 10 orders/second
        wait = self.min_interval - (self._clock() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = self._clock()

    def _check(self, response: Any, action: str, **ctx) -> dict:
        ok = isinstance(response, dict) and response.get("s") == "ok"
        code = response.get("code") if isinstance(response, dict) else None
        message = response.get("message") if isinstance(response, dict) else str(response)
        self.journal.write(action=action, ok=ok, code=code, message=message, **ctx)
        if not ok:
            raise OrderError(f"{action} refused by FYERS (code {code}): {message}")
        return response

    def place_limit(self, symbol: str, side: str, qty: int, price: float, tag: str) -> str:
        self._pace()
        data = {
            "symbol": symbol, "qty": int(qty), "type": 1, "side": 1 if side == "BUY" else -1,
            "productType": self.product_type, "limitPrice": float(price), "stopPrice": 0,
            "validity": "DAY", "disclosedQty": 0, "offlineOrder": False, "orderTag": _tag(tag),
        }
        response = self._check(self.model.place_order(data=data), "PLACE",
                               symbol=symbol, side=side, qty=qty, price=price)
        if response.get("code") == 201 or not response.get("id"):
            # FYERS: 201 = request made but not acknowledged. Never re-send blindly.
            raise OrderError("Order not acknowledged by FYERS (code 201). Check the FYERS order book "
                             "before doing anything; nothing will be re-sent automatically.")
        return str(response["id"])

    def modify_price(self, order_id: str, price: float) -> None:
        self._pace()
        self._check(self.model.modify_order(data={"id": order_id, "type": 1, "limitPrice": float(price)}),
                    "MODIFY", order_id=order_id, price=price)

    def cancel(self, order_id: str) -> None:
        self._pace()
        self._check(self.model.cancel_order(data={"id": order_id}), "CANCEL", order_id=order_id)

    def state(self, order_id: str) -> OrderState:
        self._pace()
        response = self.model.orderbook(data={"id": order_id})
        if not (isinstance(response, dict) and response.get("s") == "ok" and response.get("orderBook")):
            raise OrderError(f"Could not read order {order_id} from FYERS: {response}")
        row = response["orderBook"][0]
        traded = row.get("tradedPrice")
        return OrderState(
            order_id=str(order_id),
            status=FYERS_STATUS.get(int(row.get("status", 0)), f"UNKNOWN_{row.get('status')}"),
            filled_qty=int(row.get("filledQty") or 0),
            remaining_qty=int(row.get("remainingQuantity") or 0),
            traded_price=float(traded) if traded not in (None, "", 0) else None,
            message=str(row.get("message") or ""),
        )


class DryRunGateway:
    """Same calls as FyersOrderGateway; journals 'WOULD SEND' and never contacts FYERS."""
    mode = "DRY_RUN"

    def __init__(self, *, journal_path: Path, **_ignored) -> None:
        self.journal = _Journal(journal_path, self.mode)
        self._count = 0
        self._orders: dict[str, tuple[int, float]] = {}

    def place_limit(self, symbol, side, qty, price, tag) -> str:
        self._count += 1
        order_id = f"DRYRUN-{self._count}"
        self._orders[order_id] = (int(qty), float(price))
        self.journal.write(action="WOULD_PLACE", symbol=symbol, side=side, qty=qty, price=price,
                           order_id=order_id, ok=True, message="dry run: not sent")
        return order_id

    def modify_price(self, order_id, price) -> None:
        qty, _ = self._orders[order_id]
        self._orders[order_id] = (qty, float(price))
        self.journal.write(action="WOULD_MODIFY", order_id=order_id, price=price, ok=True, message="dry run")

    def cancel(self, order_id) -> None:
        self.journal.write(action="WOULD_CANCEL", order_id=order_id, ok=True, message="dry run")

    def state(self, order_id) -> OrderState:
        # A dry-run order is treated as filled at its limit so the mirror can
        # show the whole would-be sequence (entry then exit). Not a real fill.
        qty, price = self._orders[order_id]
        return OrderState(order_id, "FILLED", qty, 0, price, "dry run (assumed fill)")


__all__ = ["DryRunGateway", "FYERS_STATUS", "FyersOrderGateway", "OrderError", "OrderState"]
