"""LangChain agent. Claude chooses a tool, and the tool reads Chroma."""

import json
import sys
from pathlib import Path

import chromadb
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_anthropic import ChatAnthropic

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s1_detect import MODEL
from s5_index import COLLECTION, VECTOR_DIR


def chroma_collection():
    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    return client.get_collection(COLLECTION)


def filters(quality: str, date: str, reference: str) -> dict | None:
    parts = []
    if quality:
        parts.append({"quality": quality})
    if date:
        parts.append({"date": date})
    if reference:
        parts.append({"reference": reference})
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


def pack(result: dict) -> str:
    rows = []
    metadatas = result.get("metadatas") or []
    if metadatas and isinstance(metadatas[0], list):
        metadatas = metadatas[0]
    for meta in metadatas:
        if not meta:
            continue
        rows.append(
            {
                "source": meta.get("source"),
                "quality": meta.get("quality"),
                "quality_score": meta.get("quality_score"),
                "date": meta.get("date"),
                "amount": meta.get("amount"),
                "currency": meta.get("currency"),
                "reference": meta.get("reference"),
                "quality_reason": meta.get("quality_reason"),
            }
        )
    return json.dumps(rows)


@tool
def find_transactions(query: str, quality: str = "", date: str = "", reference: str = "") -> str:
    """Search scored transaction records in the vector database.

    Use quality=good for a payment, date, amount, or reference question.
    Use quality=bad when the user asks about rejected files.
    Pass date as YYYY-MM-DD when the user names a date.
    Pass reference, such as INV-1042, when the user names one.
    """
    found = chroma_collection().query(
        query_texts=[query],
        n_results=8,
        where=filters(quality, date, reference),
    )
    return pack(found)


@tool
def explain_file(source: str) -> str:
    """Return every stored record for one source file, including a bad file.

    source is the inbox file name, such as missing-reference.xml.
    """
    found = chroma_collection().get(where={"source": source})
    return pack(found)


def build_agent():
    model = ChatAnthropic(model=MODEL, max_tokens=800)
    return create_agent(
        model=model,
        tools=[find_transactions, explain_file],
        system_prompt=(
            "Answer only from the vector database tools. "
            "For a payment, date, amount, or reference question, call find_transactions "
            "and keep quality=good unless the user asks about rejected files. "
            "For why a named file failed, call explain_file. "
            "If the tool returns no rows, say the record was not found."
        ),
    )


def answer_text(message) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            parts.append(block.get("text") or "")
        else:
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def ask(question: str) -> str:
    result = build_agent().invoke({"messages": [{"role": "user", "content": question}]})
    return answer_text(result["messages"][-1])


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if question:
        print(ask(question))
        return
    print("Ask a question about the scored records. Press Enter on an empty line to stop.")
    while True:
        question = input("question: ").strip()
        if not question:
            return
        print(ask(question))
        print()


if __name__ == "__main__":
    main()
