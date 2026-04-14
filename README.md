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

CSV files exported from Excel with semicolons also work as long as they contain a `mail` column. `email` is accepted for compatibility.

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

The default entry point is `code/main.py`. Configure normal runs in `settings.toml`:

```toml
MODE = "PhD"
RUN_AI_RESEARCH = true
SEND = false
VERBOSE = true
LOG_DRY_RUN = false
WRITE_SENT_LOG = true
DELETE_INPUT_AFTER_SUCCESS = false
```

Then run:

```powershell
python code\main.py
```

Without `SEND = True`, no emails are sent. With `LOG_DRY_RUN = False`, dry runs are not written to the matching Excel file.

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

Before every send, the matching Excel file is checked automatically. If an email address is already present, it is skipped and no email is prepared or sent:

```powershell
python code\main.py --mode PhD --send --verbose
```

Only use `--resend-existing` if you intentionally want to contact already logged addresses again.

Before rendering or sending, each recipient email is also validated. The pipeline checks email syntax and whether the domain has MX or A DNS records. Invalid addresses are skipped and written to:

```text
output/invalid_mails.xlsx
```

Future runs skip addresses already listed in `invalid_mails.xlsx`. The sender also checks all `.xlsx` files in `output` for already used addresses, not just the active mode workbook. This reduces false positives, but it is not full mailbox verification: an address can still bounce even if the domain DNS is valid.

## Logs

The script writes processed recipients to:

- `output/send_phd.xlsx` for PhD mode
- `output/send_freelance.xlsx` for both freelance modes
- `output/invalid_mails.xlsx` for invalid addresses found before rendering/sending

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

The research tool is in `code/research/research_leads.py`. Depending on your setting, it uses Gemini or OpenAI with web search, can upload matching files from `attachments/<Mode>` as context, reads existing addresses from `output/send_*.xlsx` and existing `input` files as an exclusion list, and writes new leads as CSV to the matching `input/<Mode>` folder.

You can start research through `code/main.py`. If `RUN_AI_RESEARCH = true`, research runs first and the newly found contacts are then processed/sent.

```toml
RUN_AI_RESEARCH = true
MODE = "PhD"
RESEARCH_AI_PROVIDER = "openai"
RESEARCH_UPLOAD_ATTACHMENTS = false
```

Set `GEMINI_API_KEY` or `OPENAI_API_KEY` in `.env`, depending on the provider. The layout is documented in `.env.example`. For OpenAI, `OPENAI_MODEL=gpt-5.4` is the default.

Direct research examples:

```powershell
python code\research\research_leads.py --mode PhD
python code\research\research_leads.py --mode Freelance_German
python code\research\research_leads.py --mode Freelance_English
python code\research\research_leads.py --provider openai --mode PhD --no-upload-attachments
```

Test without writing output:

```powershell
python code\research\research_leads.py --mode PhD --no-write-output
```
