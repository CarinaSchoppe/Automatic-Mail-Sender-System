import os

# Liste der Dateien, die verarbeitet werden sollen
# Da Duplicate_Remover.py im Root liegt, zeigen wir auf den output-Ordner.
FILES_TO_PROCESS = [
    os.path.join("output", "invalid_mails.csv"),
    os.path.join("output", "send_phd.csv"),
    os.path.join("output", "send_freelance.csv"),
]


def remove_duplicates(file_path):
    if not os.path.exists(file_path):
        print(f"Datei nicht gefunden: {file_path}")
        return

    # Datei einlesen
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    original_count = len(lines)

    # Duplikate entfernen unter Beibehaltung der Reihenfolge (dict.fromkeys ab Python 3.7+)
    # Das stellt sicher, dass der Header (die erste Zeile) oben bleibt.
    unique_lines = list(dict.fromkeys(lines))

    new_count = len(unique_lines)

    # Nur schreiben, wenn sich etwas geändert hat (optional, aber sauberer)
    if new_count < original_count:
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            f.writelines(unique_lines)
        print(f"Verarbeitet: {file_path} ({original_count} -> {new_count} Zeilen).")
    else:
        print(f"Verarbeitet: {file_path} (Keine Duplikate gefunden).")


if __name__ == "__main__":
    for file in FILES_TO_PROCESS:
        remove_duplicates(file)
    print("Alle Dateien wurden bereinigt.")
