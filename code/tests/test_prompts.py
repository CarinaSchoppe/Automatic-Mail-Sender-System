"""Tests and helpers for tests/test_prompts.py."""

from mail_sender.prompts import load_prompts, save_prompts, DEFAULT_PROMPTS


def test_load_defaults(tmp_path):
    """Checks behavior for load defaults."""
    path = tmp_path / "nonexistent.toml"
    prompts = load_prompts(path)
    assert prompts == DEFAULT_PROMPTS


def test_default_freelance_prompts_require_online_only_providers() -> None:
    """Checks that freelance defaults keep the strict online-only lead gate."""
    assert "Online-only Bildungsanbieter" in DEFAULT_PROMPTS["Freelance German"]
    assert "Keine reinen Praesenzanbieter" in DEFAULT_PROMPTS["Freelance German"]
    assert "Australien" in DEFAULT_PROMPTS["Freelance German"]
    assert "weltweit" in DEFAULT_PROMPTS["Freelance German"]
    assert "offiziellen Anbieter-Website" in DEFAULT_PROMPTS["Freelance German"]
    assert "nicht valide markierte E-Mails" in DEFAULT_PROMPTS["Freelance German"]
    assert "online-only education or training providers" in DEFAULT_PROMPTS["Freelance English"]
    assert "in-person-only providers" in DEFAULT_PROMPTS["Freelance English"]
    assert "worldwide" in DEFAULT_PROMPTS["Freelance English"]
    assert "German or English" in DEFAULT_PROMPTS["Freelance English"]
    assert "official provider website" in DEFAULT_PROMPTS["Freelance English"]
    assert "invalid emails" in DEFAULT_PROMPTS["Freelance English"]
    assert "invalid_mails.csv" in DEFAULT_PROMPTS["Overseer"]
    assert "Germany, Australia, Switzerland, Austria, Luxembourg" in DEFAULT_PROMPTS["Overseer"]


def test_save_and_load(tmp_path):
    """Checks behavior for save and load."""
    path = tmp_path / "test_prompts.toml"
    custom_prompts = {
        "PhD": "Custom PhD Prompt",
        "Freelance German": "Custom German Prompt",
        "Freelance English": "Custom English Prompt",
        "Overseer": "Custom Overseer Prompt",
    }
    save_prompts(custom_prompts, path)

    # Check if file exists
    assert path.exists()

    # Load back
    loaded = load_prompts(path)
    assert loaded == custom_prompts


def test_partial_load(tmp_path):
    """Checks behavior for partial load."""
    path = tmp_path / "partial.toml"
    # Create a TOML with only one prompt
    content = '[prompts]\nPhD = "Only PhD"\n'
    path.write_text(content, encoding="utf-8")

    loaded = load_prompts(path)
    assert loaded["PhD"] == "Only PhD"
    assert loaded["Freelance German"] == DEFAULT_PROMPTS["Freelance German"]


def test_load_keeps_custom_task_prompts(tmp_path):
    """Checks behavior for loading custom task prompts."""
    path = tmp_path / "custom.toml"
    content = '[prompts]\n"Custom Task" = "Custom instructions"\n'
    path.write_text(content, encoding="utf-8")

    loaded = load_prompts(path)
    assert loaded["Custom Task"] == "Custom instructions"


def test_multiline_save(tmp_path):
    """Checks behavior for multiline save."""
    path = tmp_path / "multiline.toml"
    custom = DEFAULT_PROMPTS.copy()
    custom["PhD"] = "Line 1\nLine 2\nLine 3"
    save_prompts(custom, path)

    loaded = load_prompts(path)
    assert loaded["PhD"] == "Line 1\nLine 2\nLine 3"
