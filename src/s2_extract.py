"""Stage 2: one JSON record per inbox file, with transactions when the format has them."""

import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s1_detect import INBOX, ROOT, detect_file, inbox_files

JSON_DIR = ROOT / "json"
PDF_TRANSACTION = re.compile(
    r"Date\s+(\d{4}-\d{2}-\d{2})\s+Amount\s+([0-9]+(?:\.[0-9]+)?)\s+"
    r"Currency\s+([A-Za-z]{3})\s+Reference\s+(\S+)",
    re.IGNORECASE,
)


def extract_pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        parts = [(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return ""
    return "\n".join(parts).strip()


def transaction(date: str, amount: str, currency: str, reference: str) -> dict:
    return {
        "date": date.strip(),
        "amount": float(amount),
        "currency": currency.strip().upper(),
        "reference": reference.strip(),
    }


def child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if child.tag.lower() == name and child.text:
            return child.text.strip()
    return ""


def transactions_from_xml(path: Path) -> list[dict]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    rows = []
    for element in root.iter():
        if element.tag.lower() != "transaction":
            continue
        date = child_text(element, "date")
        amount = child_text(element, "amount")
        currency = child_text(element, "currency")
        reference = child_text(element, "reference")
        if not any((date, amount, currency, reference)):
            continue
        try:
            rows.append(transaction(date, amount, currency, reference))
        except ValueError:
            continue
    return rows


def transactions_from_csv(path: Path) -> list[dict]:
    rows = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                fields = {key.strip().lower(): (value or "").strip() for key, value in raw.items() if key}
                try:
                    rows.append(
                        transaction(
                            fields.get("date", ""),
                            fields.get("amount", ""),
                            fields.get("currency", ""),
                            fields.get("reference", ""),
                        )
                    )
                except ValueError:
                    continue
    except OSError:
        return []
    return rows


def transactions_from_pdf_text(text: str) -> list[dict]:
    rows = []
    for date, amount, currency, reference in PDF_TRANSACTION.findall(text):
        try:
            rows.append(transaction(date, amount, currency, reference))
        except ValueError:
            continue
    return rows


def build_record(path: Path) -> dict:
    file_type, _decided_by = detect_file(path)
    text = extract_pdf_text(path) if file_type == "pdf" else ""
    if file_type == "xml":
        transactions = transactions_from_xml(path)
    elif file_type == "csv":
        transactions = transactions_from_csv(path)
    elif file_type == "pdf":
        transactions = transactions_from_pdf_text(text)
    else:
        transactions = []
    return {
        "id": f"{path.stem}-{path.suffix.lower().lstrip('.') or 'file'}",
        "source": path.name,
        "file_type": file_type,
        "text": text,
        "transactions": transactions,
        "quality": None,
        "quality_score": None,
    }


def write_record(record: dict) -> Path:
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    out = JSON_DIR / f"{record['id']}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return out


def clear_previous_results() -> None:
    for folder in (JSON_DIR, ROOT / "good", ROOT / "bad"):
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            path.unlink()


def main() -> None:
    clear_previous_results()
    files = inbox_files()
    if not files:
        print(f"No files in {INBOX}")
        return

    rows = []
    for path in files:
        record = build_record(path)
        out = write_record(record)
        rows.append(
            (record["source"], record["file_type"], len(record["transactions"]), out.name)
        )

    src_width = max(len(source) for source, _, _, _ in rows)
    print(f"{'source':<{src_width}}  file_type  transactions  json")
    print(f"{'-' * src_width}  ---------  ------------  ----")
    for source, file_type, count, name in rows:
        print(f"{source:<{src_width}}  {file_type:<9}  {count:<12}  {name}")


if __name__ == "__main__":
    main()
