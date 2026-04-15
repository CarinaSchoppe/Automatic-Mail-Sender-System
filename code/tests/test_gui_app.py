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

        assert len(app.found_tree.get_children()) == 1
        assert len(app.sent_tree.get_children()) == 1
        assert len(app.log_tree.get_children()) == 1
    finally:
        root.destroy()
