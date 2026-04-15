import tkinter as tk

import pytest

from gui.app import MailSenderWorkbench


@pytest.fixture
def workbench(tmp_path):
    root = tk.Tk()
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
    assert hasattr(workbench, "prompts")
    assert "PhD" in workbench.prompts


def test_workbench_updates_prompt_on_change(workbench):
    # Select another mode
    workbench.prompt_mode_var.set("Freelance German")
    workbench._on_prompt_mode_change()

    current_text = workbench.prompt_text.get("1.0", "end-1c")
    assert current_text == workbench.prompts["Freelance German"]


def test_workbench_saves_prompts(workbench, tmp_path):
    workbench.prompt_text.delete("1.0", "end")
    workbench.prompt_text.insert("1.0", "My New Prompt")

    # Simulate saving
    workbench.save_all_prompts()

    # Check file
    assert (workbench.project_root / "prompts.toml").exists()
    from mail_sender.prompts import load_prompts
    loaded = load_prompts(workbench.project_root / "prompts.toml")
    assert loaded["PhD"] == "My New Prompt"  # Since PhD was default selected
