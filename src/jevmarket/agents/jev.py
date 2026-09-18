"""The two Jev arms. One API call serves both.

System One returns a full probability map over {buy, sell, pass}. `JevArgmax`
takes the choice Jev made; `JevSample` draws from that same map. Because both
read one response, running the pair over a seed costs one call, and the
argmax-vs-sample contrast (H5) is a within-call comparison with no
between-call noise to confound it.
"""

from __future__ import annotations

import numpy as np

from ..decision import DEFAULT_WORDING, Action, Decision
from .base import Observation


class JevArgmax:
    """Take the action Jev picked."""

    arm = "jev_argmax"

    def __init__(
        self, trader_id: str, client, seed: int = 0, wording: str = DEFAULT_WORDING
    ) -> None:
        self.trader_id = trader_id
        self.client = client
        self.seed = seed
        self.wording = wording

    def decide(self, observation: Observation) -> Decision:
        decision, _ = self.client.decide(observation, wording=self.wording)
        return decision


class JevSample:
    """Draw from the distribution Jev returned, rather than taking its mode."""

    arm = "jev_sample"

    def __init__(
        self, trader_id: str, client, seed: int = 0, wording: str = DEFAULT_WORDING
    ) -> None:
        self.trader_id = trader_id
        self.client = client
        self.seed = seed
        self.wording = wording

    def decide(self, observation: Observation) -> Decision:
        decision, _ = self.client.decide(observation, wording=self.wording)

        options = [action.value for action in Action]
        weights = np.array([decision.action_probabilities[o] for o in options])
        weights = weights / weights.sum()

        rng = np.random.default_rng([self.seed, observation.period, 7])
        sampled = options[int(rng.choice(len(options), p=weights))]

        # The distribution is carried through unchanged: confidence is still the
        # mass Jev put on the action actually taken, which is what ECE scores.
        return Decision.create(
            action=sampled,
            aggressiveness=decision.aggressiveness,
            already_priced=decision.already_priced,
            action_probabilities=decision.action_probabilities,
            model_confidence=decision.model_confidence,
        )
