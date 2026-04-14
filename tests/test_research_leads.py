from __future__ import annotations

import csv
import sys
import types as py_types
from pathlib import Path

import pytest

from research import research_leads
from research.research_leads import ResearchConfig
from mail_sender.recipients import Recipient
from mail_sender.sent_log import append_log


def config(
    project: Path,
    mode: str = "PhD",
    write_output: bool = True,
    verbose: bool = False,
    upload_attachments: bool = True,
    provider: str = "gemini",
    model: str = "gemini-2.5-flash-lite",
) -> ResearchConfig:
    return ResearchConfig(
        provider=provider,
        mode_name=mode,
        model=model,
        min_companies=1,
        max_companies=3,
        person_emails_per_company=2,
        base_dir=project,
        write_output=write_output,
        verbose=verbose,
        upload_attachments=upload_attachments,
    )


def test_default_config_and_parse_args(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    for key in [
        "RESEARCH_AI_PROVIDER",
        "RESEARCH_MODE",
        "RESEARCH_MODEL",
        "GEMINI_MODEL",
        "OPENAI_MODEL",
        "RESEARCH_MIN_COMPANIES",
        "RESEARCH_MAX_COMPANIES",
        "RESEARCH_PERSON_EMAILS_PER_COMPANY",
        "RESEARCH_WRITE_OUTPUT",
        "RESEARCH_UPLOAD_ATTACHMENTS",
        "RESEARCH_VERBOSE",
        "RESEARCH_BASE_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)

    default = research_leads.default_config()
    assert default.mode_name == "PhD"
    assert default.provider == "gemini"
    assert default.model == "gemini-2.5-flash-lite"

    parsed = research_leads.parse_args([
        "--provider",
        "openai",
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
        "--no-upload-attachments",
        "--verbose",
    ])

    assert parsed.mode_name == "Freelance_English"
    assert parsed.provider == "openai"
    assert parsed.base_dir == project
    assert parsed.min_companies == 2
    assert parsed.max_companies == 4
    assert parsed.person_emails_per_company == 1
    assert parsed.model == "test-model"
    assert parsed.write_output is False
    assert parsed.verbose is True
    assert parsed.upload_attachments is False


def test_default_config_reads_env(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    monkeypatch.setenv("RESEARCH_AI_PROVIDER", "openai")
    monkeypatch.setenv("RESEARCH_MODE", "Freelance_German")
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("RESEARCH_MIN_COMPANIES", "2")
    monkeypatch.setenv("RESEARCH_MAX_COMPANIES", "7")
    monkeypatch.setenv("RESEARCH_PERSON_EMAILS_PER_COMPANY", "1")
    monkeypatch.setenv("RESEARCH_WRITE_OUTPUT", "false")
    monkeypatch.setenv("RESEARCH_UPLOAD_ATTACHMENTS", "false")
    monkeypatch.setenv("RESEARCH_VERBOSE", "true")
    monkeypatch.setenv("RESEARCH_BASE_DIR", str(project))

    cfg = research_leads.default_config()

    assert cfg.provider == "openai"
    assert cfg.mode_name == "Freelance_German"
    assert cfg.model == "gpt-test"
    assert cfg.min_companies == 2
    assert cfg.max_companies == 7
    assert cfg.person_emails_per_company == 1
    assert cfg.write_output is False
    assert cfg.verbose is True
    assert cfg.upload_attachments is False
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

    recipients = research_leads.parse_recipients(raw, {"existing@example.com"})

    assert recipients == [
        Recipient(email="a@example.com", company="A"),
        Recipient(email="other@example.com", company="A"),
        Recipient(email="c@example.com", company="C"),
        Recipient(email="d@example.com", company="D"),
    ]


def test_parse_recipients_no_longer_requires_headers() -> None:
    # Previously it required headers, now it should handle headerless data if it looks like company,email
    assert research_leads.parse_recipients("A,a@example.com", set()) == [
        Recipient(email="a@example.com", company="A")
    ]
    assert research_leads.parse_recipients("", set()) == []
    assert research_leads._detect_dialect("") == csv.excel


def test_parse_recipients_handles_gemini_dump_and_company_commas() -> None:
    raw = (
        "'com.au\\n"
        "AI Engineers, Inc.,info@aiengineers.com\\n"
        "PwC,info@pwc.com\\n"
        "PwC,info@pwc.com\\n"
        "Agix Technologies,info@agix.'"
    )

    recipients = research_leads.parse_recipients(raw, set())

    assert recipients == [
        Recipient(email="info@aiengineers.com", company="AI Engineers, Inc."),
        Recipient(email="info@pwc.com", company="PwC"),
    ]


def test_parse_recipients_from_example_raw() -> None:
    # This test verifies that parse_recipients can handle the full example.raw file
    # and extract the expected data correctly.
    raw_path = Path("example.raw")
    if not raw_path.exists():
        pytest.skip("example.raw not found in project root")
    
    raw_content = raw_path.read_text(encoding="utf-8")
    recipients = research_leads.parse_recipients(raw_content, set())
    
    # Check for some specific known entries from example.raw
    emails = {r.email for r in recipients}
    companies = {r.company for r in recipients}
    
    # Total unique recipients should be around 168 (based on previous manual run)
    assert len(recipients) >= 150
    
    # Check for "Protiviti" cases which were tricky
    assert "info@protiviti.com.au" in emails
    # Check for some complex names
    assert any("Protiviti" in r.company for r in recipients)
    assert any("Data61" in r.company for r in recipients)
    
    # Check for McKinsey
    assert "McKinsey & Company" in companies
    assert "contact.au@mckinsey.com" in emails

    # Check for some special names
    assert "CSIRO's Data61" in companies
    assert "info@data61.csiro.au" in emails


def test_write_recipients_csv(project: Path) -> None:
    path = research_leads.write_recipients_csv(
        project / "input/PhD",
        "PhD",
        [Recipient(email="a@example.com", company="A")],
    )

    assert path.name.startswith("research_phd_")
    assert path.read_text(encoding="utf-8").splitlines() == ["company,mail", "A,a@example.com"]


def test_run_research_writes_output(monkeypatch: pytest.MonkeyPatch, project: Path, capsys) -> None:
    (project / "attachments/PhD/context.pdf").write_text("context", encoding="utf-8")

    def fake_generate(model: str, prompt: str, attachments: list[Path], verbose: bool = False) -> str:
        assert model == "gemini-2.5-flash-lite"
        assert attachments == [project / "attachments/PhD/context.pdf"]
        assert "Existing email exclusion list" in prompt
        assert "Mode-specific input CSV/TXT context" in prompt
        assert verbose is True
        return "company,mail\nA,a@example.com\n"

    monkeypatch.setattr(research_leads, "generate_with_gemini", fake_generate)

    output_path, recipients = research_leads.run_research(config(project, verbose=True))

    assert output_path is not None
    assert output_path.exists()
    assert recipients == [Recipient(email="a@example.com", company="A")]
    assert "[VERBOSE] AI prompt characters:" in capsys.readouterr().out


def test_run_research_can_skip_output_and_validates(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    monkeypatch.setattr(
        research_leads,
        "generate_with_gemini",
        lambda model, prompt, attachments, verbose=False: "company,mail\nA,a@example.com\n",
    )

    output_path, recipients = research_leads.run_research(config(project, write_output=False))
    assert output_path is None
    assert recipients == [Recipient(email="a@example.com", company="A")]

    bad_config = ResearchConfig("gemini", "PhD", "model", 2, 1, 1, project, True, False, True)
    with pytest.raises(ValueError, match="Company limits"):
        research_leads.run_research(bad_config)

    monkeypatch.setattr(
        research_leads,
        "generate_with_gemini",
        lambda model, prompt, attachments, verbose=False: "company,mail\n",
    )
    with pytest.raises(RuntimeError, match="no new usable"):
        research_leads.run_research(config(project))


def test_run_research_can_skip_attachment_upload(monkeypatch: pytest.MonkeyPatch, project: Path, capsys) -> None:
    (project / "attachments/PhD/context.pdf").write_text("context", encoding="utf-8")

    def fake_generate(model: str, prompt: str, attachments: list[Path], verbose: bool = False) -> str:
        assert attachments == []
        assert verbose is True
        return "company,mail\nA,a@example.com\n"

    monkeypatch.setattr(research_leads, "generate_with_gemini", fake_generate)

    _, recipients = research_leads.run_research(config(project, verbose=True, upload_attachments=False))

    assert recipients == [Recipient(email="a@example.com", company="A")]
    assert "Attachment upload disabled" in capsys.readouterr().out


def test_run_research_retries_without_attachments_after_empty_response(
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    capsys,
) -> None:
    attachment = project / "attachments/PhD/context.pdf"
    attachment.write_text("context", encoding="utf-8")
    calls = []

    def fake_generate(model: str, prompt: str, attachments: list[Path], verbose: bool = False) -> str:
        calls.append(attachments)
        if attachments:
            return ""
        return "company,mail\nA,a@example.com\n"

    monkeypatch.setattr(research_leads, "generate_with_gemini", fake_generate)

    _, recipients = research_leads.run_research(config(project, verbose=True))

    assert calls == [[attachment], []]
    assert recipients == [Recipient(email="a@example.com", company="A")]
    assert "retrying once without attachment uploads" in capsys.readouterr().out


def test_run_research_retries_with_lite_prompt_after_model_error(
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    capsys,
) -> None:
    calls = []

    def fake_generate(model: str, prompt: str, attachments: list[Path], verbose: bool = False) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "I'm sorry, but I encountered an error that prevented me from fulfilling your request. Please try again."
        assert "Existing email exclusion list:\n(none)" in prompt
        return "company,mail\nA,a@example.com\n"

    monkeypatch.setattr(research_leads, "generate_with_gemini", fake_generate)

    _, recipients = research_leads.run_research(config(project, verbose=True))

    assert len(calls) == 2
    assert recipients == [Recipient(email="a@example.com", company="A")]
    output = capsys.readouterr().out
    assert "retrying once with a smaller prompt" in output
    assert "Lite AI prompt characters:" in output


def test_needs_retry_handles_invalid_csv() -> None:
    assert research_leads._needs_retry("not,csv\nonly-one-value\n", set()) is True


def test_model_for_provider_prefers_generic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_MODEL", "generic-model")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")

    assert research_leads._model_for_provider("openai") == "generic-model"


def test_generate_with_provider_selects_openai_and_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        research_leads,
        "generate_with_openai",
        lambda model, prompt, attachments, verbose=False: "company,mail\nA,a@example.com\n",
    )

    assert research_leads.generate_with_provider("openai", "gpt-5.4", "prompt", [], True) == (
        "company,mail\nA,a@example.com\n"
    )

    with pytest.raises(ValueError, match="Unknown research provider"):
        research_leads.generate_with_provider("other", "model", "prompt", [], False)


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


def test_generate_with_openai_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        research_leads.generate_with_openai("model", "prompt", [])


def test_generate_with_openai_uses_web_search_and_uploaded_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    attachment = tmp_path / "context.pdf"
    attachment.write_text("context", encoding="utf-8")

    class FakeFiles:
        def create(self, file, purpose: str):
            assert file.read() == b"context"
            assert purpose == "user_data"
            return py_types.SimpleNamespace(id="file_123")

    class FakeResponses:
        def create(self, model, input, tools):
            assert model == "gpt-5.4"
            assert input == [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "prompt"},
                        {"type": "input_file", "file_id": "file_123"},
                    ],
                }
            ]
            assert tools == [{"type": "web_search"}]
            output_item = py_types.SimpleNamespace(type="message", status="completed", content=[])
            return py_types.SimpleNamespace(output_text="company,mail\nA,a@example.com\n", output=[output_item])

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.files = FakeFiles()
            self.responses = FakeResponses()

    fake_openai = py_types.ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    assert research_leads.generate_with_openai("gpt-5.4", "prompt", [attachment], True) == (
        "company,mail\nA,a@example.com\n"
    )
    output = capsys.readouterr().out
    assert "Calling OpenAI Responses API with web_search enabled." in output
    assert "OpenAI output items: 1" in output


def test_generate_with_openai_reads_output_content_when_output_text_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)

    class FakeFiles:
        def create(self, file, purpose: str):
            return py_types.SimpleNamespace(id="file_123")

    class FakeResponses:
        def create(self, model, input, tools):
            content = [py_types.SimpleNamespace(text="company,mail\nA,a@example.com\n")]
            output = [py_types.SimpleNamespace(type="message", status="completed", content=content)]
            return py_types.SimpleNamespace(output_text="", output=output)

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.files = FakeFiles()
            self.responses = FakeResponses()

    fake_openai = py_types.ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    assert research_leads.generate_with_openai("gpt-5.4", "prompt", [], False) == (
        "company,mail\nA,a@example.com\n"
    )


def test_verbose_openai_output_handles_disabled_and_empty(capsys) -> None:
    research_leads._verbose_openai_output(False, py_types.SimpleNamespace(output=[]))
    assert capsys.readouterr().out == ""

    research_leads._verbose_openai_output(True, py_types.SimpleNamespace(output=[]))
    assert "OpenAI output items: none" in capsys.readouterr().out


def test_generate_with_gemini_uses_google_search_and_uploaded_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
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

    assert research_leads.generate_with_gemini("gemini-2.5-flash-lite", "prompt", [attachment], True) == '{"leads": []}'
    output = capsys.readouterr().out
    assert 'Gemini response.text raw: \'{"leads": []}\'' in output
    assert "Gemini candidates: none" in output


def test_generate_with_gemini_logs_empty_candidate_metadata(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)

    class FakeFiles:
        def upload(self, file: Path):
            return object()

    class FakeModels:
        def generate_content(self, model, contents, config):
            part = py_types.SimpleNamespace(text=None)
            content = py_types.SimpleNamespace(parts=[part])
            candidate = py_types.SimpleNamespace(
                finish_reason="SAFETY",
                safety_ratings=["blocked"],
                content=content,
            )
            return py_types.SimpleNamespace(text="", candidates=[candidate], prompt_feedback="ok")

    class FakeClient:
        def __init__(self, api_key: str) -> None:
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

    assert research_leads.generate_with_gemini("gemini-2.5-flash-lite", "prompt", [], True) == ""
    output = capsys.readouterr().out
    assert "Gemini response.text raw: ''" in output
    assert "Gemini prompt_feedback: 'ok'" in output
    assert "Gemini candidates: 1" in output
    assert "Gemini candidate 1 finish_reason: 'SAFETY'" in output
    assert "Gemini candidate 1 safety_ratings: ['blocked']" in output


def test_generate_with_gemini_reads_candidate_part_text_when_response_text_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)

    class FakeFiles:
        def upload(self, file: Path):
            return object()

    class FakeModels:
        def generate_content(self, model, contents, config):
            part = py_types.SimpleNamespace(text="company,mail\nA,a@example.com\n")
            content = py_types.SimpleNamespace(parts=[part])
            candidate = py_types.SimpleNamespace(
                finish_reason="STOP",
                safety_ratings=None,
                content=content,
            )
            return py_types.SimpleNamespace(text="", candidates=[candidate])

    class FakeClient:
        def __init__(self, api_key: str) -> None:
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

    assert research_leads.generate_with_gemini("gemini-2.5-flash-lite", "prompt", [], False) == (
        "company,mail\nA,a@example.com\n"
    )


def test_verbose_gemini_candidates_handles_disabled_and_missing_parts(capsys) -> None:
    response = py_types.SimpleNamespace(
        candidates=[
            py_types.SimpleNamespace(
                finish_reason="STOP",
                safety_ratings=[],
                content=py_types.SimpleNamespace(parts=[]),
            )
        ]
    )

    research_leads._verbose_gemini_candidates(False, response)
    assert capsys.readouterr().out == ""

    research_leads._verbose_gemini_candidates(True, response)
    assert "Gemini candidate 1 content parts: none" in capsys.readouterr().out
