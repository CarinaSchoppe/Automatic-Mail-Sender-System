"""Tests and helpers for tests/test_gui_prompts.py."""

import tkinter as tk

import pytest

from gui.app import MailSenderWorkbench


@pytest.fixture
def workbench(tmp_path):
    """Encapsulates the helper step workbench."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    # Mock project root to avoid touching real files
    project_root = tmp_path
    # Create necessary dirs/files for WB initialization
    (project_root / "input" / "PhD").mkdir(parents=True)
    (project_root / "settings.toml").touch()
    (project_root / ".env").touch()

    wb = MailSenderWorkbench(root, project_root=project_root)
    yield wb
    root.destroy()


def test_workbench_loads_prompts(workbench):
    """Checks behavior for workbench loads prompts."""
    assert hasattr(workbench, "prompts")
    assert "PhD" in workbench.prompts


def test_workbench_updates_prompt_on_change(workbench):
    # Select another mode
    """Prueft das Verhalten fuer workbench updates prompt on change."""
    workbench.prompt_mode_var.set("Freelance German")
    workbench._on_prompt_mode_change()

    current_text = workbench.prompt_text.get("1.0", "end-1c")
    assert current_text == workbench.prompts["Freelance German"]


def test_workbench_saves_prompts(workbench, tmp_path):
    """Checks behavior for workbench saves prompts."""
    workbench.prompt_text.delete("1.0", "end")
    workbench.prompt_text.insert("1.0", "My New Prompt")

    # Simulate saving
    workbench.save_all_prompts()

    # Check file
    assert (workbench.project_root / "prompts.toml").exists()
    from mail_sender.prompts import load_prompts
    loaded = load_prompts(workbench.project_root / "prompts.toml")
    assert loaded["PhD"] == "My New Prompt"  # Since PhD was default selected


def test_workbench_adds_custom_task_to_prompt_template_and_mode_dropdowns(workbench):
    """Checks that a custom task is immediately available across prompt, template, and mode controls."""
    workbench.new_task_var.set("Custom Online Training")

    workbench.add_prompt_task()

    assert "Custom Online Training" in workbench.prompts
    assert workbench.prompt_mode_var.get() == "Custom Online Training"
    assert workbench.variables["MODE"].get() == "Custom_Online_Training"
    assert "Custom_Online_Training" in workbench.mode_setting_combo.cget("values")
    assert "Custom_Online_Training" in workbench.input_mode_combo.cget("values")
    assert "Custom Online Training" in workbench.mail_template_combo.cget("values")
    assert "Custom Online Training spam-safe" in workbench.mail_template_combo.cget("values")
    assert (workbench.project_root / "input" / "Custom_Online_Training").exists()
    assert (workbench.project_root / "attachments" / "Custom_Online_Training").exists()
    assert (workbench.project_root / "templates" / "custom_online_training.txt").exists()
    assert (workbench.project_root / "templates" / "custom_online_training_spam_safe.txt").exists()
