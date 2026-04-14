# MailSenderSystem

Python-Pipeline zum Versenden von PhD- oder Freelance-Mail-Batches per SMTPS.

## Einrichtung

1. Virtuelle Umgebung erstellen und Abhaengigkeiten installieren:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. `.env.example` nach `.env` kopieren und `SMTP_PASSWORD` lokal eintragen.

3. Empfaengerdateien im passenden `input`-Unterordner ablegen. Es werden alle `.csv` und `.txt` Dateien im gewaehlten Modusordner eingelesen:

- `input/PhD`
- `input/Freelance_German`
- `input/Freelance_English`

Empfohlenes Format:

```csv
company,mail
Example GmbH,max@example.com
```

CSV-Dateien mit Semikolon aus Excel funktionieren ebenfalls, solange eine `mail`-Spalte vorhanden ist. `email` wird aus Kompatibilitaetsgruenden auch noch akzeptiert.

4. Alle PhD-Anhaenge nach `attachments/PhD` legen.

5. Alle deutschen Freelance-Anhaenge nach `attachments/Freelance_German` legen.

6. Alle englischen Freelance-Anhaenge nach `attachments/Freelance_English` legen.

7. Mailtexte und Signatur bearbeiten:

- `templates/phd.txt`
- `templates/freelance_german.txt`
- `templates/freelance_english.txt`
- `templates/signature.txt`

Die Zuordnung ist:

- `MODE = "Freelance_German"` nutzt `templates/freelance_german.txt` und `attachments/Freelance_German`
- `MODE = "Freelance_English"` nutzt `templates/freelance_english.txt` und `attachments/Freelance_English`

Die Signatur enthaelt `{IMAGE}` fuer dein Logo. Lege das Logo standardmaessig hier ab:

```text
templates/signature-logo.png
```

Falls die Datei anders heisst, gib sie beim Start an:

```powershell
python main.py --mode PhD --signature-logo "C:\Pfad\zum\logo.png"
```

Die Logo-Breite kannst du so setzen:

```powershell
python main.py --mode PhD --signature-logo-width 180
```

Die erste Zeile darf `Subject: ...` sein. Diese Platzhalter sind verfuegbar:

- `{greeting}`
- `{company}`
- `{company_or_email}`
- `{email}`
- `{mail}`
- `{IMAGE}` in der Signatur fuer das eingebettete Logo

## Probelauf

Der Standardweg ist `main.py`. Stelle oben in `main.py` ein:

```python
MODE = "PhD"        # oder "Freelance_German", "Freelance_English", "Auto"
RUN_AI_RESEARCH = False # False = Mail-Sender, True = AI Research
SEND = False        # False = Probelauf, True = echt senden
VERBOSE = True
LOG_DRY_RUN = False # False = Probelauf nicht in Excel schreiben
WRITE_SENT_LOG = True # True = echte Sendungen in output/send_*.xlsx schreiben
DELETE_INPUT_AFTER_SUCCESS = True # True = Input-Dateien nach erfolgreichem echtem Versand loeschen
```

Dann starten:

```powershell
python main.py
```

Ohne `SEND = True` werden keine Mails versendet. Mit `LOG_DRY_RUN = False` wird der Probelauf auch nicht in die passende Excel-Datei geschrieben.

Du kannst die Einstellungen alternativ weiterhin per CLI uebergeben:

```powershell
python main.py --mode PhD
python main.py --mode Freelance_German
python main.py --mode Freelance_English
python main.py --mode Auto
```

`Auto` verarbeitet alle Modus-Unterordner in `input`, in denen `.csv` oder `.txt` Dateien liegen.

Mit vielen Detailausgaben:

```powershell
python main.py --mode PhD --verbose
```

## Echt versenden

Mit `--send` werden die Mails wirklich ueber SMTP SSL verschickt:

```powershell
python main.py --mode PhD --send
python main.py --mode Freelance_German --send
python main.py --mode Freelance_English --send
```

Vor jedem Versand wird automatisch die passende Excel-Datei geprueft. Wenn eine Email-Adresse dort bereits steht, wird sie uebersprungen und nicht erneut vorbereitet oder versendet:

```powershell
python main.py --mode PhD --send --verbose
```

Nur wenn du bewusst erneut an bereits protokollierte Adressen senden willst, kannst du den Schutz mit `--resend-existing` ausschalten.

## Protokolle

Das Script schreibt jeden verarbeiteten Empfaenger in:

- `output/send_phd.xlsx` fuer den PhD-Modus
- `output/send_freelance.xlsx` fuer beide Freelance-Modi

In diese Excel-Dateien werden nur diese Spalten geschrieben:

- `Unternehmen`
- `mail`
- `sent_at`

## Research

Das Research-Tool liegt in `Research/research_leads.py`. Es nutzt je nach Einstellung Gemini oder OpenAI mit Websuche, kann die passenden Dateien aus `attachments/<Mode>` als Kontext hochladen, liest bestehende Adressen aus `output/send_*.xlsx` und vorhandenen `input`-Dateien als Ausschlussliste und schreibt neue Leads als CSV in den passenden `input/<Mode>` Ordner.

Du kannst Research auch direkt ueber `main.py` starten:

```python
RUN_AI_RESEARCH = True
MODE = "PhD"  # oder "Freelance_German" / "Freelance_English"
RESEARCH_AI_PROVIDER = "openai" # oder "gemini"
RESEARCH_UPLOAD_ATTACHMENTS = False # True = Attachments an den AI Provider hochladen
```

Vorher je nach Provider `GEMINI_API_KEY` oder `OPENAI_API_KEY` in `.env` setzen. Das Layout steht in `.env.example`. Fuer OpenAI ist `OPENAI_MODEL=gpt-5.4` voreingestellt.

Beispiele:

```powershell
python Research\research_leads.py --mode PhD
python Research\research_leads.py --mode Freelance_German
python Research\research_leads.py --mode Freelance_English
python Research\research_leads.py --provider openai --mode PhD --no-upload-attachments
```

Ohne Schreiben testen:

```powershell
python Research\research_leads.py --mode PhD --no-write-output
```
