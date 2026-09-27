"""Stage 3: code score first, LLM only when text is not empty."""

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s1_detect import MODEL, ROOT

JSON_DIR = ROOT / "json"
GOOD_DIR = ROOT / "good"
BAD_DIR = ROOT / "bad"
THRESHOLD = 70
MIN_CHARS = 50


def score_text(text: str) -> int:
    stripped = text.strip()
    if len(stripped) < MIN_CHARS:
        return 0

    visible = [char for char in stripped if not char.isspace()]
    if not visible:
        return 0

    letters = sum(char.isalpha() for char in visible)
    return round(100 * letters / len(visible))


def judge_text(text: str) -> tuple[str, str]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("missing API key")

    from anthropic import Anthropic

    message = Anthropic().messages.create(
        model=MODEL,
        max_tokens=80,
        messages=[
            {
                "role": "user",
                "content": (
                    "You check extracted document text.\n"
                    "Reply with exactly two lines.\n"
                    "Line 1: good or bad\n"
                    "Line 2: one short reason\n"
                    "good means readable document sentences. "
                    "bad means symbols or garbage.\n\n"
                    f"Text:\n{text[:2000]}"
                ),
            }
        ],
    )
    lines = [line.strip() for line in message.content[0].text.splitlines() if line.strip()]
    verdict = lines[0].lower().strip(".,") if lines else "bad"
    if verdict not in {"good", "bad"}:
        verdict = "bad"
    reason = lines[1] if len(lines) > 1 else ""
    return verdict, reason


def apply_quality(record: dict) -> dict:
    text = record.get("text") or ""
    score = score_text(text)
    rules = "good" if score >= THRESHOLD else "bad"
    record["quality_score"] = score
    record["quality_rules"] = rules

    if not text.strip():
        record["quality_llm"] = None
        record["quality_llm_reason"] = "skipped because text is empty"
        record["quality"] = "bad"
        return record

    try:
        verdict, reason = judge_text(text)
    except Exception:
        record["quality_llm"] = None
        record["quality_llm_reason"] = "API unavailable; code score used"
        record["quality"] = rules
        return record

    record["quality_llm"] = verdict
    record["quality_llm_reason"] = reason
    record["quality"] = "good" if rules == "good" and verdict == "good" else "bad"
    return record


def json_records() -> list[Path]:
    return sorted(
        path
        for path in JSON_DIR.glob("*.json")
        if path.is_file() and not path.name.startswith(".")
    )


def place_record(path: Path, record: dict) -> Path:
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    GOOD_DIR.mkdir(parents=True, exist_ok=True)
    BAD_DIR.mkdir(parents=True, exist_ok=True)
    target_dir = GOOD_DIR if record["quality"] == "good" else BAD_DIR
    other_dir = BAD_DIR if target_dir == GOOD_DIR else GOOD_DIR
    target = target_dir / path.name
    shutil.copyfile(path, target)
    stale = other_dir / path.name
    if stale.exists():
        stale.unlink()
    return target


def main() -> None:
    paths = json_records()
    if not paths:
        print(f"No JSON files in {JSON_DIR}")
        return

    rows = []
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        record = apply_quality(record)
        target = place_record(path, record)
        rows.append(
            (
                record["id"],
                record["quality_score"],
                record["quality_rules"],
                record["quality_llm"] or "-",
                record["quality"],
                f"{target.parent.name}/",
            )
        )

    id_width = max(len(row[0]) for row in rows)
    print(f"{'id':<{id_width}}  score  rules  llm   final  folder")
    print(f"{'-' * id_width}  -----  -----  ----  -----  ------")
    for record_id, score, rules, llm, final, folder in rows:
        print(
            f"{record_id:<{id_width}}  {score:<5}  {rules:<5}  {llm:<4}  {final:<5}  {folder}"
        )


if __name__ == "__main__":
    main()
