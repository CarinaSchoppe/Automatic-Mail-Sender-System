"""Tests and helpers for tests/test_gui_settings_store.py."""

from __future__ import annotations

import tomllib
from pathlib import Path

from gui.settings_store import ENV_SCHEMA, SETTINGS_SCHEMA
from gui.settings_store import coerce_value, default_env, default_settings, load_env, load_settings, write_env, write_settings


def test_settings_store_writes_and_loads_full_settings(tmp_path: Path) -> None:
    """Checks behavior for settings store writes and loads full settings."""
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
    """Checks behavior for settings store can omit defaults."""
    path = tmp_path / "settings.toml"
    values = default_settings()
    values["MODE"] = "Freelance_English"

    write_settings(path, values, omit_defaults=True)
    text = path.read_text(encoding="utf-8")

    assert 'MODE = "Freelance_English"' in text
    assert "RUN_AI_RESEARCH" not in text


def test_setting_coercion_matches_widget_value_types() -> None:
    """Checks behavior for setting coercion matches widget value types."""
    specs = {spec.key: spec for spec in SETTINGS_SCHEMA}

    assert specs["SMTP_PORT"].slider is False
    assert specs["SPAM_SAFE_MODE"].default is False
    assert specs["REQUIRE_EMAIL_SMTP_PASS"].default is True
    assert specs["REJECT_CATCH_ALL"].default is True
    assert coerce_value(specs["SEND"], "true") is True
    assert coerce_value(specs["PARALLEL_THREADS"], "7.0") == 7
    assert coerce_value(specs["SELF_REQUEST_TIMEOUT"], "3.5") == 3.5
    assert coerce_value(specs["SELF_SEARCH_KEYWORDS"], "a\n\n b ") == ["a", "b"]


def test_research_model_replaces_provider_specific_gui_settings(tmp_path: Path) -> None:
    """Checks that the GUI schema exposes one research model setting."""
    path = tmp_path / "settings.toml"
    values = default_settings()
    values["RESEARCH_MODEL"] = "ollama:llama3.1:8b"

    write_settings(path, values)
    text = path.read_text(encoding="utf-8")
    schema_keys = {spec.key for spec in SETTINGS_SCHEMA}

    assert "RESEARCH_MODEL" in schema_keys
    assert "RESEARCH_AI_PROVIDER" not in schema_keys
    assert "GEMINI_MODEL" not in schema_keys
    assert "OPENAI_MODEL" not in schema_keys
    assert "OLLAMA_MODEL" not in schema_keys
    assert 'RESEARCH_MODEL = "ollama:llama3.1:8b"' in text
    assert "RESEARCH_AI_PROVIDER" not in text


def test_env_store_writes_and_loads_all_env_values(tmp_path: Path) -> None:
    """Checks behavior for env store writes and loads all env values."""
    path = tmp_path / ".env"
    values = default_env()
    values.update({"SMTP_USERNAME": "user", "SMTP_PASSWORD": "secret", "GEMINI_API_KEY": "gem"})

    write_env(path, values)
    loaded = load_env(path)

    assert loaded["SMTP_USERNAME"] == "user"
    assert loaded["SMTP_PASSWORD"] == "secret"
    assert loaded["GEMINI_API_KEY"] == "gem"
    assert {spec.key for spec in ENV_SCHEMA}.issuperset(loaded.keys())
