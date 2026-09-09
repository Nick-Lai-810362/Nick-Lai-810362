import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsgex_bfx_bot.config import StrategyConfig  # noqa: E402
from tsgex_bfx_bot.ledger import BotState  # noqa: E402


@pytest.fixture
def now():
    return datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    return StrategyConfig()


@pytest.fixture
def state():
    return BotState()


@pytest.fixture
def funded_state():
    s = BotState()
    from tsgex_bfx_bot.ledger import contribute_principal
    contribute_principal(s, 100_000.0)
    return s
