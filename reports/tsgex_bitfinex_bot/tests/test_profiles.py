import json

import pytest

from tsgex_bfx_bot.profiles import DEFAULT_PROFILE, Profile, find_profile, load_profiles


def test_load_profiles_missing_file_returns_default(tmp_path):
    profiles = load_profiles(str(tmp_path / "does_not_exist.json"))
    assert profiles == [DEFAULT_PROFILE]


def test_load_profiles_none_path_returns_default():
    assert load_profiles(None) == [DEFAULT_PROFILE]


def test_load_profiles_reads_multiple_sub_accounts(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"profiles": [
        {"name": "主帳戶", "state_path": "a.json", "api_key_env": "BFX_KEY_A", "api_secret_env": "BFX_SECRET_A"},
        {"name": "子帳戶B", "state_path": "b.json", "api_key_env": "BFX_KEY_B", "api_secret_env": "BFX_SECRET_B",
         "symbol": "fUSD", "order_visibility": "hidden"},
    ]}))
    profiles = load_profiles(str(path))
    assert [p.name for p in profiles] == ["主帳戶", "子帳戶B"]
    assert profiles[1].order_visibility == "hidden"


def test_has_credentials_true_only_when_both_env_vars_set(monkeypatch):
    p = Profile(name="x", api_key_env="TEST_BFX_KEY_X", api_secret_env="TEST_BFX_SECRET_X")
    monkeypatch.delenv("TEST_BFX_KEY_X", raising=False)
    monkeypatch.delenv("TEST_BFX_SECRET_X", raising=False)
    assert p.has_credentials() is False
    monkeypatch.setenv("TEST_BFX_KEY_X", "k")
    assert p.has_credentials() is False  # secret still missing
    monkeypatch.setenv("TEST_BFX_SECRET_X", "s")
    assert p.has_credentials() is True


def test_find_profile_by_name():
    profiles = [Profile(name="a"), Profile(name="b")]
    assert find_profile(profiles, "b").name == "b"


def test_find_profile_defaults_to_first_when_name_is_none():
    profiles = [Profile(name="a"), Profile(name="b")]
    assert find_profile(profiles, None).name == "a"


def test_find_profile_raises_on_unknown_name():
    profiles = [Profile(name="a")]
    with pytest.raises(KeyError):
        find_profile(profiles, "does-not-exist")
