import csv

from mail_sender.sent_log import deduplicate_all_output_logs


def test_deduplicate_all_output_logs(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    file1 = output_dir / "send_1.csv"
    file2 = output_dir / "send_2.csv"
    invalid_file = output_dir / "invalid_mails.csv"

    headers = ["company", "mail", "sent_at"]

    # File 1 has internal duplicates
    with file1.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(["Comp1", "dup@test.com", "2024-04-19T10:00"])
        writer.writerow(["Comp1", "dup@test.com", "2024-04-19T10:01"])
        writer.writerow(["Comp2", "unique1@test.com", "2024-04-19T10:02"])

    # File 2 has a duplicate across files
    with file2.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(["Comp3", "dup@test.com", "2024-04-19T10:03"])
        writer.writerow(["Comp4", "unique2@test.com", "2024-04-19T10:04"])

    # Invalid file should be ignored
    with invalid_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "mail", "reason", "at"])
        writer.writerow(["Comp5", "dup@test.com", "bad", "now"])
        writer.writerow(["Comp5", "dup@test.com", "bad", "now"])

    # Run deduplication
    deduplicate_all_output_logs(output_dir)

    # Verify File 1: Should have dup@test.com once and unique1@test.com
    with file1.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 2
        emails = [r["mail"] for r in rows]
        assert "dup@test.com" in emails
        assert "unique1@test.com" in emails

    # Verify File 2: Should have only unique2@test.com (dup@test.com was in file 1 already)
    with file2.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["mail"] == "unique2@test.com"

    # Verify Invalid file: Should remain untouched (not deduplicated)
    with invalid_file.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
        assert len(rows) == 3  # Header + 2 rows
