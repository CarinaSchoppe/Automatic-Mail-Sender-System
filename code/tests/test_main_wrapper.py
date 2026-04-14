from __future__ import annotations

import io
import runpy

import pytest

import main as app_main


def test_main_wrapper_can_run_research(monkeypatch) -> None:
    calls = []

    def fake_research_main(args):
        calls.append(("research", args))
        return 0

    def fake_mail_main(args=None):
        calls.append(("mail", args))
        return 0

    monkeypatch.setattr("research.research_leads.main", fake_research_main)
    monkeypatch.setattr("mail_sender.cli.main", fake_mail_main)
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
                "code/main.py",
            run_name="__main__",
            init_globals={
                "RUN_AI_RESEARCH": True,
                "RESEARCH_AI_PROVIDER": "openai",
                "MODE": "Freelance_English",
                "RESEARCH_MIN_COMPANIES": 2,
                "RESEARCH_MAX_COMPANIES": 4,
                "RESEARCH_PERSON_EMAILS_PER_COMPANY": 1,
                "RESEARCH_WRITE_OUTPUT": False,
                "RESEARCH_UPLOAD_ATTACHMENTS": False,
                "SEND": True,
                "SEND_TARGET_COUNT": 0,
                "VERBOSE": True,
            },
        )

    assert exc_info.value.code == 0
    assert calls == [
        (
            "research",
            [
                "--provider",
                "openai",
                "--mode",
                "Freelance_English",
                "--min-companies",
                "2",
                "--max-companies",
                "4",
                "--person-emails-per-company",
                "1",
                "--no-write-output",
                "--no-upload-attachments",
                "--verbose",
            ],
        ),
        (
            "mail",
            [
                "--mode",
                "Freelance_English",
                "--signature-logo",
                "templates/signature-logo.png",
                "--signature-logo-width",
                "325",
                "--send",
                "--verbose",
            ],
        ),
    ]


def test_main_wrapper_defaults_to_research(monkeypatch) -> None:
    calls = []

    def fake_research_main(args):
        calls.append(("research", args))
        return 0

    def fake_mail_main(args=None):
        calls.append(("mail", args))
        return 0

    monkeypatch.setattr("research.research_leads.main", fake_research_main)
    monkeypatch.setattr("mail_sender.cli.main", fake_mail_main)
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            "code/main.py",
            run_name="__main__",
            init_globals={"SEND": False, "SEND_TARGET_COUNT": 0},
        )

    assert exc_info.value.code == 0
    assert [call[0] for call in calls] == ["research"]
    assert "--mode" in calls[0][1]


def test_main_wrapper_forwards_explicit_cli_args_to_mail(monkeypatch) -> None:
    calls = []

    def fake_mail_main(args=None):
        calls.append(args)
        return 0

    monkeypatch.setattr("mail_sender.cli.main", fake_mail_main)
    monkeypatch.setattr("sys.argv", ["code/main.py", "--mode", "PhD"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path("code/main.py", run_name="__main__")

    assert exc_info.value.code == 0
    assert calls == [None]


def test_main_helpers_cover_settings_and_log_branches(monkeypatch, tmp_path) -> None:
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


def test_target_send_loop_repeats_until_logged_target_is_reached(monkeypatch) -> None:
    research_calls = []
    mail_calls = []
    logged_counts = iter([10, 12, 13])

    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "SEND", True)
    monkeypatch.setattr(app_main, "RESEARCH_WRITE_OUTPUT", True)
    monkeypatch.setattr(app_main, "WRITE_SENT_LOG", True)
    monkeypatch.setattr(app_main, "RESEND_EXISTING", False)
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 3)
    monkeypatch.setattr(app_main, "SEND_TARGET_MAX_ROUNDS", 0)
    monkeypatch.setattr(app_main, "VERBOSE", False)
    monkeypatch.setattr(app_main, "research_main", lambda args: research_calls.append(args) or 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args: mail_calls.append(args) or 0)
    monkeypatch.setattr(app_main, "_count_logged_sent_emails", lambda: next(logged_counts))
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    assert app_main._run() == 0
    assert len(research_calls) == 2
    assert mail_calls[0][-2:] == ["--max-send-count", "3"]
    assert mail_calls[1][-2:] == ["--max-send-count", "1"]


def test_count_logged_sent_emails_uses_project_output(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        app_main,
        "read_known_output_emails",
        lambda path: calls.append(path) or {"a@example.com", "b@example.com"},
    )

    assert app_main._count_logged_sent_emails() == 2
    assert calls == [app_main.PROJECT_ROOT / "output"]


def test_target_send_loop_requires_real_research_and_logging(monkeypatch, capsys) -> None:
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
    counts = iter([5, 5])
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "SEND", True)
    monkeypatch.setattr(app_main, "RESEARCH_WRITE_OUTPUT", True)
    monkeypatch.setattr(app_main, "WRITE_SENT_LOG", True)
    monkeypatch.setattr(app_main, "RESEND_EXISTING", False)
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 2)
    monkeypatch.setattr(app_main, "SEND_TARGET_MAX_ROUNDS", 0)
    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args: 0)
    monkeypatch.setattr(app_main, "_count_logged_sent_emails", lambda: next(counts))
    monkeypatch.setattr("sys.argv", ["code/main.py"])

    assert app_main._run() == 1
    assert "No new sent-log entries" in capsys.readouterr().out


def test_target_send_loop_stops_when_research_fails(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "SEND", True)
    monkeypatch.setattr(app_main, "RESEARCH_WRITE_OUTPUT", True)
    monkeypatch.setattr(app_main, "WRITE_SENT_LOG", True)
    monkeypatch.setattr(app_main, "RESEND_EXISTING", False)
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 2)
    monkeypatch.setattr(app_main, "SEND_TARGET_MAX_ROUNDS", 0)
    monkeypatch.setattr(app_main, "research_main", lambda args: 6)
    monkeypatch.setattr(app_main, "_count_logged_sent_emails", lambda: 0)

    assert app_main._run_target_send_loop() == 6


def test_target_send_loop_stops_at_max_rounds(monkeypatch, capsys) -> None:
    counts = iter([0, 1])
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "SEND", True)
    monkeypatch.setattr(app_main, "RESEARCH_WRITE_OUTPUT", True)
    monkeypatch.setattr(app_main, "WRITE_SENT_LOG", True)
    monkeypatch.setattr(app_main, "RESEND_EXISTING", False)
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 2)
    monkeypatch.setattr(app_main, "SEND_TARGET_MAX_ROUNDS", 1)
    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args: 0)
    monkeypatch.setattr(app_main, "_count_logged_sent_emails", lambda: next(counts))

    assert app_main._run_target_send_loop() == 1
    assert "SEND_TARGET_MAX_ROUNDS=1" in capsys.readouterr().out


def test_target_send_loop_stops_when_mail_sender_errors(monkeypatch, capsys) -> None:
    counts = iter([0, 1])
    monkeypatch.setattr(app_main, "RUN_AI_RESEARCH", True)
    monkeypatch.setattr(app_main, "SEND", True)
    monkeypatch.setattr(app_main, "RESEARCH_WRITE_OUTPUT", True)
    monkeypatch.setattr(app_main, "WRITE_SENT_LOG", True)
    monkeypatch.setattr(app_main, "RESEND_EXISTING", False)
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "SEND_TARGET_COUNT", 2)
    monkeypatch.setattr(app_main, "SEND_TARGET_MAX_ROUNDS", 0)
    monkeypatch.setattr(app_main, "research_main", lambda args: 0)
    monkeypatch.setattr(app_main, "mail_main", lambda args: 4)
    monkeypatch.setattr(app_main, "_count_logged_sent_emails", lambda: next(counts))

    assert app_main._run_target_send_loop() == 4
    assert "Mail sender returned an error" in capsys.readouterr().out


def test_run_with_optional_log_can_skip_log_and_closes_on_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_main, "SAVE_VERBOSE_LOG", False)
    monkeypatch.setattr(app_main, "_run", lambda: 12)
    assert app_main._run_with_optional_log() == 12

    def fail_run() -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(app_main, "SAVE_VERBOSE_LOG", True)
    monkeypatch.setattr(app_main, "VERBOSE_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(app_main, "MODE", "PhD")
    monkeypatch.setattr(app_main, "_run", fail_run)

    with pytest.raises(RuntimeError, match="boom"):
        app_main._run_with_optional_log()

    assert list(tmp_path.glob("run_phd_*.log"))
