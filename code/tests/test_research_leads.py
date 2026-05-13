"""Tests and helpers for tests/test_research_leads.py."""

from __future__ import annotations

import csv
import json
import runpy
import sys
import threading
import types as py_types
from pathlib import Path
from typing import Any

import pytest

from mail_sender.recipients import Recipient
from mail_sender.sent_log import append_log
from research import providers
from research import logging_utils
from research import research_leads
from research import self_research
from research.research_leads import ResearchConfig


def setup_fake_genai(monkeypatch: pytest.MonkeyPatch, fake_client_class: type) -> None:
    """Configures the fake modules for google.genai."""
    fake_types = py_types.SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: py_types.SimpleNamespace(**kwargs),
        Tool=lambda google_search: py_types.SimpleNamespace(google_search=google_search),
        GoogleSearch=lambda: py_types.SimpleNamespace(name="google_search"),
        ToolConfig=lambda **kwargs: py_types.SimpleNamespace(**kwargs),
        FunctionCallingConfig=lambda **kwargs: py_types.SimpleNamespace(**kwargs),
        FunctionCallingConfigMode=py_types.SimpleNamespace(AUTO="AUTO"),
        ThinkingConfig=lambda **kwargs: py_types.SimpleNamespace(**kwargs),
        ThinkingLevel=py_types.SimpleNamespace(
            BRIEF=py_types.SimpleNamespace(name="BRIEF"),
            MEDIUM=py_types.SimpleNamespace(name="MEDIUM"),
            FULL=py_types.SimpleNamespace(name="FULL")
        ),
    )
    fake_google = py_types.ModuleType("google")
    fake_genai = py_types.ModuleType("google.genai")
    fake_genai.Client = fake_client_class
    fake_genai.types = fake_types
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setenv("GEMINI_API_KEY", "key")


CODE_DIR = Path(__file__).resolve().parents[1]


def config(
        project: Path,
        mode: str = "PhD",
        write_output: bool = True,
        verbose: bool = False,
        upload_attachments: bool = True,
        research_context_delivery: str = "upload_files",
        provider: str = "gemini",
        model: str = "gemini-2.5-flash-lite",
        gemini_model: str = "gemini-2.5-flash-lite",
        openai_model: str = "gpt-5.4",
        ollama_model: str = "llama3.1:8b",
        max_companies: int = 3,
        reasoning_effort: str = "middle",
        send_target_count: int = 0,
        max_iterations: int = 5,
        parallel_threads: int = 1,
        self_search_keywords: tuple[str, ...] = ("query",),
        self_crawl_depth: int = 2,
        external_validation_service: str = "none",
        external_validation_api_key: str = "",
        external_validation_stage: str = "research",
) -> ResearchConfig:
    """Encapsulates the helper step config."""
    return ResearchConfig(
        provider=provider,
        mode_name=mode,
        model=model,
        min_companies=1,
        max_companies=max_companies,
        person_emails_per_company=2,
        base_dir=project,
        write_output=write_output,
        verbose=verbose,
        upload_attachments=upload_attachments,
        gemini_model=gemini_model,
        openai_model=openai_model,
        ollama_model=ollama_model,
        research_context_delivery=research_context_delivery,
        reasoning_effort=reasoning_effort,
        send_target_count=send_target_count,
        max_iterations=max_iterations,
        parallel_threads=parallel_threads,
        self_search_keywords=self_search_keywords,
        self_crawl_depth=self_crawl_depth,
        external_validation_service=external_validation_service,
        external_validation_api_key=external_validation_api_key,
        external_validation_stage=external_validation_stage,
    )


def test_default_config_and_parse_args(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Checks behavior for default config and parse args."""
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    monkeypatch.setattr(research_leads, "_load_settings", lambda: {})
    for key in [
        "RESEARCH_AI_PROVIDER",
        "RESEARCH_MODE",
        "GEMINI_MODEL",
        "OPENAI_MODEL",
        "OLLAMA_MODEL",
        "RESEARCH_MIN_COMPANIES",
        "RESEARCH_MAX_COMPANIES",
        "RESEARCH_PERSON_EMAILS_PER_COMPANY",
        "RESEARCH_WRITE_OUTPUT",
        "RESEARCH_UPLOAD_ATTACHMENTS",
        "RESEARCH_CONTEXT_DELIVERY",
        "EXTERNAL_VALIDATION_SERVICE",
        "EXTERNAL_VALIDATION_STAGE",
        "NEVERBOUNCE_API_KEY",
        "RESEARCH_VERBOSE",
        "RESEARCH_BASE_DIR",
        "SELF_SEARCH_KEYWORDS",
    ]:
        monkeypatch.delenv(key, raising=False)

    default = research_leads.default_config()
    assert default.mode_name == "PhD"
    assert default.provider == "gemini"
    assert default.model == "gemini-3-flash-preview"
    assert default.external_validation_stage == "research"

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
        "--no-write-output",
        "--no-upload-attachments",
        "--research-context-delivery",
        "paste_in_prompt",
        "--external-validation-service",
        "neverbounce",
        "--external-validation-api-key",
        "never-key",
        "--external-validation-stage",
        "send",
        "--send-target-count",
        "100",
        "--max-iterations",
        "10",
        "--reasoning-effort",
        "high",
        "--verbose",
    ])

    assert parsed.mode_name == "Freelance_English"
    assert parsed.provider == "openai"
    assert parsed.base_dir == project
    assert parsed.min_companies == 2
    assert parsed.max_companies == 4
    assert parsed.person_emails_per_company == 1
    assert parsed.model == "gpt-5.4-mini-2026-03-17"
    assert parsed.ollama_model == "llama3.1:8b"
    assert parsed.write_output is False
    assert parsed.verbose is True
    assert parsed.upload_attachments is False
    assert parsed.research_context_delivery == "paste_in_prompt"
    assert parsed.external_validation_service == "neverbounce"
    assert parsed.external_validation_api_key == "never-key"
    assert parsed.external_validation_stage == "send"
    assert parsed.reasoning_effort == "high"
    assert parsed.send_target_count == 100
    assert parsed.max_iterations == 10
    assert parsed.parallel_threads == 3


def test_default_config_reads_env(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Checks behavior for default config reads env."""
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    monkeypatch.setattr(research_leads, "_load_settings", lambda: {})
    monkeypatch.setenv("RESEARCH_AI_PROVIDER", "openai")
    monkeypatch.setenv("RESEARCH_MODE", "Freelance_German")
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("RESEARCH_MIN_COMPANIES", "2")
    monkeypatch.setenv("RESEARCH_MAX_COMPANIES", "7")
    monkeypatch.setenv("RESEARCH_PERSON_EMAILS_PER_COMPANY", "1")
    monkeypatch.setenv("RESEARCH_WRITE_OUTPUT", "false")
    monkeypatch.setenv("RESEARCH_UPLOAD_ATTACHMENTS", "false")
    monkeypatch.setenv("RESEARCH_CONTEXT_DELIVERY", "paste_in_prompt")
    monkeypatch.setenv("EXTERNAL_VALIDATION_SERVICE", "neverbounce")
    monkeypatch.setenv("EXTERNAL_VALIDATION_STAGE", "send")
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "never-key")
    monkeypatch.setenv("RESEARCH_VERBOSE", "true")
    monkeypatch.setenv("RESEARCH_REASONING_EFFORT", "high")
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
    assert cfg.research_context_delivery == "paste_in_prompt"
    assert cfg.external_validation_service == "neverbounce"
    assert cfg.external_validation_api_key == "never-key"
    assert cfg.external_validation_stage == "send"
    assert cfg.reasoning_effort == "high"
    assert cfg.base_dir == project


def test_research_model_infers_provider_and_accepts_custom_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks that the single research model value controls provider selection."""
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    monkeypatch.delenv("RESEARCH_MODEL", raising=False)
    monkeypatch.setattr(
        research_leads,
        "_load_settings",
        lambda: {"RESEARCH_MODEL": "ollama:qwen2.5:7b", "MODE": "PhD"},
    )

    cfg = research_leads.default_config()

    assert cfg.provider == "ollama"
    assert cfg.model == "qwen2.5:7b"
    assert cfg.ollama_model == "qwen2.5:7b"
    assert research_leads._provider_and_model_from_research_model("gemini-3-custom") == ("gemini", "gemini-3-custom")
    assert research_leads._provider_and_model_from_research_model("gpt-custom") == ("openai", "gpt-custom")
    assert research_leads._provider_and_model_from_research_model("self") == ("self", "self")


def test_default_config_ignores_empty_base_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checks behavior for default config ignores empty base dir env."""
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    monkeypatch.setenv("RESEARCH_BASE_DIR", "")

    expected_base = Path(str(research_leads.__file__)).resolve().parents[2]
    assert research_leads.default_config().base_dir == expected_base.resolve()


def test_collect_existing_emails_reads_output_and_input(project: Path) -> None:
    """Checks behavior for collect existing emails reads output and input."""
    append_log(project / "output/send_phd.csv", Recipient(email="logged@example.com", company="Logged"))
    (project / "input/Freelance_German/existing.csv").write_text(
        "company,mail\nInput,mailto:input@example.com\n",
        encoding="utf-8",
    )

    assert research_leads.collect_existing_emails(project) == {"logged@example.com", "input@example.com"}


def test_collect_mode_existing_companies_reads_mode_log_and_input(project: Path) -> None:
    """Checks behavior for collect mode existing companies reads mode log and input."""
    mode = research_leads.get_mode("PhD", project)
    append_log(project / "output/send_phd.csv", Recipient(email="old@example.com", company="Old Company GmbH"))
    (project / "input/PhD/existing.csv").write_text(
        "company,mail\nInput Company,input@example.com\n",
        encoding="utf-8",
    )

    assert research_leads.collect_mode_existing_companies(mode) == {"oldcompanygmbh", "inputcompany"}


def test_build_prompt_uses_mode_specific_instructions(project: Path) -> None:
    """Checks behavior for build prompt uses mode specific instructions."""
    phd_prompt = research_leads.build_prompt(
        config(project),
        research_leads.get_mode("PhD", project),
        {"old@example.com"},
        {"oldcompany"},
        "company,mail,source_url\nExample GmbH,example@example.com,https://example.com/contact",
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
    assert "oldcompany" in phd_prompt
    assert "uploaded sent-log file" in phd_prompt
    assert "company,mail,source_url" in phd_prompt
    assert "Example GmbH" in phd_prompt
    assert "AVGS" in german_prompt
    assert "Online-only" in german_prompt
    assert "Australien" in german_prompt
    assert "offiziellen Anbieter-Website" in german_prompt
    assert "nicht valide markierte E-Mails" in german_prompt
    assert "remote freelance lecturer" in english_prompt
    assert "online-only provider gate" in english_prompt
    assert "Germany, Australia, Switzerland, Austria, Luxembourg" in english_prompt
    assert "official provider website" in english_prompt
    assert "invalid_mails.csv" in english_prompt


def test_build_prompt_accepts_legacy_input_context_position(project: Path) -> None:
    """Checks behavior for build prompt accepts legacy input context position."""
    prompt = research_leads.build_prompt(
        config(project),
        research_leads.get_mode("PhD", project),
        set(),
        None,
        "legacy context",
    )

    assert "legacy context" in prompt


def test_read_input_context_reads_mode_files_and_truncates(project: Path) -> None:
    """Checks behavior for read input context reads mode files and truncates."""
    (project / "input/PhD/example.csv").write_text("company,mail\nA,a@example.com\n", encoding="utf-8")
    (project / "input/PhD/notes.txt").write_text("lead style note", encoding="utf-8")

    context = research_leads.read_input_context(project / "input/PhD", max_chars=45)

    assert "example.csv" in context
    assert "company,mail" in context
    assert context.endswith("...[truncated]")


def test_read_input_context_replaces_invalid_bytes(project: Path) -> None:
    """Checks behavior for read input context replaces invalid bytes."""
    (project / "input/PhD/broken.csv").write_bytes(b"\xffcompany,mail\nA,a@example.com\n")

    context = research_leads.read_input_context(project / "input/PhD")

    assert "broken.csv" in context
    assert "company,mail" in context


def test_list_resume_attachments_only_returns_cv_resume_files(project: Path) -> None:
    """Checks behavior for list resume attachments only returns cv resume files."""
    attachment_dir = project / "attachments/Freelance_German"
    cv = attachment_dir / "Lebenslauf Carina Sophie Schoppe.pdf"
    cert = attachment_dir / "Master Certificate.pdf"
    nested_resume = attachment_dir / "nested" / "Resume_2026.pdf"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    (attachment_dir / "nested").mkdir()
    cv.write_text("cv", encoding="utf-8")
    cert.write_text("cert", encoding="utf-8")
    nested_resume.write_text("resume", encoding="utf-8")

    assert research_leads.list_resume_attachments(attachment_dir) == [cv, nested_resume]


def test_list_research_context_files_adds_matching_sent_log(project: Path) -> None:
    """Checks behavior for list research context files adds matching sent log."""
    cv = project / "attachments/PhD/CV.pdf"
    other = project / "attachments/PhD/certificate.pdf"
    cv.write_text("cv", encoding="utf-8")
    other.write_text("certificate", encoding="utf-8")
    append_log(project / "output/send_phd.csv", Recipient(email="old@example.com", company="Old"))
    append_log(project / "output/invalid_mails.csv", Recipient(email="bad@example.com", company="Bad"))
    mode = research_leads.get_mode("PhD", project)

    assert research_leads.list_research_context_files(mode) == [
        cv,
        project / "output/invalid_mails.csv",
        project / "output/send_phd.csv",
    ]


def test_read_known_exclusion_context_pastes_sent_invalid_and_input(project: Path) -> None:
    """Checks behavior for read known exclusion context pastes known rows."""
    append_log(project / "output/send_phd.csv", Recipient(email="sent@example.com", company="Sent Co"))
    append_log(project / "output/invalid_mails.csv", Recipient(email="bad@example.com", company="Bad Co"))
    (project / "input/PhD/current.csv").write_text(
        "company,mail,source_url\nInput Co,input@example.com,https://input.example/contact\n",
        encoding="utf-8",
    )

    context = research_leads.read_known_exclusion_context(
        project,
        research_leads.get_mode("PhD", project),
    )

    assert "DIESE INHALTE WURDEN BEREITS GEFUNDEN" in context
    assert "Sent Co" in context
    assert "Bad Co" in context
    assert "Input Co" in context
    assert "sent@example.com" in context
    assert "bad@example.com" in context
    assert "input@example.com" in context


def test_parse_recipients_filters_duplicates_existing_bad_email_and_company_limit() -> None:
    """Checks behavior for parse recipients filters duplicates existing bad email and company limit."""
    raw = """
```csv
company,mail,source_url
A,mailto:a@example.com,https://a.example/contact
A,bad,https://a.example/contact
A,other@example.com,https://a.example/team
B,existing@example.com,https://b.example/contact
,missing-company@example.com,https://missing.example/contact
Missing Email,,https://missing.example/contact
C,c@example.com,https://c.example/contact
D,d@example.com,
```
"""

    recipients = research_leads.parse_recipients(raw, {"existing@example.com"})

    assert recipients == [
        Recipient(email="a@example.com", company="A", source_url="https://a.example/contact"),
        Recipient(email="other@example.com", company="A", source_url="https://a.example/team"),
        Recipient(email="c@example.com", company="C", source_url="https://c.example/contact"),
    ]


def test_parse_recipients_filters_existing_company_but_allows_multiple_new_company_emails() -> None:
    """Checks behavior for parse recipients filters existing company but allows multiple new company emails."""
    raw = """company,mail,source_url
Old Company,old-new@example.com,https://old.example/contact
New Company,one@example.com,https://new.example/contact
New Company,two@example.com,https://new.example/team
"""

    recipients = research_leads.parse_recipients(raw, set(), {"oldcompany"})

    assert recipients == [
        Recipient(email="one@example.com", company="New Company", source_url="https://new.example/contact"),
        Recipient(email="two@example.com", company="New Company", source_url="https://new.example/team"),
    ]


def test_parse_recipients_no_longer_requires_headers() -> None:
    # Previously it required headers, now it should handle headerless data if it looks like company,email
    """Checks behavior for parse recipients no longer requires headers."""
    assert research_leads.parse_recipients("A,a@example.com", set()) == [
        Recipient(email="a@example.com", company="A")
    ]
    assert research_leads.parse_recipients("", set()) == []
    assert research_leads._detect_dialect("") == research_leads.DefaultCsvDialect


def test_parse_recipients_legacy_verbose_bool_paths(capsys) -> None:
    """Covers legacy positional verbose compatibility branches."""
    assert research_leads.parse_recipients("Company,legacy@example.com", set(), True) == [
        Recipient(email="legacy@example.com", company="Company")
    ]
    assert "Parsing AI response" in capsys.readouterr().out

    assert research_leads._parse_headerless_csv_recipients("Company,headerless@example.com", set(), True) == [
        Recipient(email="headerless@example.com", company="Company")
    ]
    assert "Headerless CSV row count" in capsys.readouterr().out

    payload = '{"leads": [{"company": "Json Co", "mail": "json@example.com", "source_url": "https://json.example"}]}'
    assert research_leads._parse_json_recipients(payload, set(), True) == [
        Recipient(email="json@example.com", company="Json Co", source_url="https://json.example")
    ]
    assert "JSON lead row count" in capsys.readouterr().out


def test_logging_utils_main_thread_has_no_prefix(capsys) -> None:
    """Checks the main-thread logging prefix branch."""
    logging_utils.set_thread_id(None)
    assert logging_utils.get_thread_id() == ""
    logging_utils.info("hello")
    assert capsys.readouterr().out == "[INFO] hello\n"


def test_logging_utils_worker_thread_uses_thread_name() -> None:
    """Checks the fallback prefix branch for unnamed worker contexts."""
    values: list[str] = []

    def read_prefix() -> None:
        logging_utils.set_thread_id(None)
        values.append(logging_utils.get_thread_id())

    worker = threading.Thread(target=read_prefix, name="worker-1")
    worker.start()
    worker.join()

    assert values == ["[worker-1] "]


def test_parse_recipients_handles_gemini_dump_and_company_commas() -> None:
    """Checks behavior for parse recipients handles gemini dump and company commas."""
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


def test_parse_recipients_prefers_csv_block_from_mixed_gemini_output() -> None:
    """Checks behavior for parse recipients prefers csv block from mixed gemini output."""
    raw = """```json
[
  {"company": "Wrong", "mail": "wrong@example.com"}
]
``````csv
company,mail,source_url
CSIRO,industry.phd@csiro.au,https://csiro.au/contact
The University of Queensland,enquire@uq.edu.au,https://uq.edu.au/contact
```
"""

    recipients = research_leads.parse_recipients(raw, set())

    assert recipients == [
        Recipient(email="industry.phd@csiro.au", company="CSIRO", source_url="https://csiro.au/contact"),
        Recipient(email="enquire@uq.edu.au", company="The University of Queensland", source_url="https://uq.edu.au/contact"),
    ]


def test_parse_recipients_from_example_raw() -> None:
    # This test verifies that parse_recipients can handle the full example.raw file
    # and extract the expected data correctly.
    """Checks behavior for parse recipients from example raw."""
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
    """Prueft das Verhalten fuer write recipients csv."""
    path = research_leads.write_recipients_csv(
        project / "input/PhD",
        "PhD",
        [Recipient(email="a@example.com", company="A")],
    )

    assert path.name.startswith("research_phd_")
    assert path.read_text(encoding="utf-8").splitlines() == ["company,mail,source_url", "A,a@example.com,"]


def test_generate_response_reports_thread_target_list_progress(
        monkeypatch: pytest.MonkeyPatch,
        project: Path,
        capsys,
) -> None:
    """Prueft die Thread-Meldung fuer neu aufgenommene Gesamt-Target-Mails."""
    mode = research_leads.get_mode("PhD", project)
    cfg = config(project, max_companies=5)
    sink = research_leads.ThreadSafeRecipientSink(
        target_count=3,
        seen_emails=set(),
        seen_companies=set(),
        config=cfg,
        mode=mode,
        global_target_count=5,
        initial_count=2,
    )

    monkeypatch.setattr(
        research_leads,
        "_generate_research_response",
        lambda *args, **kwargs: (
            "company,mail,source_url\n"
            "A,a@example.com,https://a.example/contact\n"
            "B,b@example.com,https://b.example/contact\n"
        ),
    )
    monkeypatch.setattr(
        research_leads,
        "validate_email_address",
        lambda *args, **kwargs: py_types.SimpleNamespace(is_valid=True, reason=""),
    )

    added = research_leads._generate_and_process_response(
        cfg,
        mode,
        "prompt",
        [],
        sink,
        "",
        thread_id=7,
    )

    assert added == 2
    output = capsys.readouterr().out
    assert "Thread 7 added 2 new email(s) to the global target list." in output
    assert "The global target list now has 4 email(s)" in output
    assert "1 still missing to reach target 5" in output


def test_research_sink_checks_neverbounce_before_saving(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Checks that Research only saves NeverBounce-valid leads."""
    mode = research_leads.get_mode("PhD", project)
    cfg = config(
        project,
        external_validation_service="neverbounce",
        external_validation_api_key="never-key",
    )
    sink = research_leads.ThreadSafeRecipientSink(
        target_count=2,
        seen_emails=set(),
        seen_companies=set(),
        config=cfg,
        mode=mode,
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_validate(email: str, **kwargs):
        calls.append((email, kwargs))
        return py_types.SimpleNamespace(
            is_valid=email == "valid@example.com",
            reason="" if email == "valid@example.com" else "NeverBounce: invalid",
        )

    monkeypatch.setattr(research_leads, "validate_email_address", fake_validate)

    assert sink.add_recipient(Recipient(email="valid@example.com", company="Valid"), thread_id=0) is True
    assert sink.add_recipient(Recipient(email="bad@example.com", company="Bad"), thread_id=0) is False

    assert [recipient.email for recipient in sink.recipients] == ["valid@example.com"]
    saved_files = list((project / "input/PhD").glob("leads_*.csv"))
    assert len(saved_files) == 1
    saved_text = saved_files[0].read_text(encoding="utf-8")
    assert "valid@example.com" in saved_text
    assert "bad@example.com" not in saved_text
    invalid_rows = (project / "output/invalid_mails.csv").read_text(encoding="utf-8-sig")
    assert "bad@example.com" in invalid_rows
    assert calls[0][1]["external_service"] == "neverbounce"
    assert calls[0][1]["external_api_key"] == "never-key"


def test_research_sink_send_stage_skips_neverbounce_before_saving(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Checks that send-stage NeverBounce leaves research saving to local validation only."""
    mode = research_leads.get_mode("PhD", project)
    cfg = config(
        project,
        external_validation_service="neverbounce",
        external_validation_api_key="never-key",
        external_validation_stage="send",
    )
    sink = research_leads.ThreadSafeRecipientSink(
        target_count=1,
        seen_emails=set(),
        seen_companies=set(),
        config=cfg,
        mode=mode,
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_validate(email: str, **kwargs):
        calls.append((email, kwargs))
        return py_types.SimpleNamespace(is_valid=True, reason="")

    monkeypatch.setattr(research_leads, "validate_email_address", fake_validate)

    assert sink.add_recipient(Recipient(email="valid@example.com", company="Valid"), thread_id=0) is True

    assert calls == [
        (
            "valid@example.com",
            {
                "verify_mailbox": False,
                "smtp_timeout": 10.0,
                "external_service": "none",
                "external_api_key": "",
            },
        )
    ]
    assert [recipient.email for recipient in sink.recipients] == ["valid@example.com"]


def test_run_research_writes_output(monkeypatch: pytest.MonkeyPatch, project: Path, capsys) -> None:
    """Prueft das Verhalten fuer run research writes output."""
    cv = project / "attachments/PhD/CV.pdf"
    cert = project / "attachments/PhD/context.pdf"
    cv.write_text("cv", encoding="utf-8")
    cert.write_text("cert", encoding="utf-8")
    append_log(project / "output/send_phd.csv", Recipient(email="old@example.com", company="Old Co"))

    def fake_generate(model, prompt, attachments, reasoning_effort="middle", verbose=False):
        """Kapselt den Hilfsschritt fake_generate."""
        assert model == "gemini-2.5-flash-lite"
        # The test originally expected [cv, project / "output/send_phd.csv"] but due to iteration 2 it might be called again with []
        if not attachments:
            return ""
        assert attachments == [cv, project / "output/send_phd.csv"]
        assert reasoning_effort == "middle"
        assert "Existing email exclusion list" in prompt
        assert "Existing company exclusion list for this mode" in prompt
        assert "oldco" in prompt
        assert "Mode-specific input CSV/TXT context" in prompt
        assert verbose is True
        return "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"

    monkeypatch.setattr(providers, "generate_with_gemini", fake_generate)

    output_path, recipients = research_leads.run_research(config(project, verbose=True))

    assert output_path is not None
    assert output_path.exists()
    assert recipients == [Recipient(email="a@example.com", company="A", source_url="https://a.example/contact")]
    assert "[VERBOSE] AI prompt characters:" in capsys.readouterr().out


def test_run_research_parallel_batch_deduplicates_responses(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Prueft das Verhalten fuer run research parallel batch deduplicates responses."""
    counter = {"value": 0}
    lock = threading.Lock()

    def fake_generate(model, prompt, attachments, reasoning_effort="middle", verbose=False):
        """Kapselt den Hilfsschritt fake_generate."""
        assert model == "gemini-2.5-flash-lite"
        assert prompt
        assert attachments == []
        assert reasoning_effort == "middle"
        assert verbose is False
        with lock:
            counter["value"] += 1
            index = counter["value"]
        return (
            "company,mail,source_url\n"
            "Same Co,same@example.com,https://same.example/contact\n"
            f"Unique {index},unique{index}@example.com,https://unique{index}.example/contact\n"
        )

    monkeypatch.setattr(providers, "generate_with_gemini", fake_generate)

    _, recipients = research_leads.run_research(
        config(project, max_companies=3, max_iterations=3, parallel_threads=3)
    )

    emails = [recipient.email for recipient in recipients]
    assert len(emails) == 3
    assert emails.count("same@example.com") == 1
    assert len(set(emails)) == 3


def test_run_research_self_provider_crawls_and_deduplicates(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Prueft das Verhalten fuer run research self provider crawls and deduplicates."""
    append_log(project / "output/send_phd.csv", Recipient(email="old@example.com", company="Old Co"))

    monkeypatch.setattr(
        self_research,
        "collect_self_search_result_urls",
        lambda cfg, queries: ["https://a.example", "https://b.example"],
    )
    monkeypatch.setattr(
        self_research,
        "crawl_self_result_url",
        lambda cfg, url, stop_event=None, sink=None: [
            Recipient(email="same@example.com", company="Same Co"),
            Recipient(email="old@example.com", company="Old Co"),
            Recipient(email=f"{url.split('//')[1][0]}@example.com", company=f"{url} Co"),
        ],
    )
    monkeypatch.setattr(
        research_leads,
        "validate_email_address",
        lambda *args, **kwargs: py_types.SimpleNamespace(is_valid=True, reason=""),
    )

    _, recipients = research_leads.run_research(
        config(project, provider="self", model="self", max_companies=3, parallel_threads=2)
    )

    emails = [recipient.email for recipient in recipients]
    assert emails == ["same@example.com", "a@example.com", "b@example.com"]


def test_self_google_result_parser_decodes_result_links() -> None:
    """Prueft das Verhalten fuer self google result parser decodes result links."""
    html_text = '''
    <a href="/url?q=https%3A%2F%2Fexample.com%2Fcontact&sa=U">result</a>
    <a href="https://direct.example/about">direct</a>
    '''

    assert research_leads._extract_google_result_urls(html_text) == [
        "https://example.com/contact",
        "https://direct.example/about",
    ]


def test_self_crawler_respects_depth_and_extracts_nested_emails(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Prueft das Verhalten fuer self crawler respects depth and extracts nested emails."""
    pages = {
        "https://example.com": '<html><head><title>Example Co</title></head><body><a href="/about">About</a></body></html>',
        "https://example.com/about": '<html><head><title>Example About</title></head><body><a href="/team">Team</a></body></html>',
        "https://example.com/team": '<html><head><title>Example Team</title></head><body>hello@example.com</body></html>',
    }

    monkeypatch.setattr(self_research, "fetch_text", lambda url, timeout, verbose: pages.get(url, ""))

    shallow = research_leads.crawl_self_result_url(config(project, provider="self", self_crawl_depth=1), "https://example.com")
    deep = research_leads.crawl_self_result_url(config(project, provider="self", self_crawl_depth=2), "https://example.com")

    assert shallow == []
    assert deep == [Recipient(email="hello@example.com", company="Example Team", source_url="https://example.com/team")]


def test_generate_with_ollama_posts_to_local_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueft das Verhalten fuer generate with ollama posts to local api."""
    captured = {}

    class FakeResponse:
        """Dokumentiert die Test- oder Hilfsklasse FakeResponse."""

        def __enter__(self):
            """Initialisiert oder verwaltet das Testobjekt."""
            return self

        def __exit__(self, exc_type, exc, traceback):
            """Initialisiert oder verwaltet das Testobjekt."""
            return None

        @staticmethod
        def read():
            """Kapselt den Hilfsschritt read."""
            return b'{"response": "company,mail,source_url\\nA,a@example.com,https://a.example/contact\\n"}'

    def fake_urlopen(request, timeout):
        """Kapselt den Hilfsschritt fake_urlopen."""
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = research_leads.generate_with_ollama("llama3.1:8b", "prompt", "http://localhost:11434", True)

    assert result.startswith("company,mail,source_url")
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["payload"]["model"] == "llama3.1:8b"
    assert captured["payload"]["prompt"] == "prompt"
    assert captured["payload"]["stream"] is False
    assert captured["timeout"] == 300


def test_ollama_provider_uses_self_web_candidates_before_llm(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Prueft das Verhalten fuer ollama provider uses self web candidates before llm."""
    calls = []

    monkeypatch.setattr(
        self_research,
        "collect_self_search_result_urls",
        lambda cfg, queries: calls.append(("search", tuple(queries))) or ["https://example.com"],
    )
    monkeypatch.setattr(
        self_research,
        "crawl_self_result_url",
        lambda cfg, url, stop_event=None, sink=None: calls.append(("crawl", url)) or [Recipient(email="lead@example.com", company="Lead Co")],
    )
    monkeypatch.setattr(
        research_leads,
        "validate_email_address",
        lambda *args, **kwargs: py_types.SimpleNamespace(is_valid=True, reason=""),
    )

    def fake_ollama(model, prompt, base_url, verbose=False):
        """Kapselt den Hilfsschritt fake_ollama."""
        assert verbose is False
        calls.append(("ollama", model, base_url, "lead@example.com" in prompt))
        return "company,mail,source_url\nLead Co,lead@example.com,self-crawl\n"

    monkeypatch.setattr(providers, "generate_with_ollama", fake_ollama)
    # Also patch research_leads alias just in case
    monkeypatch.setattr(research_leads, "generate_with_ollama", fake_ollama)

    _, recipients = research_leads.run_research(
        config(project, provider="ollama", model="llama3.1:8b", max_companies=2)
    )

    assert recipients == [Recipient(email="lead@example.com", company="Lead Co", source_url="self-crawl")]
    assert calls == [
        ("search", ("query",)),
        ("crawl", "https://example.com"),
        ("ollama", "llama3.1:8b", "http://localhost:11434", True),
    ]


def test_run_research_can_skip_output_and_validates(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    """Prueft das Verhalten fuer run research can skip output and validates."""
    monkeypatch.setattr(
        providers,
        "generate_with_gemini",
        lambda model, prompt, attachments, reasoning_effort="middle", verbose=False: "company,mail,source_url\nA,a@example.com,https://a.example/contact\n",
    )

    output_path, recipients = research_leads.run_research(config(project, write_output=False))
    assert output_path is None
    assert recipients == [Recipient(email="a@example.com", company="A", source_url="https://a.example/contact")]

    bad_config = ResearchConfig("gemini", "PhD", "model", 2, 1, 1, project, True, False, True, "gemini-model", "openai-model", reasoning_effort="middle")
    with pytest.raises(ValueError, match="Company limits"):
        research_leads.run_research(bad_config)

    monkeypatch.setattr(
        providers,
        "generate_with_gemini",
        lambda *args, **kwargs: "company,mail,source_url\n",
    )
    with pytest.raises(RuntimeError, match="no new usable"):
        research_leads.run_research(config(project))


def test_run_research_can_skip_attachment_upload(monkeypatch: pytest.MonkeyPatch, project: Path, capsys) -> None:
    """Prueft das Verhalten fuer run research can skip attachment upload."""
    (project / "attachments/PhD/context.pdf").write_text("context", encoding="utf-8")

    def fake_generate(model, prompt, attachments, reasoning_effort="middle", verbose=False):
        """Kapselt den Hilfsschritt fake_generate."""
        assert model == "gemini-2.5-flash-lite"
        assert prompt
        assert reasoning_effort == "middle"
        assert attachments == []
        assert verbose is True
        return "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"

    monkeypatch.setattr(providers, "generate_with_gemini", fake_generate)

    _, recipients = research_leads.run_research(config(project, verbose=True, upload_attachments=False))

    assert recipients == [Recipient(email="a@example.com", company="A", source_url="https://a.example/contact")]
    assert "Attachment upload disabled" in capsys.readouterr().out


def test_run_research_pastes_known_context_when_configured(
        monkeypatch: pytest.MonkeyPatch,
        project: Path,
        capsys,
) -> None:
    """Checks behavior for run research pastes known context when configured."""
    (project / "attachments/PhD/CV.pdf").write_text("cv", encoding="utf-8")
    append_log(project / "output/send_phd.csv", Recipient(email="sent@example.com", company="Sent Co"))
    append_log(project / "output/invalid_mails.csv", Recipient(email="bad@example.com", company="Bad Co"))
    (project / "input/PhD/current.csv").write_text(
        "company,mail,source_url\nInput Co,input@example.com,https://input.example/contact\n",
        encoding="utf-8",
    )
    seen: dict[str, Any] = {}

    def fake_generate(_model, prompt, attachments, **_kwargs):
        """Kapselt den Hilfsschritt fake_generate."""
        seen["prompt"] = prompt
        seen["attachments"] = attachments
        return "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"

    monkeypatch.setattr(providers, "generate_with_gemini", fake_generate)

    _, recipients = research_leads.run_research(
        config(project, verbose=True, research_context_delivery="paste_in_prompt")
    )

    assert recipients == [Recipient(email="a@example.com", company="A", source_url="https://a.example/contact")]
    assert seen["attachments"] == []
    assert "DIESE INHALTE WURDEN BEREITS GEFUNDEN" in seen["prompt"]
    assert "Sent Co" in seen["prompt"]
    assert "Bad Co" in seen["prompt"]
    output = capsys.readouterr().out
    assert "Built AI prompt with known context: 1 sent mail(s), 1 invalid mail(s), 1 input mail(s)" in output
    assert "Built AI prompt message:" in output
    assert "Thread 0 sending AI prompt with known context: 1 sent/valid mail(s), 1 invalid mail(s), 1 input mail(s)." in output
    assert "Thread 0 AI prompt sent:" in output


def test_run_research_retries_without_attachments_after_empty_response(
        monkeypatch: pytest.MonkeyPatch,
        project: Path,
        capsys,
) -> None:
    """Prueft das Verhalten fuer run research retries without attachments after empty response."""
    attachment = project / "attachments/PhD/context.pdf"
    cv = project / "attachments/PhD/CV.pdf"
    attachment.write_text("context", encoding="utf-8")
    cv.write_text("cv", encoding="utf-8")
    calls = []

    def fake_generate(model, prompt, attachments, reasoning_effort="middle", verbose=False):
        """Kapselt den Hilfsschritt fake_generate."""
        assert model == "gemini-2.5-flash-lite"
        assert prompt
        assert reasoning_effort == "middle"
        assert verbose is True
        calls.append(attachments)
        if attachments and len(calls) == 1:
            return ""
        return "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"

    monkeypatch.setattr(providers, "generate_with_gemini", fake_generate)

    _, recipients = research_leads.run_research(config(project, verbose=True, max_companies=1))

    assert calls[0] == [cv]
    assert calls[1] == []
    assert recipients == [Recipient(email="a@example.com", company="A", source_url="https://a.example/contact")]
    assert "retrying once without attachment uploads" in capsys.readouterr().out


def test_run_research_retries_with_lite_prompt_after_model_error(
        monkeypatch: pytest.MonkeyPatch,
        project: Path,
        capsys,
) -> None:
    """Prueft das Verhalten fuer run research retries with lite prompt after model error."""
    calls = []

    def fake_generate(model, prompt, attachments, reasoning_effort="middle", verbose=False):
        """Kapselt den Hilfsschritt fake_generate."""
        assert model == "gemini-2.5-flash-lite"
        assert attachments == []
        assert reasoning_effort == "middle"
        assert verbose is True
        calls.append(prompt)
        if len(calls) == 1:
            return "I'm sorry, but I encountered an error that prevented me from fulfilling your request. Please try again."
        # Use lite prompt check if we are in iteration 1 retry or later
        return "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"

    monkeypatch.setattr(providers, "generate_with_gemini", fake_generate)

    _, recipients = research_leads.run_research(config(project, verbose=True, max_companies=1))

    assert len(calls) >= 2
    assert recipients == [Recipient(email="a@example.com", company="A", source_url="https://a.example/contact")]
    output = capsys.readouterr().out
    assert "retrying once with a smaller prompt" in output
    assert "Lite AI prompt characters:" in output


def test_needs_retry_handles_invalid_csv() -> None:
    """Prueft das Verhalten fuer needs retry handles invalid csv."""
    assert research_leads._needs_retry("not,csv\nonly-one-value\n", set()) is True


def test_model_for_provider_uses_provider_specific_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueft das Verhalten fuer model for provider uses provider specific env."""
    monkeypatch.setenv("GEMINI_MODEL", "generic-model")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")

    assert research_leads._model_for_provider("openai", "g", "o") == "gpt-test"
    assert research_leads._model_for_provider("gemini", "g", "o") == "generic-model"


def test_generate_with_provider_selects_openai_and_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueft das Verhalten fuer generate with provider selects openai and rejects unknown."""
    monkeypatch.setattr(
        providers,
        "generate_with_openai",
        lambda model, prompt, attachments, reasoning_effort="middle", verbose=False: "company,mail,source_url\nA,a@example.com,https://a.example/contact\n",
    )

    assert research_leads.generate_with_provider("openai", "gpt-5.4", "prompt", [], "middle", True) == (
        "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"
    )

    with pytest.raises(ValueError, match="Unknown research provider"):
        research_leads.generate_with_provider("other", "model", "prompt", [], "middle", False)


def test_main_success_and_error(monkeypatch: pytest.MonkeyPatch, project: Path, capsys) -> None:
    """Prueft das Verhalten fuer main success and error."""
    monkeypatch.setattr(
        research_leads,
        "run_research",
        lambda cfg: (project / "input/PhD/research.csv", [Recipient(email="a@example.com", company="A")]),
    )
    result = research_leads.main(["--mode", "PhD", "--base-dir", str(project)])
    assert result == 0
    assert "New recipients: 1" in capsys.readouterr().out

    def broken_run(_cfg):
        """Kapselt den Hilfsschritt broken_run."""
        raise RuntimeError("boom")

    monkeypatch.setattr(research_leads, "run_research", broken_run)
    result = research_leads.main(["--mode", "PhD", "--base-dir", str(project)])
    assert result == 1
    assert "Error: boom" in capsys.readouterr().out


def test_generate_with_gemini_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueft das Verhalten fuer generate with gemini requires api key."""
    monkeypatch.setattr(providers, "load_dotenv", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        providers.generate_with_gemini("model", "prompt", [])


def test_generate_with_openai_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueft das Verhalten fuer generate with openai requires api key."""
    monkeypatch.setattr(providers, "load_dotenv", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        providers.generate_with_openai("model", "prompt", [])


def test_generate_with_openai_uses_web_search_and_uploaded_files(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys,
) -> None:
    """Prueft das Verhalten fuer generate with openai uses web search and uploaded files."""
    monkeypatch.setattr(providers, "load_dotenv", lambda: None)
    attachment = tmp_path / "context.pdf"
    attachment.write_text("context", encoding="utf-8")

    class FakeFiles:
        """Dokumentiert die Test- oder Hilfsklasse FakeFiles."""

        @staticmethod
        def create(file, purpose: str):
            """Kapselt den Hilfsschritt create."""
            assert file.read() == b"context"
            assert purpose == "user_data"
            return py_types.SimpleNamespace(id="file_123")

    class FakeResponses:
        """Dokumentiert die Test- oder Hilfsklasse FakeResponses."""

        @staticmethod
        def create(model, input_data, tools, **kwargs):
            """Kapselt den Hilfsschritt create."""
            assert model == "gpt-5.4"
            assert input_data == [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "prompt"},
                        {"type": "input_file", "file_id": "file_123"},
                    ],
                }
            ]
            assert tools == [{"type": "web_search"}]
            assert kwargs["tool_choice"] == "auto"
            assert kwargs["reasoning"] == {"effort": "low"}
            output_item = py_types.SimpleNamespace(type="message", status="completed", content=[])
            return py_types.SimpleNamespace(output_text="company,mail,source_url\nA,a@example.com,https://a.example/contact\n", output=[output_item])

    class FakeOpenAI:
        """Dokumentiert die Test- oder Hilfsklasse FakeOpenAI."""

        def __init__(self, api_key: str) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            assert api_key == "key"
            self.files = FakeFiles()
            self.responses = FakeResponses()

    fake_openai = py_types.ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    assert providers.generate_with_openai("gpt-5.4", "prompt", [attachment], "low", True) == (
        "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"
    )
    output = capsys.readouterr().out
    assert "Calling OpenAI Responses API with web_search enabled." in output
    assert "reasoning_effort=low" in output
    assert "OpenAI output items: 1" in output


def test_generate_with_openai_reads_output_content_when_output_text_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueft das Verhalten fuer generate with openai reads output content when output text empty."""
    monkeypatch.setattr(providers, "load_dotenv", lambda: None)

    class FakeFiles:
        """Dokumentiert die Test- oder Hilfsklasse FakeFiles."""

        @staticmethod
        def create():
            """Kapselt den Hilfsschritt create."""
            return py_types.SimpleNamespace(id="file_123")

    class FakeResponses:
        """Dokumentiert die Test- oder Hilfsklasse FakeResponses."""

        @staticmethod
        def create():
            """Kapselt den Hilfsschritt create."""
            input_data = [py_types.SimpleNamespace(text="company,mail,source_url\nA,a@example.com,https://a.example/contact\n")]
            output = [py_types.SimpleNamespace(type="message", status="completed", content=input_data)]
            return py_types.SimpleNamespace(output_text="", output=output)

    class FakeOpenAI:
        """Dokumentiert die Test- oder Hilfsklasse FakeOpenAI."""

        def __init__(self) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.files = FakeFiles()
            self.responses = FakeResponses()

    fake_openai = py_types.ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    fake_openai.RateLimitError = type("RateLimitError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    assert providers.generate_with_openai("gpt-5.4", "prompt", [], "middle", False) == (
        "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"
    )


def test_verbose_openai_output_handles_disabled_and_empty(capsys) -> None:
    """Prueft das Verhalten fuer verbose openai output handles disabled and empty."""
    research_leads._verbose_openai_output(False, py_types.SimpleNamespace(output=[]))
    assert capsys.readouterr().out == ""

    research_leads._verbose_openai_output(True, py_types.SimpleNamespace(output=[]))
    assert "OpenAI output items: none" in capsys.readouterr().out


def test_generate_with_gemini_uses_google_search_and_uploaded_files(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys,
) -> None:
    """Prueft das Verhalten fuer generate with gemini uses google search and uploaded files."""
    monkeypatch.setattr(providers, "load_dotenv", lambda: None)
    uploaded = object()
    attachment = tmp_path / "context.pdf"
    attachment.write_text("context", encoding="utf-8")

    class FakeFiles:
        """Dokumentiert die Test- oder Hilfsklasse FakeFiles."""

        @staticmethod
        def upload(**kwargs):
            """Kapselt den Hilfsschritt upload."""
            assert kwargs["file"] == attachment
            return uploaded

    # noinspection PyShadowingNames
    class FakeModels:
        """Dokumentiert die Test- oder Hilfsklasse FakeModels."""

        @staticmethod
        def generate_content(*args, **kwargs):
            # args[1] might be contents list in Gemini API
            """Kapselt den Hilfsschritt generate_content."""
            contents = kwargs.get("contents", args[1] if len(args) > 1 else [])
            assert contents == ["prompt", uploaded]
            config_val: Any = kwargs["config"]
            thinking_config = getattr(config_val, "thinking_config")
            thinking_level = getattr(thinking_config, "thinking_level")
            tool_config = getattr(config_val, "tool_config")
            function_config = getattr(tool_config, "function_calling_config")
            assert getattr(config_val, "temperature") == 1
            assert getattr(thinking_level, "name") == "FULL"
            assert getattr(function_config, "mode") == "AUTO"
            assert getattr(tool_config, "include_server_side_tool_invocations") is True
            return py_types.SimpleNamespace(text='{"leads": []}')

    class FakeClient:
        """Dokumentiert die Test- oder Hilfsklasse FakeClient."""

        def __init__(self) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.files = FakeFiles()
            self.models = FakeModels()

    setup_fake_genai(monkeypatch, FakeClient)

    assert research_leads.generate_with_gemini("gemini-2.5-flash-lite", "prompt", [attachment], "high", True) == '{"leads": []}'
    output = capsys.readouterr().out
    assert 'Gemini response.text raw: \'{"leads": []}\'' in output
    assert "thinking_level=FULL" in output
    assert "Gemini candidates: none" in output


def test_generate_with_gemini_logs_empty_candidate_metadata(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Prueft das Verhalten fuer generate with gemini logs empty candidate metadata."""
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)

    class FakeFiles:
        """Dokumentiert die Test- oder Hilfsklasse FakeFiles."""

        @staticmethod
        def upload():
            """Kapselt den Hilfsschritt upload."""
            return object()

    class FakeModels:
        """Dokumentiert die Test- oder Hilfsklasse FakeModels."""

        @staticmethod
        def generate_content(**kwargs):
            """Kapselt den Hilfsschritt generate_content."""
            assert kwargs["model"] == "gemini-2.5-flash-lite"
            part = py_types.SimpleNamespace(text=None)
            content = py_types.SimpleNamespace(parts=[part])
            candidate = py_types.SimpleNamespace(
                finish_reason="SAFETY",
                safety_ratings=["blocked"],
                content=content,
            )
            return py_types.SimpleNamespace(text="", candidates=[candidate], prompt_feedback="ok")

    class FakeClient:
        """Dokumentiert die Test- oder Hilfsklasse FakeClient."""

        def __init__(self) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.files = FakeFiles()
            self.models = FakeModels()

    setup_fake_genai(monkeypatch, FakeClient)

    assert research_leads.generate_with_gemini("gemini-2.5-flash-lite", "prompt", [], "middle", True) == ""
    output = capsys.readouterr().out
    assert "Gemini response.text raw: ''" in output
    assert "Gemini prompt_feedback: 'ok'" in output
    assert "thinking_level=MEDIUM" in output
    assert "Gemini candidates: 1" in output
    assert "Gemini candidate 1 finish_reason: 'SAFETY'" in output


def test_fake_txt_extensions(tmp_path: Path) -> None:
    """Prueft das Verhalten fuer fake txt extensions."""
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("a,b,c", encoding="utf-8")
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_text("pdf content", encoding="utf-8")

    with research_leads._fake_txt_extensions([csv_file, pdf_file], verbose=True) as new_paths:
        assert len(new_paths) == 2
        assert new_paths[1] == pdf_file
        assert new_paths[0].suffix == ".txt"
        assert new_paths[0].name == "test.csv.txt"
        assert new_paths[0].exists()
        assert new_paths[0].read_text(encoding="utf-8") == "a,b,c"
        # Original should still exist
        assert csv_file.exists()

    # After context, temp file should be gone
    assert not new_paths[0].exists()
    assert csv_file.exists()
    assert pdf_file.exists()


def test_generate_with_gemini_fakes_csv_extension(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    """Prueft das Verhalten fuer generate with gemini fakes csv extension."""
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    csv_attachment = tmp_path / "data.csv"
    csv_attachment.write_text("col1,col2", encoding="utf-8")

    captured_paths = []

    class FakeFiles:
        """Dokumentiert die Test- oder Hilfsklasse FakeFiles."""

        @staticmethod
        def upload(*args, **kwargs):
            """Kapselt den Hilfsschritt upload."""
            if args:
                captured_paths.append(args[0])
            elif "file" in kwargs:
                captured_paths.append(kwargs["file"])
            return object()

    class FakeModels:
        """Dokumentiert die Test- oder Hilfsklasse FakeModels."""

        @staticmethod
        def generate_content(**kwargs):
            """Kapselt den Hilfsschritt generate_content."""
            assert kwargs["model"] == "model"
            return py_types.SimpleNamespace(text='{"leads": []}')

    class FakeClient:
        """Dokumentiert die Test- oder Hilfsklasse FakeClient."""

        def __init__(self) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.files = FakeFiles()
            self.models = FakeModels()

    fake_google = py_types.ModuleType("google")
    fake_genai = py_types.ModuleType("google.genai")
    fake_genai.Client = FakeClient
    fake_genai.types = py_types.SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: None,
        Tool=lambda **kwargs: None,
        GoogleSearch=lambda: None,
        ToolConfig=lambda **kwargs: None,
        FunctionCallingConfig=lambda **kwargs: None,
        FunctionCallingConfigMode=py_types.SimpleNamespace(AUTO="AUTO"),
        ThinkingConfig=lambda **kwargs: None,
        ThinkingLevel=py_types.SimpleNamespace(
            BRIEF=py_types.SimpleNamespace(name="BRIEF"),
            MEDIUM=py_types.SimpleNamespace(name="MEDIUM"),
            FULL=py_types.SimpleNamespace(name="FULL")
        ),
    )
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setenv("GEMINI_API_KEY", "key")

    research_leads.generate_with_gemini("model", "prompt", [csv_attachment], "middle", True)

    assert len(captured_paths) == 1
    assert captured_paths[0].suffix == ".txt"
    assert captured_paths[0].name == "data.csv.txt"
    assert not captured_paths[0].exists()  # Should be deleted after upload


def test_generate_with_openai_fakes_csv_extension(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    """Prueft das Verhalten fuer generate with openai fakes csv extension."""
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)
    csv_attachment = tmp_path / "data.csv"
    csv_attachment.write_text("col1,col2", encoding="utf-8")

    captured_paths = []

    class FakeFiles:
        """Dokumentiert die Test- oder Hilfsklasse FakeFiles."""

        @staticmethod
        def create(file):
            """Kapselt den Hilfsschritt create."""
            captured_paths.append(Path(file.name))
            return py_types.SimpleNamespace(id="file_123")

    class FakeResponses:
        """Dokumentiert die Test- oder Hilfsklasse FakeResponses."""

        @staticmethod
        def create():
            """Kapselt den Hilfsschritt create."""
            return py_types.SimpleNamespace(output_text='{"leads": []}', output=[])

    class FakeClient:
        """Dokumentiert die Test- oder Hilfsklasse FakeClient."""

        def __init__(self) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.files = FakeFiles()
            self.responses = FakeResponses()

    fake_openai = py_types.ModuleType("openai")
    fake_openai.OpenAI = FakeClient
    fake_openai.RateLimitError = type("RateLimitError", (Exception,), {"response": py_types.SimpleNamespace(status_code=429)})
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    research_leads.generate_with_openai("model", "prompt", [csv_attachment], "middle", True)

    assert len(captured_paths) == 1
    assert captured_paths[0].suffix == ".txt"
    assert captured_paths[0].name == "data.csv.txt"
    assert not captured_paths[0].exists()  # Should be deleted after upload


def test_generate_with_gemini_reads_candidate_part_text_when_response_text_is_empty(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prueft das Verhalten fuer generate with gemini reads candidate part text when response text is empty."""
    monkeypatch.setattr(research_leads, "load_dotenv", lambda: None)

    class FakeFiles:
        """Dokumentiert die Test- oder Hilfsklasse FakeFiles."""

        @staticmethod
        def upload():
            """Kapselt den Hilfsschritt upload."""
            return object()

    class FakeModels:
        """Dokumentiert die Test- oder Hilfsklasse FakeModels."""

        @staticmethod
        def generate_content(**kwargs):
            """Kapselt den Hilfsschritt generate_content."""
            assert kwargs["model"] == "gemini-2.5-flash-lite"
            part = py_types.SimpleNamespace(text="company,mail,source_url\nA,a@example.com,https://a.example/contact\n")
            content = py_types.SimpleNamespace(parts=[part])
            candidate = py_types.SimpleNamespace(
                finish_reason="STOP",
                safety_ratings=None,
                content=content,
            )
            return py_types.SimpleNamespace(text="", candidates=[candidate])

    class FakeClient:
        """Dokumentiert die Test- oder Hilfsklasse FakeClient."""

        def __init__(self) -> None:
            """Initialisiert oder verwaltet das Testobjekt."""
            self.files = FakeFiles()
            self.models = FakeModels()

    setup_fake_genai(monkeypatch, FakeClient)

    assert research_leads.generate_with_gemini("gemini-2.5-flash-lite", "prompt", [], "middle", False) == (
        "company,mail,source_url\nA,a@example.com,https://a.example/contact\n"
    )


def test_verbose_gemini_candidates_handles_disabled_and_missing_parts(capsys) -> None:
    """Prueft das Verhalten fuer verbose gemini candidates handles disabled and missing parts."""
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


def test_direct_script_bootstrap_inserts_code_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueft das Verhalten fuer direct script bootstrap inserts code dir."""
    original_path = list(sys.path)
    research_dir = CODE_DIR / "research"
    monkeypatch.setattr(
        sys,
        "path",
        [str(research_dir)] + [
            path
            for path in original_path
            if not path or Path(path).resolve() != CODE_DIR.resolve()
        ],
    )

    namespace = runpy.run_path("code/research/research_leads.py")

    assert namespace["CODE_DIR"] == CODE_DIR
    assert str(CODE_DIR) in sys.path


def test_research_main_uses_sys_argv_when_no_args_are_passed(
        monkeypatch: pytest.MonkeyPatch,
        project: Path,
        capsys,
) -> None:
    """Checks behavior for research main uses sys argv when no args are passed."""
    monkeypatch.setattr("sys.argv", ["research_leads.py", "--mode", "PhD", "--base-dir", str(project)])
    monkeypatch.setattr(
        research_leads,
        "run_research",
        lambda cfg: (project / "input/PhD/research.csv", [Recipient(email="a@example.com", company="A")]),
    )

    assert research_leads.main() == 0
    assert "New recipients: 1" in capsys.readouterr().out


def test_retry_handles_parse_errors(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Checks behavior for retry handles parse errors."""

    def broken_parse(*_args, **_kwargs):
        """Encapsulates the helper step broken_parse."""
        raise ValueError("bad csv")

    monkeypatch.setattr(research_leads, "parse_recipients", broken_parse)

    assert research_leads._needs_retry("not empty", set(), True) is True
    output = capsys.readouterr().out
    assert "Failed to parse CSV" in output
    assert "bad csv" in output


def test_read_input_context_logs_empty_files(project: Path, capsys) -> None:
    """Checks behavior for read input context logs empty files."""
    empty_file = project / "input/PhD/empty.csv"
    empty_file.write_text("   ", encoding="utf-8")

    assert research_leads.read_input_context(project / "input/PhD", verbose=True) == ""
    assert "Skipped empty input context file: empty.csv" in capsys.readouterr().out


def test_parse_recipients_handles_json_and_fence_fallbacks(capsys) -> None:
    """Checks behavior for parse recipients handles json and fence fallbacks."""
    json_text = """
```json
{"leads": [{"company": "A", "emails": ["a@example.com"], "source_urls": ["https://a.example/contact"]}]}
```
"""
    recipients = research_leads.parse_recipients(json_text, set(), verbose=True)
    assert [(recipient.company, recipient.email) for recipient in recipients] == [("A", "a@example.com")]
    assert "Parsed JSON recipients: 1" in capsys.readouterr().out

    list_payload = """
[{"company": "B", "email": "b@example.com", "source": "https://b.example/contact"}, "skip me"]
"""
    recipients = research_leads._parse_json_recipients(list_payload, set(), verbose=True)
    assert [(recipient.company, recipient.email) for recipient in recipients] == [("B", "b@example.com")]

    assert research_leads._parse_json_recipients('"not a list"', set(), verbose=True) == []

    assert research_leads._strip_csv_fence("```csv\nA,a@example.com\n```") == "A,a@example.com"
    assert research_leads._strip_csv_fence("```\nA,a@example.com\n```") == "A,a@example.com"
    assert research_leads._strip_json_fence("```\n{\"leads\": []}\n```") == '{"leads": []}'
    assert research_leads._find_field({"": "", "mail": "a@example.com"}, research_leads.EMAIL_KEYS) == "mail"


def test_headerless_csv_parser_handles_csv_errors(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Checks behavior for headerless csv parser handles csv errors."""

    def broken_dialect(*_args, **_kwargs):
        """Encapsulates the helper step broken_dialect."""
        raise csv.Error("bad dialect")

    monkeypatch.setattr(research_leads, "detect_dialect", broken_dialect)
    monkeypatch.setattr("research.parsing.detect_dialect", broken_dialect)

    assert research_leads._parse_headerless_csv_recipients("A,a@example.com", set(), verbose=True) == []
    assert "Headerless CSV parser failed to read CSV rows." in capsys.readouterr().out
