"""Tests and helpers for tests/test_main_wrapper.py."""

from __future__ import annotations

import io
import runpy

import pytest

import main as app_main


def setup_mock_mains(monkeypatch, calls: list) -> None:
    """Configures fake main functions for research and mail."""

    def fake_research_main(args):
        """Kapselt den Hilfsschritt fake_research_main."""
        calls.append(("research", args))
        return 0

    def fake_mail_main(args=None):
        """Kapselt den Hilfsschritt fake_mail_main."""
        calls.append(("mail", args))
        return 0

    monkeypatch.setattr("research.research_leads.main", fake_research_main)
    monkeypatch.setattr("mail_sender.cli.main", fake_mail_main)
    monkeypatch.setattr("sys.argv", ["code/main.py"])


def setup_target_send_config(monkeypatch, **kwargs) -> None:
    """Sets the standard configuration for Target-Send tests."""
    defaults = {
        "RUN_AI_RESEARCH": True,
        "SEND": True,
        "RESEARCH_WRITE_OUTPUT": True,
        "WRITE_SENT_LOG": True,
        "RESEND_EXISTING": False,
        "MODE": "PhD",
        "SEND_TARGET_COUNT": 2,
        "SEND_TARGET_MAX_ROUNDS": 0,
    }
    defaults.update(kwargs)
    for key, value in defaults.items():
        monkeypatch.setattr(app_main, key, value)


def _setup_target_loop_mocks(monkeypatch, **kwargs) -> None:
    """Sets standard mocks and configurations for Target-Loop tests."""
    setup_target_send_config(monkeypatch, **kwargs)
    monkeypatch.setattr(app_main, "SAVE_VERBOSE_LOG", kwargs.get("SAVE_VERBOSE_LOG", False))
    monkeypatch.setattr(app_main, "_get_logged_emails", lambda: {"old@example.com"})
    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args=None: 0)


def test_main_wrapper_can_run_research(monkeypatch) -> None:
    """Checks behavior for main wrapper can run research."""
    calls = []
    setup_mock_mains(monkeypatch, calls)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            "code/main.py",
            run_name="__main__",
            init_globals={
                "RUN_AI_RESEARCH": True,
                "RESEARCH_MODEL": "gpt-5.4",
                "MODE": "Freelance_English",
                "RESEARCH_MIN_COMPANIES": 2,
                "RESEARCH_MAX_COMPANIES": 4,
                "RESEARCH_PERSON_EMAILS_PER_COMPANY": 1,
                "RESEARCH_WRITE_OUTPUT": False,
                "RESEARCH_UPLOAD_ATTACHMENTS": False,
                "RESEARCH_CONTEXT_DELIVERY": "paste_in_prompt",
                "EXTERNAL_VALIDATION_SERVICE": "neverbounce",
                "EXTERNAL_VALIDATION_STAGE": "send",
                "SEND": True,
                "SEND_TARGET_COUNT": 0,
                "REQUIRE_EMAIL_SMTP_PASS": True,
                "REJECT_CATCH_ALL": True,
                "VERBOSE": True,
            },
        )

    assert exc_info.value.code == 0
    assert [call[0] for call in calls] == ["research", "mail"]
    research_args = calls[0][1]
    mail_args = calls[1][1]
    assert research_args[:6] == ["--provider", "openai", "--mode", "Freelance_English", "--base-dir", str(app_main.PROJECT_ROOT)]
    assert "--model" in research_args
    assert "gpt-5.4" in research_args
    assert "--no-write-output" in research_args
    assert "--no-upload-attachments" in research_args
    assert "--research-context-delivery" in research_args
    assert "paste_in_prompt" in research_args
    assert "--external-validation-service" in research_args
    assert "neverbounce" in research_args
    assert "--external-validation-stage" in research_args
    assert "send" in research_args
    assert "--parallel-threads" in research_args
    assert mail_args[:4] == ["--mode", "Freelance_English", "--base-dir", str(app_main.PROJECT_ROOT)]
    assert "--send" in mail_args
    assert "--parallel-threads" in mail_args
    assert "--require-email-smtp-pass" in mail_args
    assert "--reject-catch-all" in mail_args


def test_main_wrapper_defaults_to_research(monkeypatch) -> None:
    """Checks behavior for main wrapper defaults to research."""
    calls = []
    setup_mock_mains(monkeypatch, calls)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            "code/main.py",
            run_name="__main__",
            init_globals={"RUN_AI_RESEARCH": True, "SEND": False, "SEND_TARGET_COUNT": 0},
        )

    assert exc_info.value.code == 0
    assert [call[0] for call in calls] == ["research"]
    assert "--mode" in calls[0][1]


def test_main_summary_output(monkeypatch, capsys) -> None:
    """Checks behavior for main summary output."""
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    # Mock read_logged_rows to simulate state changes
    # Round 0: empty
    # Round 1: one entry
    state = {"calls": 0}

    def fake_read_logged_rows():
        """Kapselt den Hilfsschritt fake_read_logged_rows."""
        state["calls"] += 1
        if state["calls"] <= 1:
            return []
        return [{"company": "Test Company", "mail": "test@example.com"}]

    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args=None: 0)
    monkeypatch.setattr(app_main, "_read_output_sent_rows", lambda: fake_read_logged_rows())
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "SEND", True)
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 0)

    assert app_main._run() == 0
    captured = capsys.readouterr()
    assert "Summary: 1 unique email(s) sent to these recipients:" in captured.out
    assert "- Test Company: test@example.com" in captured.out


def test_target_loop_summary_output(monkeypatch, capsys) -> None:
    """Checks behavior for target loop summary output."""
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    # Mock read_known_output_emails to control the loop
    # Round 1 start: 0
    # Round 1 end: 1
    count_state = {"val": 0}

    def fake_read_emails():
        """Kapselt den Hilfsschritt fake_read_emails."""
        count = count_state["val"]
        count_state["val"] = 1
        return ["e" * i for i in range(count)]

    # Mock read_logged_rows for summary
    row_state = {"calls": 0}

    def fake_read_rows():
        """Kapselt den Hilfsschritt fake_read_rows."""
        row_state["calls"] += 1
        if row_state["calls"] <= 1:
            return []
        return [{"company": "Loop Company", "mail": "loop@example.com"}]

    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args=None: 0)
    monkeypatch.setattr(app_main, "_read_output_sent_rows", lambda: fake_read_rows())
    monkeypatch.setattr(app_main, "_get_logged_emails", lambda: fake_read_emails())
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "SEND", True)
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 1)
    monkeypatch.setattr(app_main, "RESEARCH_WRITE_OUTPUT", True)
    monkeypatch.setattr(app_main, "WRITE_SENT_LOG", True)
    monkeypatch.setattr(app_main, "RESEND_EXISTING", False)
    monkeypatch.setattr(app_main, "MODE", "PhD")

    assert app_main._run() == 0
    captured = capsys.readouterr()
    assert "Summary: 1 unique email(s) sent to these recipients:" in captured.out
    assert "- Loop Company: loop@example.com" in captured.out


def test_main_wrapper_forwards_explicit_cli_args_to_mail(monkeypatch) -> None:
    """Checks behavior for main wrapper forwards explicit cli args to mail."""
    calls = []

    def fake_mail_main(args=None):
        """Kapselt den Hilfsschritt fake_mail_main."""
        calls.append(args)
        return 0

    monkeypatch.setattr("mail_sender.cli.main", fake_mail_main)
    monkeypatch.setattr("sys.argv", ["code/main.py", "--mode", "PhD"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path("code/main.py", run_name="__main__")

    assert exc_info.value.code == 0
    assert calls == [None]


def test_main_helpers_cover_settings_and_log_branches(monkeypatch, tmp_path) -> None:
    """Checks behavior for main helpers cover settings and log branches."""
    monkeypatch.setattr(app_main, "SETTINGS_PATH", tmp_path / "missing.toml")
    assert app_main._load_settings() == {}

    stream = io.StringIO()
    tee = app_main._Tee(stream)
    assert tee.write("ok") == 2
    tee.flush()
    assert stream.getvalue() == "ok"

    monkeypatch.setattr(app_main, "SAVE_VERBOSE_LOG", False)
    assert app_main._create_log_file() is None


def test_main_run_stops_when_research_fails(monkeypatch) -> None:
    """Checks behavior for main run stops when research fails."""
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "RESEARCH_AI_PROVIDER", "gemini")
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 0)
    monkeypatch.setattr(app_main, "VERBOSE", False)
    monkeypatch.setattr(app_main, "research_main", lambda args: 7)
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    with pytest.raises(SystemExit) as exc_info:
        app_main._run()

    assert exc_info.value.code == 7


def test_main_run_can_skip_research_and_mail_directly(monkeypatch) -> None:
    """Checks behavior for main run can skip research and mail directly."""
    calls = []
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", False)
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "SEND", False)
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 0)
    monkeypatch.setattr(app_main, "VERBOSE", False)
    monkeypatch.setattr(app_main, "mail_main", lambda args: calls.append(args) or 0)
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    assert app_main._run() == 0
    assert calls == [app_main._build_mail_args()]


def test_main_mail_args_include_spam_safe_when_enabled(monkeypatch) -> None:
    """Checks that settings.toml spam-safe mode is forwarded to the mail CLI."""
    monkeypatch.setattr(app_main, "SPAM_SAFE_MODE", True)

    assert "--spam-safe" in app_main._build_mail_args()


def test_target_send_loop_repeats_until_logged_target_is_reached(monkeypatch) -> None:
    """Checks behavior for target send loop repeats until logged target is reached."""
    research_calls = []
    mail_calls = []
    email_sets = iter([
        {f"old{i}@example.com" for i in range(10)},
    ])
    row_sets = iter([
        [{"company": f"Old {i}", "mail": f"old{i}@example.com"} for i in range(10)],
        [{"company": f"Old {i}", "mail": f"old{i}@example.com"} for i in range(10)]
        + [{"company": "New 1", "mail": "new1@example.com"}, {"company": "New 2", "mail": "new2@example.com"}],
        [{"company": f"Old {i}", "mail": f"old{i}@example.com"} for i in range(10)]
        + [{"company": "New 1", "mail": "new1@example.com"}, {"company": "New 2", "mail": "new2@example.com"}],
        [{"company": f"Old {i}", "mail": f"old{i}@example.com"} for i in range(10)]
        + [{"company": "New 1", "mail": "new1@example.com"}, {"company": "New 2", "mail": "new2@example.com"}, {"company": "New 3", "mail": "new3@example.com"}],
    ])

    setup_target_send_config(monkeypatch, SEND_TARGET_COUNT=3)
    monkeypatch.setattr(app_main, "VERBOSE", False)
    monkeypatch.setattr(app_main, "research_main", lambda args: research_calls.append(args) or 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args: mail_calls.append(args) or 0)
    monkeypatch.setattr(app_main, "_get_logged_emails", lambda: next(email_sets))
    monkeypatch.setattr(app_main, "_read_output_sent_rows", lambda: next(row_sets))
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    assert app_main._run() == 0
    assert len(research_calls) == 2
    assert ["--max-send-count", "3"] == mail_calls[0][mail_calls[0].index("--max-send-count"):mail_calls[0].index("--max-send-count") + 2]
    assert ["--max-send-count", "1"] == mail_calls[1][mail_calls[1].index("--max-send-count"):mail_calls[1].index("--max-send-count") + 2]


def test_count_logged_sent_emails_uses_project_output(monkeypatch) -> None:
    """Checks behavior for count logged sent emails uses project output."""
    calls = []
    monkeypatch.setattr(
        app_main,
        "read_known_output_emails",
        lambda path: calls.append(path) or {"a@example.com", "b@example.com"},
    )

    assert app_main._count_logged_sent_emails() == 2
    assert calls == [app_main.PROJECT_ROOT / "output"]


def test_target_send_loop_requires_real_research_and_logging(monkeypatch, capsys) -> None:
    """Checks behavior for target send loop requires real research and logging."""
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 0)
    assert app_main._validate_target_send_settings() is True

    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", False)
    monkeypatch.setattr(app_main, "SEND", True)
    monkeypatch.setattr(app_main, "RESEARCH_WRITE_OUTPUT", True)
    monkeypatch.setattr(app_main, "WRITE_SENT_LOG", True)
    monkeypatch.setattr(app_main, "RESEND_EXISTING", False)
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 10)
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    assert app_main._run() == 1
    assert "RUN_AI_RESEARCH must be true" in capsys.readouterr().out


def test_target_send_loop_reports_all_invalid_setting_combinations(monkeypatch, capsys) -> None:
    """Checks behavior for target send loop reports all invalid setting combinations."""
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "SEND", False)
    monkeypatch.setattr(app_main, "RESEARCH_WRITE_OUTPUT", False)
    monkeypatch.setattr(app_main, "WRITE_SENT_LOG", False)
    monkeypatch.setattr(app_main, "RESEND_EXISTING", True)
    monkeypatch.setattr(app_main, "MODE", "Auto")
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 10)

    assert app_main._validate_target_send_settings() is False
    output = capsys.readouterr().out
    assert "SEND must be true" in output
    assert "RESEARCH_WRITE_OUTPUT must be true" in output
    assert "WRITE_SENT_LOG must be true" in output
    assert "RESEND_EXISTING must be false" in output
    assert 'MODE must be a concrete mode, not "Auto"' in output


def test_target_send_loop_stops_when_no_new_sent_log_entries_are_created(monkeypatch, capsys) -> None:
    """Checks behavior for target send loop stops when no new sent log entries are created."""
    rows = [{"company": f"Old {i}", "mail": f"old{i}@example.com"} for i in range(5)]
    setup_target_send_config(monkeypatch)
    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args: 0)
    monkeypatch.setattr(app_main, "_get_logged_emails", lambda: {row["mail"] for row in rows})
    monkeypatch.setattr(app_main, "_read_output_sent_rows", lambda: rows)
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    assert app_main._run() == 1
    assert "No new unique sent-log entries" in capsys.readouterr().out


def test_target_send_loop_stops_when_research_fails(monkeypatch) -> None:
    """Checks behavior for target send loop stops when research fails."""
    setup_target_send_config(monkeypatch)
    monkeypatch.setattr(app_main, "research_main", lambda args: 6)
    monkeypatch.setattr(app_main, "_count_logged_sent_emails", lambda: 0)

    assert app_main._run_target_send_loop() == 6


def test_target_send_loop_stops_at_max_rounds(monkeypatch, capsys) -> None:
    """Checks behavior for target send loop stops at max rounds."""
    row_sets = iter([[], [{"company": "One", "mail": "one@example.com"}]])
    setup_target_send_config(monkeypatch, SEND_TARGET_MAX_ROUNDS=1)
    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args: 0)
    monkeypatch.setattr(app_main, "_get_logged_emails", lambda: set())
    monkeypatch.setattr(app_main, "_read_output_sent_rows", lambda: next(row_sets))

    assert app_main._run_target_send_loop() == 1
    assert "SEND_TARGET_MAX_ROUNDS=1" in capsys.readouterr().out


def test_target_send_loop_stops_when_mail_sender_errors(monkeypatch, capsys) -> None:
    """Checks behavior for target send loop stops when mail sender errors."""
    row_sets = iter([[], [{"company": "One", "mail": "one@example.com"}]])
    setup_target_send_config(monkeypatch)
    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args: 4)
    monkeypatch.setattr(app_main, "_get_logged_emails", lambda: set())
    monkeypatch.setattr(app_main, "_read_output_sent_rows", lambda: next(row_sets))

    assert app_main._run_target_send_loop() == 4
    assert "Mail sender returned an error" in capsys.readouterr().out


def test_run_with_optional_log_can_skip_log_and_closes_on_error(monkeypatch, tmp_path) -> None:
    """Checks behavior for run with optional log can skip log and closes on error."""
    monkeypatch.setattr(app_main, "SAVE_VERBOSE_LOG", False)
    monkeypatch.setattr(app_main, "_run", lambda: 12)
    assert app_main._run_with_optional_log() == 12

    def fail_run() -> int:
        """Kapselt den Hilfsschritt fail_run."""
        raise RuntimeError("boom")

    monkeypatch.setattr(app_main, "SAVE_VERBOSE_LOG", True)
    monkeypatch.setattr(app_main, "VERBOSE_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "_run", fail_run)

    with pytest.raises(RuntimeError, match="boom"):
        app_main._run_with_optional_log()

    assert list(tmp_path.glob("run_phd_*.log"))


def test_target_loop_max_rounds_safety_gate(monkeypatch, capsys) -> None:
    """Checks behavior for target loop max rounds safety gate."""
    _setup_target_loop_mocks(monkeypatch, SEND_TARGET_COUNT=100, SEND_TARGET_MAX_ROUNDS=1)

    # To simulate progress but then stop because of max_rounds=1
    # Round 1 start: current_count = 1
    # Round 1 end: current_count = 2 (progress made)
    # But loop condition is 2 < 101.
    # After round 1 finished, it checks round_number > max_rounds.

    row_sets = iter([
        [{"company": "Old", "mail": "old@example.com"}],
        [{"company": "Old", "mail": "old@example.com"}, {"company": "Round 1", "mail": "new@example.com"}],
    ])
    monkeypatch.setattr(app_main, "_read_output_sent_rows", lambda: next(row_sets))

    status = app_main._run_target_send_loop()
    assert status == 1
    captured = capsys.readouterr()
    assert "Safety gate active: Maximum of 1 round(s) allowed." in captured.out
    assert "Stopping before target because SEND_TARGET_MAX_ROUNDS=1 was reached." in captured.out


def test_target_loop_unlimited_warning(monkeypatch, capsys) -> None:
    """Checks behavior for target loop unlimited warning."""
    _setup_target_loop_mocks(monkeypatch, SEND_TARGET_COUNT=100, SEND_TARGET_MAX_ROUNDS=0)

    monkeypatch.setattr(app_main, "_read_output_sent_rows", lambda: [])

    app_main._run_target_send_loop()
    captured = capsys.readouterr()
    assert "Safety gate: Unlimited rounds (0) until target is reached." in captured.out
    assert "Note: With a high target count and unlimited rounds" in captured.out
