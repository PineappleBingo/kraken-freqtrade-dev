import json
from pathlib import Path

import pytest

from companion import config_io


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    (tmp_path / config_io.CONFIG_FILE).write_text(json.dumps({
        "dry_run": True,
        "stake_currency": "USD",
        "stoploss": -0.99,
    }))
    (tmp_path / config_io.RISK_FILE).write_text(json.dumps({
        "max_open_trades": 3,
        "stoploss": -0.08,
        "available_capital": 300,
        "companion": {"capital_management": {
            "enabled": True,
            "profit_target_usd": 10000,
            "set_aside_usd": 9000,
            "restart_capital_usd": 1000,
        }},
    }))
    return tmp_path


def test_merged_config_risk_file_wins(config_dir):
    cfg = config_io.merged_config(config_dir)
    assert cfg["stoploss"] == -0.08
    assert cfg["stake_currency"] == "USD"
    assert cfg["companion"]["capital_management"]["enabled"] is True


@pytest.mark.parametrize("key,raw,expected", [
    ("stoploss", "-0.05", -0.05),
    ("max_open_trades", "5", 5),
    ("trailing_stop", "on", True),
    ("trailing_stop", "off", False),
    ("cm_enabled", "ON", True),
])
def test_validate_and_cast_ok(key, raw, expected):
    assert config_io.validate_and_cast(config_io.FIELDS[key], raw) == expected


@pytest.mark.parametrize("key,raw", [
    ("stoploss", "0.05"),        # positive: above max -0.01
    ("stoploss", "-0.9"),        # below min
    ("stoploss", "abc"),
    ("max_open_trades", "0"),
    ("max_open_trades", "99"),
    ("max_open_trades", "2.5"),
    ("trailing_stop", "maybe"),
])
def test_validate_and_cast_rejects(key, raw):
    with pytest.raises(ValueError):
        config_io.validate_and_cast(config_io.FIELDS[key], raw)


def test_update_field_writes_and_returns_old(config_dir):
    spec = config_io.FIELDS["max_open_trades"]
    old, warnings = config_io.update_field(config_dir, spec, 2)
    assert old == 3
    assert warnings == []
    saved = json.loads((config_dir / config_io.RISK_FILE).read_text())
    assert saved["max_open_trades"] == 2


def test_cross_field_warning_on_bad_set_aside(config_dir):
    spec = config_io.FIELDS["cm_set_aside"]
    _, warnings = config_io.update_field(config_dir, spec, 20000.0)
    assert warnings, "set_aside above profit target must warn"


def test_all_field_paths_resolve(config_dir):
    """Every registry entry must point at a real key in the shipped configs."""
    repo_config = Path(__file__).resolve().parent.parent / "config"
    for spec in config_io.FIELDS.values():
        data = config_io.load_json(repo_config / spec.file)
        assert config_io.get_path(data, list(spec.path)) is not None, spec.key
