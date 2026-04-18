"""Tests and helpers for tests/test_gui_app.py."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from gui.app import MailSenderWorkbench


def test_mail_sender_workbench_collects_and_saves_settings(tmp_path: Path) -> None:
    """Checks behavior for mail sender workbench collects and saves settings."""
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
        if app.keyword_text is not None:
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
    """Checks behavior for mail sender workbench refreshes output and log tables."""
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


def test_mail_sender_workbench_routes_sent_tabs_by_mail_file(tmp_path: Path) -> None:
    """Checks the PhD, Freelance, and Invalid assignment of mailing lists."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "send_phd.csv").write_text(
            "company,mail,source_url\nPhD Co,phd@example.com,https://phd.example\n",
            encoding="utf-8",
        )
        (output_dir / "send_freelance.csv").write_text(
            "company,mail,source_url\nFree Co,free@example.com,https://free.example\n",
            encoding="utf-8",
        )
        (output_dir / "invalid_mails.csv").write_text(
            "company,mail,invalid_reason,detected_at\nBad Co,bad@example.invalid,no mx,2026-04-15T10:00:00+10:00\n",
            encoding="utf-8",
        )

        app = MailSenderWorkbench(root, project_root=tmp_path)
        sent_tabs = [app.sent_notebook.tab(tab_id, "text") for tab_id in app.sent_notebook.tabs()]

        assert sent_tabs == ["PhD", "Freelance", "Invalid"]
        assert len(app.sent_trees["PhD"].get_children()) == 1
        assert len(app.sent_trees["Freelance"].get_children()) == 1
        assert len(app.sent_trees["Invalid"].get_children()) == 1
        invalid_values = app.sent_trees["Invalid"].item(app.sent_trees["Invalid"].get_children()[0])["values"]
        assert invalid_values == ["invalid_mails.csv", "Bad Co", "bad@example.invalid", "no mx"]
    finally:
        root.destroy()


def test_mail_sender_workbench_imports_input_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prueft das Verhalten fuer mail sender workbench imports input file."""
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
    """Prueft das Verhalten fuer mail sender workbench exposes required tabs."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        app = MailSenderWorkbench(root, project_root=tmp_path)
        tabs = [app.notebook.tab(tab_id, "text") for tab_id in app.notebook.tabs()]

        assert tabs == [
            "Settings",
            ".env",
            "Prompts",
            "Mail Templates",
            "AI Inputs",
            "Found Mails",
            "Sent Mails",
            "Saved Logs",
            "Run Console",
        ]
        assert app.autosave.get() is True
        assert app.auto_refresh.get() is True
    finally:
        root.destroy()


def test_mail_sender_workbench_mail_only_command_and_integer_sliders(tmp_path: Path) -> None:
    """Prueft das Verhalten fuer mail sender workbench mail only command and integer sliders."""
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
        app.variables["SPAM_SAFE_MODE"].set(True)
        command = app._mail_only_command()

        assert any("from mail_sender.cli import main" in part for part in command)
        assert "--mode" in command
        assert "Freelance_English" in command
        assert "--send" in command
        assert "--spam-safe" in command
        assert "--parallel-threads" in command
        assert "7" in command
        assert isinstance(app.variables["RESEARCH_MIN_COMPANIES"].get(), int)
        assert isinstance(app.variables["RESEARCH_MAX_COMPANIES"].get(), int)
        assert "SMTP_PORT" in app.variables
    finally:
        root.destroy()


def test_mail_sender_workbench_edits_mail_templates(tmp_path: Path) -> None:
    """Checks behavior for mail template editing in the GUI."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "phd.txt").write_text("Subject: Old\n\nOld body", encoding="utf-8")

        app = MailSenderWorkbench(root, project_root=tmp_path)
        app.mail_template_var.set("PhD")
        app._on_mail_template_change()
        app.mail_template_text.delete("1.0", "end")
        app.mail_template_text.insert("1.0", "Subject: New\n\nNew body")
        app.save_mail_templates()

        assert (templates_dir / "phd.txt").read_text(encoding="utf-8") == "Subject: New\n\nNew body\n"
        assert (templates_dir / "phd_spam_safe.txt").exists()
    finally:
        root.destroy()


def test_mail_sender_workbench_opens_log_in_new_tab(tmp_path: Path) -> None:
    """Prueft das Verhalten fuer mail sender workbench opens log in new tab."""
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
        selected_tab = app.root.nametowidget(app.notebook.select())
        app.close_tab(selected_tab)
        assert len(app.notebook.tabs()) == before
    finally:
        root.destroy()
