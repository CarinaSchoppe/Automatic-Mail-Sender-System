# MailSenderSystem

Python pipeline for researching leads and sending PhD or freelance email batches via SMTPS.

## Project Layout

All Python source and tests live in `code/`. Project configuration and data folders stay at the project root:

- `settings.toml`
- `.env`
- `attachments/`
- `input/`
- `output/`
- `templates/`

## Setup

1. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

1. Copy `.env.example` to `.env` and add your local secrets.

2. Place recipient files in the matching `input` subfolder. The selected mode reads all `.csv` and `.txt` files from its folder:

- `input/PhD`
- `input/Freelance_German`
- `input/Freelance_English`

Recommended format:

```csv
company,mail
Example GmbH,max@example.com
```

AI research output additionally includes a `source_url` column:

```csv
company,mail,source_url
Example GmbH,max@example.com,https://example.com/contact
```

The mail sender only needs `company` and `mail`, but research rows without `source_url` are rejected so AI-generated addresses must point to a public source.

1. Place all PhD attachments in `attachments/PhD`.

2. Place all German freelance attachments in `attachments/Freelance_German`.

3. Place all English freelance attachments in `attachments/Freelance_English`.

4. Edit the email templates and signature:

- `templates/phd.txt`
- `templates/freelance_german.txt`
- `templates/freelance_english.txt`
- `templates/signature.txt`

Mode mapping:

- `MODE = "Freelance_German"` uses `templates/freelance_german.txt` and `attachments/Freelance_German`
- `MODE = "Freelance_English"` uses `templates/freelance_english.txt` and `attachments/Freelance_English`

The signature contains `{IMAGE}` for your logo. By default, place the logo here:

```text
templates/signature-logo.png
```

If the file has another name, pass it at startup:

```powershell
python code\main.py --mode PhD --signature-logo "C:\Path\to\logo.png"
```

Set the logo width like this:

```powershell
python code\main.py --mode PhD --signature-logo-width 180
```

The first template line may be `Subject: ...`. These placeholders are available:

- `{greeting}`
- `{company}`
- `{company_or_email}`
- `{email}`
- `{mail}`
- `{IMAGE}` in the signature for the embedded logo

## Dry Run

The default entry point is `code/main.py`. Configure normal runs in `settings.toml`.
Every setting in that file has a short explanation and its default value directly above it, so normal behavior can be changed without touching Python code.

```toml
MODE = "PhD"
RUN_AI_RESEARCH = true
SEND = false
VERBOSE = true
SAVE_VERBOSE_LOG = true
VERBOSE_LOG_DIR = "logs"
SEND_TARGET_COUNT = 0
SEND_TARGET_MAX_ROUNDS = 0
LOG_DRY_RUN = false
WRITE_SENT_LOG = true
DELETE_INPUT_AFTER_SUCCESS = false
```

Then run:

```powershell
python code\main.py
```

Without `SEND = True`, no emails are sent. With `LOG_DRY_RUN = False`, dry runs are not written to the matching CSV file.

You can also pass settings through the CLI:

```powershell
python code\main.py --mode PhD
python code\main.py --mode Freelance_German
python code\main.py --mode Freelance_English
python code\main.py --mode Auto
```

`Auto` processes every mode subfolder in `input` that contains `.csv` or `.txt` files.

With detailed output:

```powershell
python code\main.py --mode PhD --verbose
```

## Real Sending

Use `--send` to send emails through SMTP SSL:

```powershell
python code\main.py --mode PhD --send
python code\main.py --mode Freelance_German --send
python code\main.py --mode Freelance_English --send
```

Before every send, the matching CSV file is checked automatically. If an email address is already present, it is skipped and no email is prepared or sent:

```powershell
python code\main.py --mode PhD --send --verbose
```

Only use `--resend-existing` if you intentionally want to contact already logged addresses again.

For repeated research + sending until a target number is reached, set:

```toml
RUN_AI_RESEARCH = true
SEND = true
RESEARCH_WRITE_OUTPUT = true
WRITE_SENT_LOG = true
RESEND_EXISTING = false
SEND_TARGET_COUNT = 500
SEND_TARGET_MAX_ROUNDS = 0
```

`SEND_TARGET_COUNT` counts newly logged sent emails in this run. The system checks the existing `output/*.csv` sent logs before it starts, then repeats research and real sending until that many new addresses have been added. The final send round is capped automatically so it does not intentionally send past the remaining target. `SEND_TARGET_MAX_ROUNDS = 0` means unlimited rounds; even then, the loop stops if a round creates no new sent-log entries.

Before rendering or sending, each recipient email is also validated. The pipeline checks email syntax and whether the domain has MX or A DNS records. Invalid addresses are skipped and written to:

```text
output/invalid_mails.csv
```

Future runs skip addresses already listed in `invalid_mails.csv`. The sender also checks all `.csv` files in `output` for already used addresses, not just the active mode workbook. This reduces false positives, but it is not full mailbox verification: an address can still bounce even if the domain DNS is valid.

## Logs

Normal runs print status lines such as `[INFO]`, `[DRY_RUN]`, `[SENT]`, `[SKIP]`, and `[ERROR]`.
Set `VERBOSE = true` in `settings.toml` or pass `--verbose` for detailed step-by-step output about file discovery, filtering, provider calls, generated CLI arguments, validation, and skipped rows.

By default, `SAVE_VERBOSE_LOG = true` mirrors terminal output into timestamped files under:

```text
logs/
```

If `VERBOSE = true`, these saved logs also include all `[VERBOSE]` lines. If `VERBOSE = false`, the log file still contains the normal status output.

The script writes processed recipients to:

- `output/send_phd.csv` for PhD mode
- `output/send_freelance.csv` for both freelance modes
- `output/invalid_mails.csv` for invalid addresses found before rendering/sending

Only these columns are written:

- `company`
- `mail`
- `sent_at`

The invalid email log writes:

- `company`
- `mail`
- `invalid_reason`
- `detected_at`

## Research

The research tool is in `code/research/research_leads.py`. Depending on your setting, it uses Gemini or OpenAI with web search, reads existing addresses from `output/send_*.csv` and existing `input` files as an exclusion list, and writes new leads as CSV to the matching `input/<Mode>` folder.

For AI research context upload, only CV/resume/Lebenslauf files from `attachments/<Mode>` plus the matching sent CSV log are uploaded. PhD research uploads `output/send_phd.csv` when it exists. Freelance research uploads `output/send_freelance.csv` when it exists. Mail sending is separate and still uses the normal attachment folder behavior.

The prompt also tells the AI not to search for or return companies or email addresses already present in the mode-specific sent CSV list. The local parser still filters existing email addresses and mode-specific company names after the AI response.

Gemini research is configured with Google Search grounding, automatic tool use, and high thinking/reasoning. OpenAI research uses the Responses API with `web_search`, automatic tool choice, and high reasoning effort. The research provider is detected from `RESEARCH_MODEL`; use `gemini-*`, `gpt*`, `self`, an Ollama-style local model such as `llama3.1:8b`, or an explicit prefix like `ollama:qwen2.5:7b`.

```toml
RESEARCH_MODEL = "gemini-3-flash-preview"
RESEARCH_MODEL = "gpt-5.4"
RESEARCH_MODEL = "ollama:llama3.1:8b"
```

You can start research through `code/main.py`. If `RUN_AI_RESEARCH = true`, research runs first and the newly found contacts are then processed/sent.

```toml
RUN_AI_RESEARCH = true
MODE = "PhD"
RESEARCH_MODEL = "gpt-5.4"
RESEARCH_UPLOAD_ATTACHMENTS = false
```

Set `GEMINI_API_KEY` or `OPENAI_API_KEY` in `.env`, depending on the selected model/provider. The layout is documented in `.env.example`.

Direct research examples:

```powershell
python code\research\research_leads.py --mode PhD
python code\research\research_leads.py --mode Freelance_German
python code\research\research_leads.py --mode Freelance_English
python code\research\research_leads.py --model gpt-5.4 --mode PhD --no-upload-attachments
```

Test without writing output:

```powershell
python code\research\research_leads.py --mode PhD --no-write-output
```

## Quality Checks

Run the full test suite:

```powershell
python -m pytest
```

Run source coverage for the application code:

```powershell
python -m pytest --cov=main --cov=mail_sender --cov=code\research --cov-report=term-missing
```

Run the focused Ruff check for unused imports and unused production-code arguments:

```powershell
python -m ruff check code\main.py code\mail_sender code\research --select F,ARG
```
