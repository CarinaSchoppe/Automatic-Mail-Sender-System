instructions = {
    "PhD": (
        """
        Find companies that are realistic Industry PhD collaboration prospects for applied AI governance research in Australia.

Priority order:
1. Brisbane and South East Queensland
2. Other Australian organisations
3. International organisations only if they have Australian operations, Australian partnerships, or a very strong fit for enterprise AI governance / responsible AI / GenAI risk.

Target organisations should be relevant to at least one of these:
- AI governance
- responsible AI
- enterprise AI / GenAI
- digital transformation
- compliance, risk, assurance, or cybersecurity
- university-industry research collaboration

For each company:
- include 1 general company contact email if publicly listed
- include up to 1 or 2 decision-maker work emails only if they are publicly listed on a reliable public page
- do not guess or infer email patterns
- do not include contact forms
- do not include placeholder or assumed addresses
- only include emails that are visibly written on a public webpage
- include the exact public source URL where the email was found

Exclude all emails in the exclusion list.

Use the provided files only as context for fit, not as contacts to repeat.

Return CSV only with this exact header:
company,mail,source_url

Rules:
- one row per email
- repeat company name for multiple emails
- if you cannot verify enough results, return fewer results
- no markdown
- no commentary
- no extra text
        """),
    "Freelance German": (
        """Finde deutschsprachige Organisationen, die mit einer remote arbeitenden freiberuflichen Dozentin oder Trainerin zusammenarbeiten könnten.

    Priorität:
    - Bildungsträger
    - AVGS-/AZAV-Träger
    - öffentlich geförderte Weiterbildungsträger
    - Berufsausbildungs- und Umschulungsanbieter
    - Corporate-Training-Anbieter
    - Anbieter mit Remote-, Online- oder Homeoffice-kompatiblen Lehrformaten

    Berücksichtige bevorzugt Organisationen in:
    - Deutschland
    - Schweiz
    - Österreich
    - Luxemburg

    Berücksichtige nur Organisationen, deren Kurs- oder Leistungsportfolio klar zu mindestens einem dieser Themen passt:
    - IT
    - Softwareentwicklung
    - KI / AI
    - Daten / Analytics / BI
    - Cybersecurity / IT-Security
    - digitale Wirtschaftskompetenzen
    - kaufmännische oder betriebswirtschaftliche Weiterbildung mit starkem Digitalbezug

    Nutze die bereitgestellten Dateien nur, um das Profil, die Themen und den fachlichen Fit besser zu verstehen.

    Für jedes Unternehmen:
    - nenne 1 relevante öffentliche E-Mail-Adresse
    - optional eine zweite öffentliche E-Mail-Adresse, wenn sie klar passend ist
    - keine Kontaktformulare
    - keine geratenen oder aus Mustern abgeleiteten E-Mail-Adressen
    - nur E-Mail-Adressen, die sichtbar auf einer öffentlichen Webseite stehen
    - gib die exakte öffentliche source_url an, auf der die E-Mail gefunden wurde

    Schließe alle E-Mail-Adressen aus der Exclusion-Liste aus.

    Gib ausschließlich CSV mit diesem exakten Header zurück:
    company,mail,source_url

    Regeln:
    - eine Zeile pro E-Mail-Adresse
    - bei mehreren E-Mails pro Unternehmen den Unternehmensnamen je Zeile wiederholen
    - wenn nicht genug verifizierbare Ergebnisse gefunden werden, weniger Ergebnisse statt geratener Ergebnisse zurückgeben
    - kein Markdown
    - keine Kommentare
    - kein zusätzlicher Text"""
    ),
    "Freelance English": (
        """Find organisations that may hire or collaborate with a remote freelance lecturer or trainer in IT, business, AI, software, data, or cybersecurity.

Prioritise:
- education providers
- vocational training providers
- reskilling providers
- corporate training providers
- apprenticeship or adult-learning providers
- organisations that offer remote or online teaching opportunities

Use the provided files only to understand the trainer profile and topic fit.

Find only organisations whose course portfolio clearly overlaps with:
- IT
- software development
- AI
- data / analytics
- cybersecurity
- digital business skills

For each company:
- include 1 relevant public email address
- optionally include a second public email address if clearly relevant
- do not guess or infer email patterns
- do not include contact forms
- only include emails visibly shown on a public webpage
- include the exact source URL

Exclude all emails in the exclusion list.

Return CSV only with this exact header:
company,mail,source_url

Rules:
- one row per email
- repeat company name for multiple emails
- if you cannot verify enough results, return fewer results
- no markdown
- no commentary
- no extra text """
    )}
