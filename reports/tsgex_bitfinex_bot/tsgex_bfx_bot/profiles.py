"""
Multi-sub-account profile config for webapp.py -- lets one dashboard switch
between several Bitfinex accounts (e.g. different sub-accounts or legal
entities), each with its own local ledger file and its own API key/secret.

Credentials are NEVER written into the profiles file itself -- only the
NAMES of the environment variables holding them, following this project's
existing convention (cli.py already requires BFX_API_KEY/BFX_API_SECRET as
env vars, never CLI args, so they don't end up in shell history or process
listings). A profiles.json committed to source control (or shared) therefore
never leaks a secret.
"""
import json
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Profile:
    name: str
    state_path: str = "bfx_bot_state.json"
    api_key_env: str = "BFX_API_KEY"
    api_secret_env: str = "BFX_API_SECRET"
    symbol: str = "fUSD"
    order_visibility: str = "standard"  # "standard" | "hidden" -- which platform fee applies to this profile's positions

    def has_credentials(self) -> bool:
        return bool(os.environ.get(self.api_key_env) and os.environ.get(self.api_secret_env))


DEFAULT_PROFILE = Profile(name="default")


def load_profiles(path: Optional[str]) -> List[Profile]:
    """Loads {"profiles": [{"name": ..., "state_path": ..., "api_key_env": ...,
    "api_secret_env": ..., "symbol": ...}, ...]} from `path`. Falls back to a
    single DEFAULT_PROFILE (matching cli.py's own defaults) if `path` is None
    or the file doesn't exist, so the dashboard works out of the box for a
    single-account setup with zero config."""
    if not path or not os.path.exists(path):
        return [DEFAULT_PROFILE]
    with open(path) as f:
        raw = json.load(f)
    profiles = [Profile(**p) for p in raw.get("profiles", [])]
    return profiles or [DEFAULT_PROFILE]


def find_profile(profiles: List[Profile], name: Optional[str]) -> Profile:
    if not name:
        return profiles[0]
    for p in profiles:
        if p.name == name:
            return p
    raise KeyError(f"Unknown profile '{name}'. Known profiles: {[p.name for p in profiles]}")
