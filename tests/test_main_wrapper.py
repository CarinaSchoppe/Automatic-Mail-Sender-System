from __future__ import annotations

import runpy

import pytest


def test_main_wrapper_can_run_research(monkeypatch) -> None:
    calls = []

    def fake_research_main(args):
        calls.append(("research", args))
        return 0

    def fake_mail_main(args=None):
        calls.append(("mail", args))
        return 0

    monkeypatch.setattr("Research.research_leads.main", fake_research_main)
    monkeypatch.setattr("mail_sender.cli.main", fake_mail_main)
    monkeypatch.setattr("sys.argv", ["main.py"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            "main.py",
            run_name="__main__",
            init_globals={
                "RUN_AI_RESEARCH": True,
                "RESEARCH_AI_PROVIDER": "openai",
                "MODE": "Freelance_English",
                "RESEARCH_MODEL": "custom-model",
                "RESEARCH_MIN_COMPANIES": 2,
                "RESEARCH_MAX_COMPANIES": 4,
                "RESEARCH_PERSON_EMAILS_PER_COMPANY": 1,
                "RESEARCH_WRITE_OUTPUT": False,
                "RESEARCH_UPLOAD_ATTACHMENTS": False,
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
                "--model",
                "custom-model",
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
        )
    ]


def test_main_wrapper_defaults_to_research(monkeypatch) -> None:
    calls = []

    def fake_research_main(args):
        calls.append(("research", args))
        return 0

    def fake_mail_main(args=None):
        calls.append(("mail", args))
        return 0

    monkeypatch.setattr("Research.research_leads.main", fake_research_main)
    monkeypatch.setattr("mail_sender.cli.main", fake_mail_main)
    monkeypatch.setattr("sys.argv", ["main.py"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path("main.py", run_name="__main__")

    assert exc_info.value.code == 0
    assert calls[0][0] == "research"
    assert "--mode" in calls[0][1]


def test_main_wrapper_forwards_explicit_cli_args_to_mail(monkeypatch) -> None:
    calls = []

    def fake_mail_main(args=None):
        calls.append(args)
        return 0

    monkeypatch.setattr("mail_sender.cli.main", fake_mail_main)
    monkeypatch.setattr("sys.argv", ["main.py", "--mode", "PhD"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path("main.py", run_name="__main__")

    assert exc_info.value.code == 0
    assert calls == [None]
