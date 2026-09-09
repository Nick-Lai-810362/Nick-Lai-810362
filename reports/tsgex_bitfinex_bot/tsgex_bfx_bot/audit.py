"""
Structured, human-readable JSON-lines decision audit log. Fuly.ai is a
closed SaaS with no equivalent decision trail; this is what an institutional
treasury's internal audit/risk sign-off actually needs, independent of
realized return.
"""
import json
from datetime import datetime, timezone

from .config import StrategyConfig


def write_audit_log(cfg: StrategyConfig, record: dict) -> None:
    if not cfg.audit_log_path:
        return
    record = {"ts_utc": datetime.now(timezone.utc).isoformat(), **record}
    with open(cfg.audit_log_path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
