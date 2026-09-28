"""Stage 1: rules first, AI only when the rules miss."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"
ALLOWED_TYPES = {"pdf", "xml", "csv", "txt", "docx", "html", "image", "unknown"}
RULED_TYPES = {".pdf": "pdf", ".xml": "xml", ".csv": "csv"}
MODEL = "claude-haiku-4-5"

load_dotenv(ROOT / ".env")


def detect_by_rules(path: Path) -> str | None:
    return RULED_TYPES.get(path.suffix.lower())


def classify_with_ai(path: Path) -> str:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("missing API key")

    from anthropic import Anthropic

    sample = path.read_bytes()[:500].decode("utf-8", errors="replace")
    message = Anthropic().messages.create(
        model=MODEL,
        max_tokens=16,
        messages=[
            {
                "role": "user",
                "content": (
                    "Classify this file format. Reply with one word only: "
                    "pdf, txt, docx, html, image, or unknown.\n"
                    f"Filename: {path.name}\n"
                    f"Sample:\n{sample}"
                ),
            }
        ],
    )
    word = message.content[0].text.strip().lower().split()[0].strip(".,")
    if word not in ALLOWED_TYPES:
        return "unknown"
    return word


def detect_file(path: Path) -> tuple[str, str]:
    ruled = detect_by_rules(path)
    if ruled is not None:
        return ruled, "rules"

    try:
        return classify_with_ai(path), "ai"
    except Exception:
        return "unknown", "ai_failed"


def inbox_files(inbox: Path = INBOX) -> list[Path]:
    return sorted(
        path
        for path in inbox.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )


def main() -> None:
    files = inbox_files()
    if not files:
        print(f"No files in {INBOX}")
        return

    rows = [(path.name, *detect_file(path)) for path in files]
    name_width = max(len(name) for name, _, _ in rows)
    print(f"{'file':<{name_width}}  file_type  decided_by")
    print(f"{'-' * name_width}  ---------  ----------")
    for name, file_type, decided_by in rows:
        print(f"{name:<{name_width}}  {file_type:<9}  {decided_by}")


if __name__ == "__main__":
    main()
