"""Transparent import/export tariff transformation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TariffSettings:
    """Variable Dutch retail tariff components in currency per kWh."""

    dutch_enabled: bool = True
    vat_percent: float = 21.0
    energy_tax_per_kwh: float = 0.09161
    supplier_buy_markup_per_kwh: float = 0.02
    supplier_sell_markdown_per_kwh: float = 0.0
    legacy_buy_adder_per_kwh: float = 0.0
    legacy_sell_adder_per_kwh: float = 0.0


@dataclass(frozen=True, slots=True)
class RetailPrice:
    """Import and export prices derived from one wholesale value."""

    wholesale: float
    buy: float
    sell: float


def retail_price(wholesale_price: float, settings: TariffSettings) -> RetailPrice:
    """Convert a Nord Pool wholesale price to consumer import/export prices.

    Dutch energy tax is charged on imported electricity only. VAT applies to
    the wholesale price, tax and supplier purchase markup. Export defaults to
    wholesale less a configurable supplier deduction; no import tax is credited
    to battery exports. Annual fixed charges and tax rebates are excluded because
    dispatch cannot affect them.
    """
    if not settings.dutch_enabled:
        return RetailPrice(
            wholesale=wholesale_price,
            buy=wholesale_price + settings.legacy_buy_adder_per_kwh,
            sell=wholesale_price - settings.legacy_sell_adder_per_kwh,
        )
    vat = 1 + min(max(settings.vat_percent, 0.0), 100.0) / 100
    buy = (
        wholesale_price
        + settings.energy_tax_per_kwh
        + settings.supplier_buy_markup_per_kwh
    ) * vat
    sell = wholesale_price - settings.supplier_sell_markdown_per_kwh
    return RetailPrice(wholesale=wholesale_price, buy=buy, sell=sell)
