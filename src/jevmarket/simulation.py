"""The run loop. One good, one market, one brain per run.

Each period: the fundamental is drawn, traders arrive in random order, and each
gets one turn. A turn is: withdraw your resting orders, look, decide, quote.
Order size is fixed at one unit so aggressiveness is the only lever an arm has;
sizing is a second channel and it is deliberately shut off in v1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .agents import JevArgmax, JevSample, Observation, ZeroIntelligence
from .book import Side
from .decision import DEFAULT_WORDING, Action, Decision
from .exchange import Exchange, OrderRejected
from .fundamental import Fundamental, Signal
from .quoting import quote_price

ARMS = {
    "zi": ZeroIntelligence,
    "jev_argmax": JevArgmax,
    "jev_sample": JevSample,
}
JEV_ARMS = {"jev_argmax", "jev_sample"}


@dataclass
class RunConfig:
    n_traders: int = 50
    periods: int = 500
    seed: int = 0
    arm: str = "zi"
    initial_cash: int = 100_000
    initial_inventory: int = 50
    private_value_sd: float = 5.0
    order_size: int = 1
    # Periods of zero-intelligence flow before the treatment arm takes over, so
    # that an informative arm inherits a populated book rather than a void. See
    # the cold-start note in preregistration.md.
    burn_in_periods: int = 0
    # The wording treatment: "original" (asymmetry-inducing) vs "mirror"
    # (the control). Only meaningful for the Jev arms.
    wording: str = DEFAULT_WORDING
    fundamental: Fundamental = field(default_factory=Fundamental)
    signal: Signal = field(default_factory=Signal)
    # Required for the Jev arms. Share one client (and one cache) across arms
    # and the second arm costs nothing.
    jev_client: object | None = None


@dataclass(frozen=True)
class DecisionRecord:
    """One brain-call, with everything the calibration analysis needs."""

    period: int
    trader_id: str
    arm: str
    decision: Decision
    fundamental: float
    signal: float
    private_value: float
    quoted_price: int | None
    filled_quantity: int
    rejected: bool


@dataclass
class RunResult:
    config: RunConfig
    exchange: Exchange
    fundamental_path: list[float]
    trade_prices: list
    mid_prices: list
    decisions: list[DecisionRecord]
    rejections: int

    @property
    def jump_times(self) -> list[int]:
        return list(self.config.fundamental.jump_times)


def run(config: RunConfig) -> RunResult:
    if config.arm not in ARMS:
        raise ValueError("unknown arm: " + repr(config.arm))
    if config.arm in JEV_ARMS and config.jev_client is None:
        raise ValueError(
            f"arm {config.arm!r} needs a jev_client; refusing to start a run that "
            f"would fail partway through"
        )

    trader_ids = ["t%03d" % i for i in range(config.n_traders)]
    brain_cls = ARMS[config.arm]
    brains = {}
    for i, tid in enumerate(trader_ids):
        seed = config.seed * 100_003 + i
        if config.arm in JEV_ARMS:
            brains[tid] = brain_cls(
                trader_id=tid, client=config.jev_client, seed=seed,
                wording=config.wording,
            )
        else:
            brains[tid] = brain_cls(trader_id=tid, seed=seed)
    burn_in_brains = {
        tid: ZeroIntelligence(trader_id=tid, seed=config.seed * 100_003 + i)
        for i, tid in enumerate(trader_ids)
    }
    exchange = Exchange.from_endowments(
        trader_ids, cash=config.initial_cash, inventory=config.initial_inventory
    )
    path = config.fundamental.path(config.periods)

    trade_prices: list = []
    mid_prices: list = []
    decisions: list[DecisionRecord] = []
    rejections = 0

    for period in range(config.periods):
        arrival_rng = np.random.default_rng([config.seed, period, 999])
        arrival = list(trader_ids)
        arrival_rng.shuffle(arrival)
        traded_before = exchange.trade_count
        signal = config.signal.observe(path, period)

        for index, trader_id in enumerate(arrival):
            exchange.cancel_all(trader_id)

            pv_rng = np.random.default_rng([config.seed, period, index])
            private_value = signal + float(pv_rng.normal(0.0, config.private_value_sd))

            account = exchange.accounts[trader_id]
            observation = Observation(
                period=period,
                signal=signal,
                private_value=private_value,
                best_bid=exchange.book.best_bid,
                best_ask=exchange.book.best_ask,
                last_price=exchange.last_price,
                cash=account.cash,
                inventory=account.inventory,
                available_cash=exchange.available_cash(trader_id),
                available_inventory=exchange.available_inventory(trader_id),
            )

            in_burn_in = period < config.burn_in_periods
            brain = burn_in_brains[trader_id] if in_burn_in else brains[trader_id]
            decision = brain.decide(observation)
            price = None
            filled = 0
            rejected = False

            if decision.action is not Action.PASS:
                side = Side.BUY if decision.action is Action.BUY else Side.SELL
                price = quote_price(
                    side,
                    private_value,
                    decision.aggressiveness,
                    observation.best_bid,
                    observation.best_ask,
                )
                if price is not None:
                    try:
                        result = exchange.submit(
                            trader_id, side, price=price, quantity=config.order_size
                        )
                        filled = sum(t.quantity for t in result.trades)
                    except OrderRejected:
                        rejections += 1
                        rejected = True

            decisions.append(
                DecisionRecord(
                    period=period,
                    trader_id=trader_id,
                    arm="burn_in" if in_burn_in else config.arm,
                    decision=decision,
                    fundamental=path[period],
                    signal=signal,
                    private_value=private_value,
                    quoted_price=price,
                    filled_quantity=filled,
                    rejected=rejected,
                )
            )

        period_trades = exchange.trades[traded_before:]
        if period_trades:
            volume = sum(t.quantity for t in period_trades)
            value = sum(t.price * t.quantity for t in period_trades)
            trade_prices.append(value / volume)
        else:
            trade_prices.append(None)

        bid = exchange.book.best_bid
        ask = exchange.book.best_ask
        mid_prices.append((bid + ask) / 2 if bid is not None and ask is not None else None)

    return RunResult(
        config=config,
        exchange=exchange,
        fundamental_path=path,
        trade_prices=trade_prices,
        mid_prices=mid_prices,
        decisions=decisions,
        rejections=rejections,
    )
