from __future__ import annotations

import tomllib
from pathlib import Path

from gui.settings_store import SETTINGS_SCHEMA, coerce_value, default_settings, load_settings, write_settings


def test_settings_store_writes_and_loads_full_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    values = default_settings()
    values.update(
        {
            "MODE": "PhD",
            "RUN_AI_RESEARCH": False,
            "PARALLEL_THREADS": 12,
            "SELF_SEARCH_KEYWORDS": ["alpha email", "beta contact"],
        }
    )

    write_settings(path, values)
    loaded = load_settings(path)

    assert loaded["MODE"] == "PhD"
    assert loaded["RUN_AI_RESEARCH"] is False
    assert loaded["PARALLEL_THREADS"] == 12
    assert loaded["SELF_SEARCH_KEYWORDS"] == ["alpha email", "beta contact"]
    assert tomllib.loads(path.read_text(encoding="utf-8"))["MODE"] == "PhD"


def test_settings_store_can_omit_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    values = default_settings()
    values["MODE"] = "Freelance_English"

    write_settings(path, values, omit_defaults=True)
    text = path.read_text(encoding="utf-8")

    assert 'MODE = "Freelance_English"' in text
    assert "RUN_AI_RESEARCH" not in text


def test_setting_coercion_matches_widget_value_types() -> None:
    specs = {spec.key: spec for spec in SETTINGS_SCHEMA}

    assert coerce_value(specs["SEND"], "true") is True
    assert coerce_value(specs["PARALLEL_THREADS"], "7.0") == 7
    assert coerce_value(specs["SELF_REQUEST_TIMEOUT"], "3.5") == 3.5
    assert coerce_value(specs["SELF_SEARCH_KEYWORDS"], "a\n\n b ") == ["a", "b"]

