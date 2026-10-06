"""Load scored JSON records into a local vector store."""

import json
import sys
from pathlib import Path

import chromadb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s1_detect import ROOT

JSON_DIR = ROOT / "json"
VECTOR_DIR = ROOT / "vector_db"
COLLECTION = "scored_records"


def record_text(record: dict, transaction: dict | None) -> str:
    source = record.get("source") or record.get("id") or "unknown"
    quality = record.get("quality") or "bad"
    score = record.get("quality_score")
    reason = record.get("quality_llm_reason") or ""
    if transaction is None:
        return (
            f"source {source} quality {quality} score {score} "
            f"no transactions. {reason}"
        ).strip()
    return (
        f"source {source} quality {quality} score {score} "
        f"date {transaction.get('date') or ''} "
        f"amount {transaction.get('amount')} "
        f"currency {transaction.get('currency') or ''} "
        f"reference {transaction.get('reference') or ''}. {reason}"
    ).strip()


def record_metadata(record: dict, transaction: dict | None) -> dict:
    metadata = {
        "source": str(record.get("source") or ""),
        "file_id": str(record.get("id") or ""),
        "file_type": str(record.get("file_type") or ""),
        "quality": str(record.get("quality") or "bad"),
        "quality_score": int(record.get("quality_score") or 0),
        "quality_reason": str(record.get("quality_llm_reason") or ""),
    }
    if transaction is None:
        metadata.update({"date": "", "currency": "", "reference": "", "amount": 0.0})
        return metadata
    amount = transaction.get("amount")
    metadata.update(
        {
            "date": str(transaction.get("date") or ""),
            "currency": str(transaction.get("currency") or ""),
            "reference": str(transaction.get("reference") or ""),
            "amount": float(amount) if isinstance(amount, (int, float)) else 0.0,
        }
    )
    return metadata


def documents_from_record(record: dict) -> list[tuple[str, str, dict]]:
    file_id = str(record.get("id") or record.get("source") or "record")
    transactions = record.get("transactions") or []
    rows = []
    if not transactions:
        rows.append((f"{file_id}-file", record_text(record, None), record_metadata(record, None)))
        return rows
    for index, transaction in enumerate(transactions, start=1):
        if not isinstance(transaction, dict):
            continue
        rows.append(
            (
                f"{file_id}-{index}",
                record_text(record, transaction),
                record_metadata(record, transaction),
            )
        )
    return rows


def index_scored_records(json_dir: Path = JSON_DIR, vector_dir: Path = VECTOR_DIR) -> int:
    paths = sorted(path for path in json_dir.glob("*.json") if path.is_file())
    ids = []
    texts = []
    metadatas = []
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        for doc_id, text, metadata in documents_from_record(record):
            ids.append(doc_id)
            texts.append(text)
            metadatas.append(metadata)

    vector_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(vector_dir))
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    if not ids:
        print("No scored records to index")
        return 0

    collection = client.get_or_create_collection(COLLECTION)
    collection.add(ids=ids, documents=texts, metadatas=metadatas)
    print(f"Indexed {len(ids)} records into {vector_dir}")
    return len(ids)


if __name__ == "__main__":
    index_scored_records()
