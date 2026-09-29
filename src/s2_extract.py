"""Stage 2: one JSON record per inbox file, with transactions when the format has them."""

import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s1_detect import INBOX, MODEL, ROOT, detect_file, inbox_files

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


def source_text(path: Path, file_type: str, pdf_text: str) -> str:
    if file_type == "pdf":
        return pdf_text
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def normalise_ai_rows(parsed: object) -> list[dict]:
    if not isinstance(parsed, list):
        raise ValueError("model did not return a list")
    rows = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                transaction(
                    str(item.get("date") or ""),
                    str(item.get("amount") or ""),
                    str(item.get("currency") or ""),
                    str(item.get("reference") or ""),
                )
            )
        except ValueError:
            continue
    return rows


def transactions_from_ai(source_name: str, raw: str) -> list[dict]:
    if not raw.strip():
        return []
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("missing API key")

    from anthropic import Anthropic

    message = Anthropic().messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[
            {
                "role": "user",
                "content": (
                    "Map this financial file into transactions by meaning, not by exact field name.\n"
                    "Read each label and value. If a field means a date, put it in date. "
                    "If it means an amount of money, put it in amount. "
                    "If it means a currency, put it in currency. "
                    "If it means a payment or invoice reference, put it in reference.\n"
                    "The label can be anything. transactiondate is only one example of a date. "
                    "booking date, value date, posted on, and similar wording are dates too. "
                    "Do the same for amount, currency, and reference.\n"
                    "Return only a JSON array. Each object has exactly these keys: "
                    "date (YYYY-MM-DD), amount (number), currency (3 letters), reference (string).\n"
                    "Do not include description or any other field.\n"
                    "Copy only values that are in the file. Do not invent amounts or references.\n"
                    "If a reference is blank, use an empty string.\n"
                    "If there are no transactions, return [].\n\n"
                    f"File: {source_name}\n"
                    f"{raw[:6000]}"
                ),
            }
        ],
    )
    reply = message.content[0].text.strip()
    if reply.startswith("```"):
        reply = reply.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return normalise_ai_rows(json.loads(reply))


def transactions_from_python(path: Path, file_type: str, pdf_text: str) -> list[dict]:
    if file_type == "xml":
        return transactions_from_xml(path)
    if file_type == "csv":
        return transactions_from_csv(path)
    if file_type == "pdf":
        return transactions_from_pdf_text(pdf_text)
    return []


def build_record(path: Path) -> dict:
    file_type, _decided_by = detect_file(path)
    text = extract_pdf_text(path) if file_type == "pdf" else ""
    raw = source_text(path, file_type, text)
    extracted_by = "python"
    if file_type in {"xml", "csv", "pdf"} and raw.strip():
        try:
            transactions = transactions_from_ai(path.name, raw)
            extracted_by = "ai"
        except Exception:
            transactions = transactions_from_python(path, file_type, text)
    else:
        transactions = []
    return {
        "id": f"{path.stem}-{path.suffix.lower().lstrip('.') or 'file'}",
        "source": path.name,
        "file_type": file_type,
        "text": text,
        "transactions": transactions,
        "extracted_by": extracted_by,
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
            (
                record["source"],
                record["file_type"],
                len(record["transactions"]),
                record["extracted_by"],
                out.name,
            )
        )

    src_width = max(len(source) for source, _, _, _, _ in rows)
    print(f"{'source':<{src_width}}  file_type  transactions  extracted_by  json")
    print(f"{'-' * src_width}  ---------  ------------  ------------  ----")
    for source, file_type, count, extracted_by, name in rows:
        print(f"{source:<{src_width}}  {file_type:<9}  {count:<12}  {extracted_by:<12}  {name}")


if __name__ == "__main__":
    main()
