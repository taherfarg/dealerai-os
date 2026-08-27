"""Money as integer minor units. No float ever touches a price.

A price shown to a customer is a fact from the database; binary floating point
turns 66000.00 into 65999.99999999999 and a dealer into an angry phone call.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: Minor-unit exponent per currency. The Gulf is not all 2-decimal: KWD, BHD and
#: OMR are 3-decimal, and getting that wrong is a 1000x pricing error.
_EXPONENT: dict[str, int] = {
    "AED": 2,
    "SAR": 2,
    "QAR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "KWD": 3,
    "BHD": 3,
    "OMR": 3,
    "JPY": 0,
}

DEFAULT_EXPONENT = 2


def exponent(currency: str) -> int:
    return _EXPONENT.get(currency.upper(), DEFAULT_EXPONENT)


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        # bool is a subclass of int; Money(True, "AED") must not be legal.
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise TypeError(
                f"amount_minor must be int minor units, got {type(self.amount_minor).__name__}. "
                "Use Money.from_major() to convert from a decimal amount."
            )
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError(f"currency must be a 3-letter code, got {self.currency!r}")
        object.__setattr__(self, "currency", self.currency.upper())

    @classmethod
    def from_major(cls, amount: Decimal | str | int, currency: str) -> Money:
        """66000 AED -> Money(6600000, 'AED'). Accepts str/Decimal/int, never float."""
        if isinstance(amount, float):
            raise TypeError("refusing to build Money from a float; pass a str or Decimal")
        # scaleb, not `* 10**n`: it stays in Decimal the whole way and never
        # detours through a binary float.
        scaled = Decimal(amount).scaleb(exponent(currency))
        if scaled != scaled.to_integral_value():
            raise ValueError(f"{amount} has more precision than {currency} allows")
        return cls(int(scaled), currency)

    @property
    def major(self) -> Decimal:
        return Decimal(self.amount_minor).scaleb(-exponent(self.currency))

    def format(self, *, with_currency: bool = True) -> str:
        digits = exponent(self.currency)
        body = f"{self.major:,.{digits}f}"
        return f"{self.currency} {body}" if with_currency else body

    def __str__(self) -> str:
        return self.format()
