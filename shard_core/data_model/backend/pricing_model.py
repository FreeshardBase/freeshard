# DO NOT MODIFY - copied from freeshard-controller

from pydantic import BaseModel

from .shard_model import VmSize


class VmSizeNetPrice(BaseModel):
    """Net monthly price of one VM size, in integer cents, before disk and VAT."""

    vm_size: VmSize
    net_price_cents: int


class PricingComponents(BaseModel):
    """The coefficients of the price formula, so a client can compute locally.

    A client that computes rather than asking per interaction MUST reproduce the
    controller's arithmetic exactly, or the price it displays will disagree with the
    price PayPal charges. Two things are load-bearing:

    Grouping. The reference expression, in floating point, is

        net_eur   = net_price_cents / 100 + disk_gb * (disk_net_price_cents_per_gb / 100)
        gross_eur = net_eur * (1 + vat_rate)

    Convert each component to euro *before* combining. The tempting cents-first form
    `(net_price_cents + disk_gb * disk_net_price_cents_per_gb) / 100` is not the same
    double and disagrees by 1 ct at some disk sizes.

    Rounding. Gross euro becomes cents half-up, `int(gross_eur * 100 + 0.5)` —
    JavaScript's `Math.round(gross_eur * 100)`. Do not use a banker's-rounding
    primitive (Python's own `round()`, `toFixed` in some engines): it diverges by 1 ct
    on every half-cent result, of which S at 250 GB is one (3749, not 3748).

    Every amount here is a **net** price with our margin already included; `vat_rate` is
    the only factor left to apply. `currency` is the unit for every `*_cents` field here
    and in `ShardPricesResponse`.
    """

    currency: str
    net_prices: list[VmSizeNetPrice]
    disk_net_price_cents_per_gb: int
    vat_rate: float


class VmSizePrice(BaseModel):
    """One VM size priced for a specific shard: its net price, and its gross monthly total."""

    vm_size: VmSize
    net_price_cents: int
    price_cents: int


class ShardPricesResponse(BaseModel):
    """Every VM size priced for the calling shard, plus the formula behind the figures.

    `prices` is the server's own answer at the shard's current `volume_size_gb`;
    `components` is what a client needs to compute any other disk size itself. Both are
    derived from the same constants in the same request, so a client can and should
    recompute `price_cents` from `components` and assert the two agree — that check is
    the cheapest available guard against the formula drifting between the controller,
    the landing page and the shard UI.

    See `PricingComponents` for the grouping and rounding a local computation must match.
    """

    vm_size: VmSize
    volume_size_gb: int
    components: PricingComponents
    prices: list[VmSizePrice]
