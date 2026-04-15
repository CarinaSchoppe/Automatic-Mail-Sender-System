import pytest
from pathlib import Path
from mail_sender.prompts import load_prompts, save_prompts, DEFAULT_PROMPTS

def test_load_defaults(tmp_path):
    # If file doesn't exist, should return defaults
    path = tmp_path / "nonexistent.toml"
    prompts = load_prompts(path)
    assert prompts == DEFAULT_PROMPTS

def test_save_and_load(tmp_path):
    path = tmp_path / "test_prompts.toml"
    custom_prompts = {
        "PhD": "Custom PhD Prompt",
        "Freelance German": "Custom German Prompt",
        "Freelance English": "Custom English Prompt"
    }
    save_prompts(custom_prompts, path)
    
    # Check if file exists
    assert path.exists()
    
    # Load back
    loaded = load_prompts(path)
    assert loaded == custom_prompts

def test_partial_load(tmp_path):
    path = tmp_path / "partial.toml"
    # Create a TOML with only one prompt
    content = '[prompts]\nPhD = "Only PhD"\n'
    path.write_text(content, encoding="utf-8")
    
    loaded = load_prompts(path)
    assert loaded["PhD"] == "Only PhD"
    assert loaded["Freelance German"] == DEFAULT_PROMPTS["Freelance German"]

def test_multiline_save(tmp_path):
    path = tmp_path / "multiline.toml"
    custom = DEFAULT_PROMPTS.copy()
    custom["PhD"] = "Line 1\nLine 2\nLine 3"
    save_prompts(custom, path)
    
    loaded = load_prompts(path)
    assert loaded["PhD"] == "Line 1\nLine 2\nLine 3"
