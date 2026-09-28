"""Summarize good and bad files. Bad names are printed in red."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s1_detect import MODEL, ROOT

JSON_DIR = ROOT / "json"
RED = "\033[31m"
RESET = "\033[0m"


def record_paths(folder: Path) -> list[Path]:
    direct = sorted(path for path in folder.glob("*.json") if path.is_file())
    if direct:
        return direct
    return sorted(path for path in folder.glob("json/*.json") if path.is_file())


def load_records(folder: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in record_paths(folder)]


def fallback(record: dict) -> tuple[str, str]:
    if record.get("file_type") in {"xml", "csv"} or record.get("transactions"):
        transactions = record.get("transactions") or []
        if not transactions:
            return (
                "No transactions could be read from the file.",
                "Replace it with a valid statement that has date, amount, currency, and reference.",
            )
        blank_reference = any(
            not str(item.get("reference") or "").strip() for item in transactions if isinstance(item, dict)
        )
        if blank_reference:
            return (
                "One transaction has a blank reference number.",
                "Add a reference like INV-1042 on that transaction and run the pipeline again.",
            )
        return (
            "One or more transactions are missing a date, amount, currency, or reference number.",
            "Correct those fields and run the pipeline again.",
        )
    text = (record.get("text") or "").strip()
    file_type = record.get("file_type") or "unknown"
    if not text and file_type != "pdf":
        return (
            "The file is not a PDF, so no text was extracted.",
            "Submit a digital PDF, or extend extraction to this file type.",
        )
    if not text:
        return (
            "The PDF has no extractable text.",
            "Replace it with a digital PDF that contains a text layer.",
        )
    if record.get("quality_rules") == "bad":
        return (
            "The extracted text is mostly symbols or too short to use.",
            "Replace the source file with readable text and run the pipeline again.",
        )
    return (
        "The quality checks did not both pass.",
        "Fix the source text and run the pipeline again.",
    )


def ask_claude(records: list[dict]) -> dict[str, dict]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("missing API key")

    from anthropic import Anthropic

    payload = []
    for record in records:
        payload.append(
            {
                "source": record.get("source"),
                "file_type": record.get("file_type"),
                "quality": record.get("quality"),
                "quality_score": record.get("quality_score"),
                "quality_rules": record.get("quality_rules"),
                "quality_llm": record.get("quality_llm"),
                "quality_llm_reason": record.get("quality_llm_reason"),
                "text_preview": (record.get("text") or "")[:400],
                "transactions": (record.get("transactions") or [])[:5],
            }
        )
    message = Anthropic().messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[
            {
                "role": "user",
                "content": (
                    "You explain ingest quality results.\n"
                    "Return only a JSON array. One object per file.\n"
                    'Each object has keys "source", "root_cause", "mitigation".\n'
                    "Use the source value exactly.\n"
                    "For a good file, root_cause and mitigation are empty strings.\n"
                    "For a bad file, root_cause is one sentence and mitigation is one sentence.\n"
                    "Do not change which files are good or bad.\n\n"
                    f"{json.dumps(payload)}"
                ),
            }
        ],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    parsed = json.loads(raw)
    return {item["source"]: item for item in parsed if isinstance(item, dict) and item.get("source")}


def explain(records: list[dict]) -> list[dict]:
    try:
        advice = ask_claude(records)
    except Exception:
        advice = {}

    rows = []
    for record in records:
        source = record.get("source") or record.get("id") or "unknown"
        result = record.get("quality") or "bad"
        item = advice.get(source, {})
        if result == "bad":
            cause = (item.get("root_cause") or "").strip()
            fix = (item.get("mitigation") or "").strip()
            if not cause or not fix:
                cause, fix = fallback(record)
        else:
            cause = ""
            fix = ""
        rows.append(
            {
                "source": source,
                "result": result,
                "root_cause": cause,
                "mitigation": fix,
            }
        )
    return rows


def cell(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ")


def display_name(source: str, result: str) -> str:
    if result == "bad":
        return f"{RED}{source}{RESET}"
    return source


def write_step_summary(rows: list[dict]) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Quality summary",
        "",
        "| File | Result | Root cause | Mitigation |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        name = row["source"]
        if row["result"] == "bad":
            name = f'<span style="color:#d1242f"><strong>{name}</strong></span>'
        lines.append(
            f"| {name} | {row['result']} | {cell(row['root_cause'])} | {cell(row['mitigation'])} |"
        )
    lines.append("")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else JSON_DIR
    records = load_records(folder)
    if not records:
        print(f"No JSON records in {folder}")
        return

    rows = explain(records)
    good = sum(row["result"] == "good" for row in rows)
    bad = len(rows) - good
    print(f"Quality summary: {good} good, {bad} bad")
    print()
    for row in rows:
        print(display_name(row["source"], row["result"]))
        print(f"  result: {row['result']}")
        if row["result"] == "bad":
            print(f"  root cause: {row['root_cause']}")
            print(f"  mitigation: {row['mitigation']}")
            cause = row["root_cause"].replace("\n", " ")
            fix = row["mitigation"].replace("\n", " ")
            print(f"::error title={row['source']}::Root cause: {cause} Mitigation: {fix}")
        print()
    write_step_summary(rows)


if __name__ == "__main__":
    main()
