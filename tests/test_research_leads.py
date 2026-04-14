from __future__ import annotations

import csv
import sys
import types as py_types
from pathlib import Path

import pytest

from Research import research_leads
from Research.research_leads import ResearchConfig
from mail_sender.recipients import Recipient
from mail_sender.sent_log import append_log


def config(project: Path, mode: str = "PhD", write_output: bool = True) -> ResearchConfig:
    return ResearchConfig(
        mode_name=mode,
        model="gemini-2.5-flash-lite",
        min_companies=1,
        max_companies=3,
        person_emails_per_company=2,
        base_dir=project,
        write_output=write_output,
    )


def test_default_config_and_parse_args(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    for key in [
        "RESEARCH_MODE",
        "GEMINI_MODEL",
        "RESEARCH_MIN_COMPANIES",
        "RESEARCH_MAX_COMPANIES",
        "RESEARCH_PERSON_EMAILS_PER_COMPANY",
        "RESEARCH_WRITE_OUTPUT",
        "RESEARCH_BASE_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)

    default = research_leads.default_config()
    assert default.mode_name == "PhD"
    assert default.model == "gemini-2.5-flash-lite"

    parsed = research_leads.parse_args([
        "--mode",
        "Freelance_English",
        "--base-dir",
        str(project),
        "--min-companies",
        "2",
        "--max-companies",
        "4",
        "--person-emails-per-company",
        "1",
        "--model",
        "test-model",
        "--no-write-output",
    ])

    assert parsed.mode_name == "Freelance_English"
    assert parsed.base_dir == project
    assert parsed.min_companies == 2
    assert parsed.max_companies == 4
    assert parsed.person_emails_per_company == 1
    assert parsed.model == "test-model"
    assert parsed.write_output is False


def test_default_config_reads_env(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    monkeypatch.setenv("RESEARCH_MODE", "Freelance_German")
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    monkeypatch.setenv("RESEARCH_MIN_COMPANIES", "2")
    monkeypatch.setenv("RESEARCH_MAX_COMPANIES", "7")
    monkeypatch.setenv("RESEARCH_PERSON_EMAILS_PER_COMPANY", "1")
    monkeypatch.setenv("RESEARCH_WRITE_OUTPUT", "false")
    monkeypatch.setenv("RESEARCH_BASE_DIR", str(project))

    cfg = research_leads.default_config()

    assert cfg.mode_name == "Freelance_German"
    assert cfg.model == "custom-model"
    assert cfg.min_companies == 2
    assert cfg.max_companies == 7
    assert cfg.person_emails_per_company == 1
    assert cfg.write_output is False
    assert cfg.base_dir == project


def test_collect_existing_emails_reads_output_and_input(project: Path) -> None:
    append_log(project / "output/send_phd.xlsx", Recipient(email="logged@example.com", company="Logged"))
    (project / "input/Freelance_German/existing.csv").write_text(
        "company,mail\nInput,mailto:input@example.com\n",
        encoding="utf-8",
    )

    assert research_leads.collect_existing_emails(project) == {"logged@example.com", "input@example.com"}


def test_build_prompt_uses_mode_specific_instructions(project: Path) -> None:
    phd_prompt = research_leads.build_prompt(
        config(project),
        research_leads.get_mode("PhD", project),
        {"old@example.com"},
        "company,mail\nExample GmbH,example@example.com",
    )
    german_prompt = research_leads.build_prompt(
        config(project, mode="Freelance_German"),
        research_leads.get_mode("Freelance_German", project),
        set(),
    )
    english_prompt = research_leads.build_prompt(
        config(project, mode="Freelance_English"),
        research_leads.get_mode("Freelance_English", project),
        set(),
    )

    assert "Industry PhD" in phd_prompt
    assert "old@example.com" in phd_prompt
    assert "company,mail" in phd_prompt
    assert "Example GmbH" in phd_prompt
    assert "AVGS" in german_prompt
    assert "Luxembourg" in english_prompt


def test_read_input_context_reads_mode_files_and_truncates(project: Path) -> None:
    (project / "input/PhD/example.csv").write_text("company,mail\nA,a@example.com\n", encoding="utf-8")
    (project / "input/PhD/notes.txt").write_text("lead style note", encoding="utf-8")

    context = research_leads.read_input_context(project / "input/PhD", max_chars=45)

    assert "example.csv" in context
    assert "company,mail" in context
    assert context.endswith("...[truncated]")


def test_read_input_context_replaces_invalid_bytes(project: Path) -> None:
    (project / "input/PhD/broken.csv").write_bytes(b"\xffcompany,mail\nA,a@example.com\n")

    context = research_leads.read_input_context(project / "input/PhD")

    assert "broken.csv" in context
    assert "company,mail" in context


def test_parse_recipients_filters_duplicates_existing_bad_email_and_company_limit() -> None:
    raw = """
```csv
company,mail
A,mailto:a@example.com
A,bad
A,other@example.com
B,existing@example.com
,missing-company@example.com
Missing Email,
C,c@example.com
D,d@example.com
```
"""

    recipients = research_leads.parse_recipients(raw, {"existing@example.com"}, max_companies=2)

    assert recipients == [
        Recipient(email="a@example.com", company="A"),
        Recipient(email="other@example.com", company="A"),
        Recipient(email="c@example.com", company="C"),
    ]


def test_parse_recipients_requires_company_and_mail_columns() -> None:
    with pytest.raises(ValueError, match="company and mail"):
        research_leads.parse_recipients("name,address\nA,a@example.com", set(), max_companies=1)

    assert research_leads.parse_recipients("", set(), max_companies=1) == []
    assert research_leads._detect_dialect("") == csv.excel


def test_write_recipients_csv(project: Path) -> None:
    path = research_leads.write_recipients_csv(
        project / "input/PhD",
        "PhD",
        [Recipient(email="a@example.com", company="A")],
    )

    assert path.name.startswith("research_phd_")
    assert path.read_text(encoding="utf-8").splitlines() == ["company,mail", "A,a@example.com"]


def test_run_research_writes_output(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    (project / "attachments/PhD/context.pdf").write_text("context", encoding="utf-8")

    def fake_generate(model: str, prompt: str, attachments: list[Path]) -> str:
        assert model == "gemini-2.5-flash-lite"
        assert attachments == [project / "attachments/PhD/context.pdf"]
        assert "Existing email exclusion list" in prompt
        assert "Mode-specific input CSV/TXT context" in prompt
        return "company,mail\nA,a@example.com\n"

    monkeypatch.setattr(research_leads, "generate_with_gemini", fake_generate)

    output_path, recipients = research_leads.run_research(config(project))

    assert output_path is not None
    assert output_path.exists()
    assert recipients == [Recipient(email="a@example.com", company="A")]


def test_run_research_can_skip_output_and_validates(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    (project / "attachments/PhD/context.pdf").write_text("context", encoding="utf-8")
    monkeypatch.setattr(
        research_leads,
        "generate_with_gemini",
        lambda model, prompt, attachments: "company,mail\nA,a@example.com\n",
    )

    output_path, recipients = research_leads.run_research(config(project, write_output=False))
    assert output_path is None
    assert recipients == [Recipient(email="a@example.com", company="A")]

    bad_config = ResearchConfig("PhD", "model", 2, 1, 1, project, True)
    with pytest.raises(ValueError, match="Company limits"):
        research_leads.run_research(bad_config)

    monkeypatch.setattr(research_leads, "generate_with_gemini", lambda model, prompt, attachments: "company,mail\n")
    with pytest.raises(RuntimeError, match="no new usable"):
        research_leads.run_research(config(project))


def test_main_success_and_error(monkeypatch: pytest.MonkeyPatch, project: Path, capsys) -> None:
    monkeypatch.setattr(
        research_leads,
        "run_research",
        lambda cfg: (project / "input/PhD/research.csv", [Recipient(email="a@example.com", company="A")]),
    )
    result = research_leads.main(["--mode", "PhD", "--base-dir", str(project)])
    assert result == 0
    assert "New recipients: 1" in capsys.readouterr().out

    def broken_run(cfg):
        raise RuntimeError("boom")

    monkeypatch.setattr(research_leads, "run_research", broken_run)
    result = research_leads.main(["--mode", "PhD", "--base-dir", str(project)])
    assert result == 1
    assert "Error: boom" in capsys.readouterr().out


def test_generate_with_gemini_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        research_leads.generate_with_gemini("model", "prompt", [])


def test_generate_with_gemini_uses_google_search_and_uploaded_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    uploaded = object()
    attachment = tmp_path / "context.pdf"
    attachment.write_text("context", encoding="utf-8")

    class FakeFiles:
        def upload(self, file: Path):
            assert file == attachment
            return uploaded

    class FakeModels:
        def generate_content(self, model, contents, config):
            assert model == "gemini-2.5-flash-lite"
            assert contents == ["prompt", uploaded]
            assert config.temperature == 0.2
            return py_types.SimpleNamespace(text='{"leads": []}')

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.files = FakeFiles()
            self.models = FakeModels()

    fake_types = py_types.SimpleNamespace(
        GenerateContentConfig=lambda tools, temperature: py_types.SimpleNamespace(tools=tools, temperature=temperature),
        Tool=lambda google_search: py_types.SimpleNamespace(google_search=google_search),
        GoogleSearch=lambda: py_types.SimpleNamespace(name="google_search"),
    )
    fake_google = py_types.ModuleType("google")
    fake_genai = py_types.ModuleType("google.genai")
    fake_genai.Client = FakeClient
    fake_genai.types = fake_types
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setenv("GEMINI_API_KEY", "key")

    assert research_leads.generate_with_gemini("gemini-2.5-flash-lite", "prompt", [attachment]) == '{"leads": []}'
