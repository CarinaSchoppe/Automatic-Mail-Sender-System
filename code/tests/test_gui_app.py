"""Tests and helpers for tests/test_gui_app.py."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

import pytest

from gui.app import MailSenderWorkbench
from gui.settings_store import ENV_SCHEMA, SETTINGS_SCHEMA


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
        app.variables["SKIP_EMAIL_DNS_CHECK"].set(True)
        app.variables["SUBJECT_OVERRIDE"].set("Custom subject")
        command = app._mail_only_command()

        assert any("from mail_sender.cli import main" in part for part in command)
        assert "--mode" in command
        assert "Freelance_English" in command
        assert "--send" in command
        assert "--spam-safe" in command
        assert "--skip-email-dns-check" in command
        assert "--subject" in command
        assert "Custom subject" in command
        assert "--parallel-threads" in command
        assert "7" in command
        assert isinstance(app.variables["RESEARCH_MIN_COMPANIES"].get(), int)
        assert isinstance(app.variables["RESEARCH_MAX_COMPANIES"].get(), int)
        assert "SMTP_PORT" in app.variables
    finally:
        root.destroy()


def test_mail_sender_workbench_research_only_command_uses_gui_settings(tmp_path: Path) -> None:
    """Checks that Research Only forwards all important GUI settings explicitly."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        app = MailSenderWorkbench(root, project_root=tmp_path)
        app.variables["MODE"].set("Custom_Online_Training")
        app.variables["RESEARCH_MODEL"].set("gemini-3-flash-preview")
        app.variables["RESEARCH_MIN_COMPANIES"].set(12)
        app.variables["RESEARCH_MAX_COMPANIES"].set(34)
        app.variables["RESEARCH_WRITE_OUTPUT"].set(False)
        app.variables["RESEARCH_UPLOAD_ATTACHMENTS"].set(False)
        app.variables["VERBOSE"].set(True)
        command = app._research_only_command()

        assert command[:2] == [sys.executable, "code/research/research_leads.py"]
        assert "--mode" in command
        assert "Custom_Online_Training" in command
        assert "--model" in command
        assert "gemini-3-flash-preview" in command
        assert "--min-companies" in command
        assert "12" in command
        assert "--max-companies" in command
        assert "34" in command
        assert "--no-write-output" in command
        assert "--no-upload-attachments" in command
        assert "--verbose" in command
    finally:
        root.destroy()


def test_mail_sender_workbench_blocks_target_pipeline_when_send_is_off(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    """Checks that target sending cannot be started from the GUI with SEND disabled."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        errors: list[tuple[str, str]] = []
        commands: list[list[str]] = []
        app = MailSenderWorkbench(root, project_root=tmp_path)
        app.variables["SEND"].set(False)
        app.variables["SEND_TARGET_COUNT"].set(550)
        monkeypatch.setattr("gui.app.messagebox.showerror", lambda title, body: errors.append((title, body)))
        monkeypatch.setattr(app, "_start_command", lambda command: commands.append(command))

        app.start_process(["code/main.py"])

        assert commands == []
        assert errors
        assert errors[0][0] == "SEND is off"
        assert "SEND / Real email sending" in errors[0][1]
        assert app.setting_search_vars["settings"].get() == "SEND"
    finally:
        root.destroy()


def test_mail_sender_workbench_formats_failed_process_log_details(tmp_path: Path) -> None:
    """Checks that failed processes show the saved traceback in the GUI console."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        log_path = tmp_path / "logs" / "run.log"
        log_path.parent.mkdir()
        log_path.write_text(
            "[INFO] before\n"
            "Traceback (most recent call last):\n"
            "  File \"code/main.py\", line 1, in <module>\n"
            "RuntimeError: boom\n",
            encoding="utf-8",
        )
        app = MailSenderWorkbench(root, project_root=tmp_path)
        app._remember_process_log_path(f"[INFO] Saving terminal log to {log_path}.\n")

        details = app._format_process_failure_details(1, ["fallback\n"])

        assert "PROCESS FAILED WITH EXIT CODE 1" in details
        assert str(log_path) in details
        assert "Traceback (most recent call last):" in details
        assert "RuntimeError: boom" in details
        assert "[INFO] before" not in details
    finally:
        root.destroy()


def test_mail_sender_workbench_filters_settings_and_env(tmp_path: Path) -> None:
    """Checks behavior for settings and env search filters."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
        pytest.skip(f"Tkinter is unavailable: {exc}")
    root.withdraw()
    try:
        app = MailSenderWorkbench(root, project_root=tmp_path)

        assert len(app.setting_row_widgets["settings"]) == len(SETTINGS_SCHEMA)
        app.setting_search_vars["settings"].set("spam safe")
        visible_setting_keys = {
            row["key"]
            for row in app.setting_row_widgets["settings"]
            if row["visible"]
        }

        assert visible_setting_keys == {"SPAM_SAFE_MODE"}
        assert app.setting_search_counts["settings"].get() == f"1/{len(SETTINGS_SCHEMA)}"

        app.setting_search_vars["settings"].set("")
        assert app.setting_search_counts["settings"].get() == ""
        assert all(row["visible"] for row in app.setting_row_widgets["settings"])

        app.setting_search_vars["env"].set("password")
        visible_env_keys = {
            row["key"]
            for row in app.setting_row_widgets["env"]
            if row["visible"]
        }

        assert visible_env_keys == {"SMTP_PASSWORD"}
        assert app.setting_search_counts["env"].get() == f"1/{len(ENV_SCHEMA)}"
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
