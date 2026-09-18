"""The run loop. One good, one market, one brain per run.

Each period: the fundamental is drawn, traders arrive in random order, and each
gets one turn. A turn is: withdraw your resting orders, look, decide, quote.
Order size is fixed at one unit so aggressiveness is the only lever an arm has;
sizing is a second channel and it is deliberately shut off in v1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .agents import Observation, ZeroIntelligence
from .book import Side
from .decision import Action, Decision
from .exchange import Exchange, OrderRejected
from .fundamental import Fundamental, Signal
from .quoting import quote_price

ARMS = {"zi": ZeroIntelligence}


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
    fundamental: Fundamental = field(default_factory=Fundamental)
    signal: Signal = field(default_factory=Signal)


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

    trader_ids = ["t%03d" % i for i in range(config.n_traders)]
    brain_cls = ARMS[config.arm]
    brains = {
        tid: brain_cls(trader_id=tid, seed=config.seed * 100_003 + i)
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

            decision = brains[trader_id].decide(observation)
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
                    arm=config.arm,
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
