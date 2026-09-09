"""
Governance guard: refuse to run live if the API key can withdraw/transfer.
Independently re-enforces Fuly.ai's own documented "Funding-only, never
Withdraw" setup instructions, and the TSGEX report's "最小授權架構" rule.
"""
import logging

from .client import BitfinexClient

log = logging.getLogger("tsgex_bot")


def assert_minimal_permissions(client: BitfinexClient) -> None:
    perms = client.get_permissions()
    perm_map = {row[0]: row for row in perms}
    withdraw_perm = perm_map.get("wallets") or perm_map.get("withdraw")
    if withdraw_perm and len(withdraw_perm) >= 4 and int(withdraw_perm[3]) == 1:
        raise RuntimeError(
            "REFUSING TO RUN: this API key has withdrawal/transfer permission. "
            "Both Fuly.ai's own setup guides and TSGEX governance policy require "
            "funding-only keys with withdrawal explicitly disabled. Create a new restricted key."
        )
    log.info("Permission check passed: key has no withdrawal/transfer scope.")
