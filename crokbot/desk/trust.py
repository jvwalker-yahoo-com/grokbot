"""Trust ladder — how the desk earns larger capital (article §6).

Stages gate the DESK's total exposure, not individual orders. You advance
paper -> small -> scale only after the desk proves itself on the current stage.
The risk engine still applies the per-order and per-position caps on top.
"""

STAGES = ("paper", "small", "scale")

# exposure multiplier applied to max_position_notional at each stage
CASH_MULTIPLIER = {
    "paper": 1.0,
    "small": 0.25,
    "scale": 1.0,
}

# advance criteria: min profitable periods / days before moving up
ADVANCE_RULES = {
    "paper": {"profitable_periods": 20, "min_trades": 50},
    "small": {"profitable_periods": 30, "min_trades": 100},
    "scale": None,
}


def stage_multiplier(stage: str) -> float:
    return CASH_MULTIPLIER.get(stage.lower(), 1.0)


def next_cap(max_position_notional: float, stage: str) -> float:
    """Effective max position notional for the current trust stage."""
    return max_position_notional * stage_multiplier(stage)