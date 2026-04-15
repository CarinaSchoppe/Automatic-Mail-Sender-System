from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from gui.app import MailSenderWorkbench


def test_mail_sender_workbench_collects_and_saves_settings(tmp_path: Path) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        app = MailSenderWorkbench(root, project_root=tmp_path)
        app.variables["MODE"].set("PhD")
        app.env_variables["SMTP_USERNAME"].set("mailer")
        app.variables["PARALLEL_THREADS"].set(9)
        app.keyword_text.delete("1.0", "end")
        app.keyword_text.insert("1.0", "alpha email\nbeta contact\n")

        values = app.collect_form_values()
        env_values = app.collect_env_values()
        assert values["MODE"] == "PhD"
        assert values["PARALLEL_THREADS"] == 9
        assert values["SELF_SEARCH_KEYWORDS"] == ["alpha email", "beta contact"]
        assert env_values["SMTP_USERNAME"] == "mailer"

        app.save_all()
        assert 'MODE = "PhD"' in (tmp_path / "settings.toml").read_text(encoding="utf-8")
        assert "SMTP_USERNAME=mailer" in (tmp_path / ".env").read_text(encoding="utf-8")
    finally:
        root.destroy()


def test_mail_sender_workbench_refreshes_output_and_log_tables(tmp_path: Path) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        input_dir = tmp_path / "input" / "PhD"
        output_dir = tmp_path / "output"
        log_dir = tmp_path / "logs"
        input_dir.mkdir(parents=True)
        output_dir.mkdir()
        log_dir.mkdir()
        (input_dir / "research_phd.csv").write_text(
            "company,mail,source_url\nLead,l@example.com,https://lead.example\n",
            encoding="utf-8",
        )
        (output_dir / "send_phd.csv").write_text(
            "company,mail,source_url\nAcme,a@example.com,https://example.com\n",
            encoding="utf-8",
        )
        (log_dir / "run.log").write_text("[INFO] ok", encoding="utf-8")

        app = MailSenderWorkbench(root, project_root=tmp_path)
        app.refresh_tables()

        assert len(app.input_tree.get_children()) == 1
        assert len(app.found_tree.get_children()) == 1
        assert len(app.sent_tree.get_children()) == 1
        assert len(app.log_tree.get_children()) == 1

        app.input_tree.selection_set(app.input_tree.get_children()[0])
        app._show_selected_file(app.input_tree, "input")
        assert "Lead,l@example.com" in app.file_viewer.get("1.0", "end")
    finally:
        root.destroy()


def test_mail_sender_workbench_imports_input_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        source = tmp_path / "leads.csv"
        source.write_text("company,mail\nImported,i@example.com\n", encoding="utf-8")
        monkeypatch.setattr("gui.app.filedialog.askopenfilename", lambda **_kwargs: str(source))

        app = MailSenderWorkbench(root, project_root=tmp_path)
        app.input_mode_var.set("Freelance_German")
        app.import_input_file()

        target = tmp_path / "input" / "Freelance_German" / "leads.csv"
        assert target.exists()
        assert len(app.input_tree.get_children()) == 1
    finally:
        root.destroy()


def test_mail_sender_workbench_exposes_required_tabs(tmp_path: Path) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        app = MailSenderWorkbench(root, project_root=tmp_path)
        tabs = [app.notebook.tab(tab_id, "text") for tab_id in app.notebook.tabs()]

        assert tabs == ["Settings", ".env", "AI Inputs", "Found Mails", "Sent Mails", "Saved Logs", "Run Console"]
        assert app.autosave.get() is True
        assert app.auto_refresh.get() is True
    finally:
        root.destroy()


def test_mail_sender_workbench_mail_only_command_and_integer_sliders(tmp_path: Path) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        app = MailSenderWorkbench(root, project_root=tmp_path)
        app.variables["MODE"].set("Freelance_English")
        app.variables["PARALLEL_THREADS"].set(7)
        app.variables["SEND"].set(True)
        command = app._mail_only_command()

        assert any("from mail_sender.cli import main" in part for part in command)
        assert "--mode" in command
        assert "Freelance_English" in command
        assert "--send" in command
        assert "--parallel-threads" in command
        assert "7" in command
        assert isinstance(app.variables["RESEARCH_MIN_COMPANIES"].get(), int)
        assert isinstance(app.variables["RESEARCH_MAX_COMPANIES"].get(), int)
    finally:
        root.destroy()


def test_mail_sender_workbench_opens_log_in_new_tab(tmp_path: Path) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "run.log").write_text("[INFO] visible log", encoding="utf-8")

        app = MailSenderWorkbench(root, project_root=tmp_path)
        app.refresh_tables()
        app.log_tree.selection_set(app.log_tree.get_children()[0])
        before = len(app.notebook.tabs())
        app.open_selected_log_tab()

        assert len(app.notebook.tabs()) == before + 1
        assert app.notebook.tab(app.notebook.select(), "text") == "Log: run.log"
    finally:
        root.destroy()
