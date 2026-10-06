# Pilot: AI-enabled unstructured data handling

Mixed financial files in `inbox/` become one JSON shape. Python writes the files and enforces the rules. Claude maps fields and gives a second opinion. Records that pass both checks are copied to `good/`. Every scored record, passing or not, is then loaded into a local Chroma database. The chat page answers questions from that database.

Each transaction keeps four fields only: `date`, `amount`, `currency`, and `reference`. A description or any other source field is left out.

## Pipeline

| Stage | What it does | Python or hybrid | Benefit |
| --- | --- | --- | --- |
| Stage 1 — format detection | Python reads the extension. `.pdf`, `.xml`, and `.csv` are decided by that rule. Claude is called only when the extension is not one of those. If that call fails, the file is `unknown`. | Hybrid | Known formats are instant and repeatable. Claude is used only for a file the rules do not already recognise. |
| Stage 2 — extract to JSON | Claude maps any date-like, amount-like, currency-like, or reference-like label into `date`, `amount`, `currency`, and `reference`. Python writes one file per source into `json/` and sets `extracted_by` to `ai`. If Claude is unavailable, Python’s parsers fill the transactions and set `extracted_by` to `python`. | Hybrid | Labels such as `Txnamt`, `TransactionDate`, `Ccy`, and `PaymentRef` still become the same four JSON fields. The run still produces JSON when the model is down. |
| Stage 3 — quality gate | Python scores every row. A file passes only when every transaction has a date as `YYYY-MM-DD`, a numeric amount, a 3-letter currency, and a reference like `INV-1042`. Claude then gives a second good or bad verdict. Both must pass for `good/`. A miss goes to `bad/`. If the API is down, the Python score is the result. | Hybrid | A blank reference or a broken file cannot pass. The score and verdict are stored on the JSON. |
| Stage 5 — index | At the end of Stage 3, `src/s5_index.py` reads every file in `json/`. Each transaction becomes one sentence. Chroma turns that sentence into a vector and stores it in `vector_db/`, collection `scored_records`. A file with no transactions becomes one vector for the file. The collection is rebuilt on every run. | Python | Good and bad records can be searched by meaning, and filtered by quality, date, or reference, without opening the JSON files. |
| Stage 4 — summary | `src/s4_summary.py`. Claude writes a root cause and a mitigation for each bad file. Python prints the list, colours bad names red, and writes the same table into the GitHub job summary. If Claude fails, Python supplies the root cause and mitigation from the score. | Hybrid | Every run shows which files passed, which failed, why, and what to fix. |
| Chat | `src/chat.py` keeps a FastAPI page running. A question goes to the LangChain agent in `src/agent.py`. Claude chooses a tool, the tool reads Chroma, and Claude writes the reply from those rows. | Hybrid | Someone can ask about a payment or a rejected file without starting the agent, and without reading `json/`. |

Model: `claude-haiku-4-5`. Stage 5 does not call it. Chroma embeds each sentence with its built-in MiniLM model.

Stage 5 runs at the end of the Stage 3 script, before the Stage 4 job. Its file is `src/s5_index.py` because the summary script was already `src/s4_summary.py`.

## Flow

1. **Format check.** Stage 1 sets the type from the extension. Claude is used only when the extension is not pdf, xml, or csv.
2. **Fetch and convert to JSON.** Stage 2 reads the file. Claude maps the fields. Python writes `json/<id>.json` and sets `extracted_by`. `quality` and `quality_score` are still `null` here.
3. **Quality check.** Stage 3 scores that JSON. Python sets `quality_score`. Claude sets `quality_llm` to good or bad.
4. **Fill the same JSON.** Stage 3 writes those fields back into the file from step 2, then copies it to `good/` or `bad/`.
5. **Index.** Stage 5 reads those scored JSON files and rebuilds the Chroma collection. This runs inside the Stage 3 script. It is not a separate workflow job.
6. **Summary.** The Summary job reads the finished files and lists what passed, what failed, why, and what to fix.
7. **Ask.** With the chat server running, a question on the page goes to the agent, which answers from Chroma.

The id is the file stem plus the extension, so `statement.xml` becomes `statement-xml.json` and does not overwrite `statement-pdf.json`.

## Where the JSON file is written

Python creates the file. Claude supplies the transaction values inside it.

Stage 2 writes the file in `write_record` in `src/s2_extract.py`:

```python
out = JSON_DIR / f"{record['id']}.json"
out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
```

Stage 3 updates that same file in `place_record` in `src/s3_quality.py`, then copies it to `good/` or `bad/`.

`json.dumps` writes the Python dictionary. It does not add fields of its own.

### Fields written in Stage 2

| Field | What is in it |
| --- | --- |
| `id` | File name plus type, such as `transactions-csv` |
| `source` | Original inbox name, such as `transactions.csv` |
| `file_type` | `pdf`, `xml`, or `csv` |
| `text` | PDF text. Empty for XML and CSV |
| `transactions` | `date`, `amount`, `currency`, and `reference` |
| `extracted_by` | `ai` when Claude supplied the list, otherwise `python` |
| `quality` | `null` until Stage 3 |
| `quality_score` | `null` until Stage 3 |

### Fields filled in Stage 3

| Field | What is in it |
| --- | --- |
| `quality_score` | `100` or `0` from the Python scorer |
| `quality_rules` | `good` when the score is 70 or more, otherwise `bad` |
| `quality_llm` | `good` or `bad` from Claude. `null` when the content is empty or the API is down |
| `quality_llm_reason` | Claude’s one-line reason, or the skip or API message |
| `quality` | `good` only when both checks passed. When the API is down, the Python result is used. Empty content stays `bad` |

## How scoring works

`uses_transactions` in `src/s3_quality.py` chooses the Python scorer. It is our own function. XML and CSV always use the transaction score. A PDF uses it only when the transaction list is not empty.

| Function | Purpose |
| --- | --- |
| `score_transactions` | Returns `100` when every row has a `YYYY-MM-DD` date, a numeric amount, a 3-letter currency, and a reference like `INV-1044`. Returns `0` when the list is empty or any row fails. |
| `score_text` | Used for a PDF with no transactions. Returns the percentage of non-space characters that are letters, or `0` when the text is under 50 characters. |
| `judge_text` | Sends the transactions, or the PDF text, to Claude. Claude returns `good` or `bad` and one reason. It does not read `quality_score` and it does not return a number. |
| `apply_quality` | Stores the Python score, calls Claude, and sets `quality` to `good` only when both say good. |
| `place_record` | Writes the scored JSON back to `json/` and copies it to `good/` or `bad/`. |
| `index_scored_records` | Called at the end of Stage 3. Rebuilds the Chroma collection from `json/*.json`. Defined in `src/s5_index.py`. |

Both checks look at the same four fields. Python also enforces the exact shape: `YYYY-MM-DD`, a numeric amount, exactly 3 letters for currency, and a reference of letters, a hyphen, then digits. Claude is given the sentence that each item needs a date, a numeric amount, a currency, and a reference like `INV-1042`.

To change what Claude accepts, edit the instruction inside `judge_text`. To change the numeric score, edit `score_transactions`. When Claude replies, a file is kept only when both agree, so change both when the pass rule itself should change.

## Inbox samples

| File | What it shows |
| --- | --- |
| `statement.xml` | Standard transaction tags. Passes. |
| `transactions.csv` | Standard column names. Passes. |
| `statement.pdf` | Transaction lines in a digital PDF. Passes. |
| `alt-field-names.xml` | Labels are `TransactionDate`, `Txnamt`, `Ccy`, and `PaymentRef`. Claude maps them to the four JSON fields. Passes. |
| `missing-reference.xml` | One reference is blank. Score is 0. Lands in `bad/`. |
| `broken.xml` | Truncated XML. No transactions. Lands in `bad/`. Claude is skipped. |
| `garbage-text.pdf` | Symbol text and no transactions. Text score is 0. Lands in `bad/`. |

## How JSON becomes vectors

Stage 5 does not store the PDF, XML, CSV, or the JSON file as the vector. `record_text` in `src/s5_index.py` turns each transaction into one sentence. Chroma embeds that sentence.

The first payment in `statement.xml` is stored from this sentence:

`source statement.xml quality good score 100 date 2026-03-12 amount 250.0 currency GBP reference INV-1042. All items have date, numeric amount, currency, and reference.`

The same values are stored beside the vector as metadata: `source`, `file_id`, `file_type`, `quality`, `quality_score`, `quality_reason`, `date`, `amount`, `currency`, and `reference`. Search uses the vector. Filters use the metadata.

The current inbox produces 13 records: one per transaction, or one per file when the transaction list is empty.

| Source file | Records in Chroma | Quality |
| --- | --- | --- |
| `statement.xml` | 3 | good |
| `transactions.csv` | 2 | good |
| `statement.pdf` | 2 | good |
| `alt-field-names.xml` | 1 | good |
| `missing-reference.xml` | 3 | bad |
| `broken.xml` | 1 | bad |
| `garbage-text.pdf` | 1 | bad |

`vector_db/` is gitignored. Stage 3 uploads it with the `pilot-results` artifact. It is not committed. `git add` in the workflow is only `json/`, `good/`, and `bad/`.

## Ask a question

`src/chat.py` is the FastAPI service. The page title is **Transaction Assistant**. `GET /` returns the page. `POST /ask` calls `ask()` in `src/agent.py`.

`ask()` sends the question to a LangChain agent, together with the system prompt and two tools:

| Tool | What it reads |
| --- | --- |
| `find_transactions` | Up to 8 rows from `scored_records`. A payment, date, amount, or reference question uses `quality=good`. A question about rejected files uses `quality=bad`. |
| `explain_file` | Every stored row for one inbox name, such as `missing-reference.xml`. |

Claude chooses the tool. The Python tool queries Chroma and returns the rows. Claude writes the answer from those rows, and FastAPI returns that text to the page. FastAPI does not search Chroma itself.

The chat is local. The GitHub workflow does not start it.

```bash
PYTHONPATH=src python src/s5_index.py
PYTHONPATH=src python -m uvicorn chat:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The first command rebuilds `vector_db/` from the scored JSON already in `json/`. `ANTHROPIC_API_KEY` must be available to the server, as it is for the pipeline.

For a temporary public demo, leave the server on `127.0.0.1:8000` and run `cloudflared tunnel --url http://127.0.0.1:8000`. Cloudflare assigns a new `*.trycloudflare.com` name each time that process starts. The page is reachable only while both processes are running.

## Run it

The workflow is **Pilot pipeline** in `.github/workflows/pilot.yml`. It runs only when started by hand.

1. Add `ANTHROPIC_API_KEY` as a repository secret.
2. On GitHub, open **Actions**, choose **Pilot pipeline**, and click **Run workflow** on `main`.

**Re-run** repeats the previous commit. A new **Run workflow** is required after a code or inbox change.

Stage 3 commits `json/`, `good/`, and `bad/` back to the repository. Each run replaces the previous JSON files.
