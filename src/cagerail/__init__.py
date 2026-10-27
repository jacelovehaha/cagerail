"""cagerail — the cage for trading bots and AI agents.

Position limits, loss brakes, cooldowns and kill switches that sit between
any strategy (human-written or LLM-driven) and the broker/exchange.
"""

from .config import GuardConfig
from .engine import Cage, Decision, Intent

__version__ = "0.1.0"
__all__ = ["GuardConfig", "Cage", "Decision", "Intent", "__version__"]
