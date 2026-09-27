"""Stage 2: copy PDF text into one JSON record per inbox file."""

import json
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s1_detect import INBOX, ROOT, detect_file, inbox_files

JSON_DIR = ROOT / "json"


def extract_pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        parts = [(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return ""
    return "\n".join(parts).strip()


def build_record(path: Path) -> dict:
    file_type, _decided_by = detect_file(path)
    text = extract_pdf_text(path) if file_type == "pdf" else ""
    return {
        "id": path.stem,
        "source": path.name,
        "file_type": file_type,
        "text": text,
        "quality": None,
        "quality_score": None,
    }


def write_record(record: dict) -> Path:
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    out = JSON_DIR / f"{record['id']}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    files = inbox_files()
    if not files:
        print(f"No files in {INBOX}")
        return

    rows = []
    for path in files:
        record = build_record(path)
        out = write_record(record)
        rows.append((record["source"], record["file_type"], len(record["text"]), out.name))

    src_width = max(len(source) for source, _, _, _ in rows)
    print(f"{'source':<{src_width}}  file_type  chars  json")
    print(f"{'-' * src_width}  ---------  -----  ----")
    for source, file_type, chars, name in rows:
        print(f"{source:<{src_width}}  {file_type:<9}  {chars:<5}  {name}")


if __name__ == "__main__":
    main()
