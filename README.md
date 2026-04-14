# MailSenderSystem

Python pipeline for researching leads and sending PhD or freelance email batches via SMTPS.

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
python main.py --mode PhD --signature-logo "C:\Path\to\logo.png"
```

Set the logo width like this:

```powershell
python main.py --mode PhD --signature-logo-width 180
```

The first template line may be `Subject: ...`. These placeholders are available:

- `{greeting}`
- `{company}`
- `{company_or_email}`
- `{email}`
- `{mail}`
- `{IMAGE}` in the signature for the embedded logo

## Dry Run

The default entry point is `main.py`. Configure the top of `main.py`:

```python
MODE = "PhD"        # or "Freelance_German", "Freelance_English", "Auto"
RUN_AI_RESEARCH = True # True = run AI research first, then process/send emails
SEND = False        # False = dry run, True = real sending
VERBOSE = True
LOG_DRY_RUN = False # False = do not write dry runs to Excel
WRITE_SENT_LOG = True # True = write real sends to output/send_*.xlsx
DELETE_INPUT_AFTER_SUCCESS = True # True = delete input files after successful real sending
```

Then run:

```powershell
python main.py
```

Without `SEND = True`, no emails are sent. With `LOG_DRY_RUN = False`, dry runs are not written to the matching Excel file.

You can also pass settings through the CLI:

```powershell
python main.py --mode PhD
python main.py --mode Freelance_German
python main.py --mode Freelance_English
python main.py --mode Auto
```

`Auto` processes every mode subfolder in `input` that contains `.csv` or `.txt` files.

With detailed output:

```powershell
python main.py --mode PhD --verbose
```

## Real Sending

Use `--send` to send emails through SMTP SSL:

```powershell
python main.py --mode PhD --send
python main.py --mode Freelance_German --send
python main.py --mode Freelance_English --send
```

Before every send, the matching Excel file is checked automatically. If an email address is already present, it is skipped and no email is prepared or sent:

```powershell
python main.py --mode PhD --send --verbose
```

Only use `--resend-existing` if you intentionally want to contact already logged addresses again.

## Logs

The script writes processed recipients to:

- `output/send_phd.xlsx` for PhD mode
- `output/send_freelance.xlsx` for both freelance modes

Only these columns are written:

- `company`
- `mail`
- `sent_at`

## Research

The research tool is in `research/research_leads.py`. Depending on your setting, it uses Gemini or OpenAI with web search, can upload matching files from `attachments/<Mode>` as context, reads existing addresses from `output/send_*.xlsx` and existing `input` files as an exclusion list, and writes new leads as CSV to the matching `input/<Mode>` folder.

You can start research through `main.py`. If `RUN_AI_RESEARCH = True`, research runs first and the newly found contacts are then processed/sent.

```python
RUN_AI_RESEARCH = True
MODE = "PhD"  # or "Freelance_German" / "Freelance_English"
RESEARCH_AI_PROVIDER = "openai" # or "gemini"
RESEARCH_UPLOAD_ATTACHMENTS = False # True = upload attachments to the AI provider
```

Set `GEMINI_API_KEY` or `OPENAI_API_KEY` in `.env`, depending on the provider. The layout is documented in `.env.example`. For OpenAI, `OPENAI_MODEL=gpt-5.4` is the default.

Direct research examples:

```powershell
python research\research_leads.py --mode PhD
python research\research_leads.py --mode Freelance_German
python research\research_leads.py --mode Freelance_English
python research\research_leads.py --provider openai --mode PhD --no-upload-attachments
```

Test without writing output:

```powershell
python research\research_leads.py --mode PhD --no-write-output
```
