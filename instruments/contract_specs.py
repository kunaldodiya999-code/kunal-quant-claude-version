from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class ContractSpec:
    """
    Historical contract specification.

    A specification can be matched against an expiry date.
    """

    underlying: str
    effective_from: date
    effective_to: Optional[date]
    lot_size: int
    tick_size: float
    source: str


class ContractSpecRegistry:
    """
    Kunal Quant - Historical Contract Specification Registry.

    Purpose:
        Provide centralized historical contract specifications
        such as lot size and tick size.

    Important:
        This registry is intentionally separate from the broker
        instrument master because expired FYERS contract records
        may not provide complete contract specifications.

    The registry will grow as we validate historical contract
    specifications for additional instruments and periods.
    """

    # =========================================================
    # VERIFIED SPECIFICATIONS
    # =========================================================

    # NIFTY contracts expiring in the 2024-11-28 sample
    # were using lot size 25.
    #
    # This entry is deliberately scoped to the tested period.
    # We will add additional historical ranges after validation.
    VERIFIED_SPECS = (
        ContractSpec(
            underlying="NIFTY",
            effective_from=date(2024, 1, 1),
            effective_to=date(2024, 11, 28),
            lot_size=25,
            tick_size=0.05,
            source="KUNAL_QUANT_VERIFIED_2024_SAMPLE",
        ),
    )

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def normalize_underlying(
        underlying: str,
    ) -> str:
        """
        Normalize common FYERS-style underlying names.
        """

        value = (
            str(underlying)
            .strip()
            .upper()
        )

        mappings = {
            "NIFTY50": "NIFTY",
            "NIFTY50-INDEX": "NIFTY",
            "NSE:NIFTY50-INDEX": "NIFTY",
            "BANKNIFTY": "BANKNIFTY",
            "NIFTYBANK": "BANKNIFTY",
            "NIFTYBANK-INDEX": "BANKNIFTY",
            "NSE:NIFTYBANK-INDEX": "BANKNIFTY",
            "FINNIFTY": "FINNIFTY",
            "NIFTYFIN": "FINNIFTY",
            "MIDCPNIFTY": "MIDCPNIFTY",
            "SENSEX": "SENSEX",
            "BANKEX": "BANKEX",
        }

        return mappings.get(
            value,
            value,
        )

    # =========================================================
    # RESOLUTION
    # =========================================================

    def resolve(
        self,
        underlying: str,
        expiry_date: str | date,
    ) -> Optional[ContractSpec]:
        """
        Resolve the historical contract specification.

        Returns:
            ContractSpec if a matching specification exists.
            None otherwise.
        """

        normalized_underlying = (
            self.normalize_underlying(
                underlying
            )
        )

        expiry = self._parse_date(
            expiry_date
        )

        matches = []

        for spec in self.VERIFIED_SPECS:

            if (
                self.normalize_underlying(
                    spec.underlying
                )
                != normalized_underlying
            ):
                continue

            if expiry < spec.effective_from:
                continue

            if (
                spec.effective_to is not None
                and expiry > spec.effective_to
            ):
                continue

            matches.append(spec)

        if not matches:
            return None

        # Most specific / latest starting specification wins.
        matches.sort(
            key=lambda item: item.effective_from,
            reverse=True,
        )

        return matches[0]

    # =========================================================
    # LOT SIZE
    # =========================================================

    def get_lot_size(
        self,
        underlying: str,
        expiry_date: str | date,
    ) -> Optional[int]:
        """
        Return the historical lot size.
        """

        spec = self.resolve(
            underlying=underlying,
            expiry_date=expiry_date,
        )

        if spec is None:
            return None

        return spec.lot_size

    # =========================================================
    # TICK SIZE
    # =========================================================

    def get_tick_size(
        self,
        underlying: str,
        expiry_date: str | date,
    ) -> Optional[float]:
        """
        Return the historical tick size.
        """

        spec = self.resolve(
            underlying=underlying,
            expiry_date=expiry_date,
        )

        if spec is None:
            return None

        return spec.tick_size

    # =========================================================
    # GENERIC SPEC ACCESS
    # =========================================================

    def get_spec(
        self,
        underlying: str,
        expiry_date: str | date,
    ) -> Optional[dict]:
        """
        Return the resolved specification as a dictionary.
        """

        spec = self.resolve(
            underlying=underlying,
            expiry_date=expiry_date,
        )

        if spec is None:
            return None

        return {
            "underlying": spec.underlying,
            "effective_from": (
                spec.effective_from.isoformat()
            ),
            "effective_to": (
                spec.effective_to.isoformat()
                if spec.effective_to is not None
                else None
            ),
            "lot_size": spec.lot_size,
            "tick_size": spec.tick_size,
            "source": spec.source,
        }

    # =========================================================
    # DATE PARSER
    # =========================================================

    @staticmethod
    def _parse_date(
        value: str | date,
    ) -> date:
        """
        Convert YYYY-MM-DD string to date.
        """

        if isinstance(value, date):
            return value

        return date.fromisoformat(
            str(value).strip()
        )


# =============================================================
# SIMPLE MANUAL TEST
# =============================================================

def main() -> None:

    registry = ContractSpecRegistry()

    expiry = "2024-11-28"

    print()
    print("=" * 70)
    print("KUNAL QUANT - CONTRACT SPEC REGISTRY")
    print("=" * 70)

    print()
    print("Underlying :", "NIFTY")
    print("Expiry     :", expiry)

    spec = registry.get_spec(
        underlying="NIFTY",
        expiry_date=expiry,
    )

    if spec is None:

        print()
        print("No specification found.")

    else:

        print()
        print("Resolved specification:")
        print(
            f"  Lot size  : {spec['lot_size']}"
        )
        print(
            f"  Tick size : {spec['tick_size']}"
        )
        print(
            f"  Source    : {spec['source']}"
        )

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()