# Pilot: AI-enabled unstructured data handling

Mixed financial files in `inbox/` become one JSON shape. Only records that pass the quality checks are kept in `good/`. Python writes the files and enforces the rules. Claude maps fields and gives a second opinion.

Each transaction keeps four fields only: `date`, `amount`, `currency`, and `reference`. A description or any other source field is left out.

## Pipeline

| Stage | What it does | Python or hybrid | Benefit |
| --- | --- | --- | --- |
| Stage 1 — format detection | Python reads the extension. `.pdf`, `.xml`, and `.csv` are decided by that rule. Claude is called only when the extension is not one of those. If that call fails, the file is `unknown`. | Hybrid | Known formats are instant and repeatable. Claude is used only for a file the rules do not already recognise. |
| Stage 2 — extract to JSON | Claude maps any date-like, amount-like, currency-like, or reference-like label into `date`, `amount`, `currency`, and `reference`. Python writes one file per source into `json/` and sets `extracted_by` to `ai`. If Claude is unavailable, Python’s parsers fill the transactions and set `extracted_by` to `python`. | Hybrid | Labels such as `Txnamt`, `TransactionDate`, `Ccy`, and `PaymentRef` still become the same four JSON fields. The run still produces JSON when the model is down. |
| Stage 3 — quality gate | Python scores every row. A file passes only when every transaction has a date as `YYYY-MM-DD`, a numeric amount, a 3-letter currency, and a reference like `INV-1042`. Claude then gives a second good or bad verdict. Both must pass for `good/`. A miss goes to `bad/`. If the API is down, the Python score is the result. | Hybrid | A blank reference or a broken file cannot pass. The score and verdict are stored on the JSON. |
| Summary | Claude writes a root cause and a mitigation for each bad file. Python prints the list, colours bad names red, and writes the same table into the GitHub job summary. If Claude fails, Python supplies the root cause and mitigation from the score. | Hybrid | Every run shows which files passed, which failed, why, and what to fix. |

Model: `claude-haiku-4-5`.

## Flow

1. **Format check.** Stage 1 sets the type from the extension. Claude is used only when the extension is not pdf, xml, or csv.
2. **Fetch and convert to JSON.** Stage 2 reads the file. Claude maps the fields. Python writes `json/<id>.json` and sets `extracted_by`. `quality` and `quality_score` are still empty here.
3. **Quality check.** Stage 3 scores that JSON. Python sets `quality_score`. Claude sets `quality_llm` to good or bad.
4. **Fill the same JSON.** Stage 3 writes those fields back into the file from step 2, then copies it to `good/` or `bad/`.
5. **Summary.** The Summary job reads the finished files and lists what passed, what failed, why, and what to fix.

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
| `quality` | Empty until Stage 3 |
| `quality_score` | Empty until Stage 3 |

### Fields filled in Stage 3

| Field | What is in it |
| --- | --- |
| `quality_score` | `100` or `0` from the Python scorer |
| `quality_rules` | `good` when the score is 70 or more, otherwise `bad` |
| `quality_llm` | `good` or `bad` from Claude |
| `quality_llm_reason` | Claude’s one-line reason |
| `quality` | `good` only when both checks passed |

## How scoring works

`uses_transactions` in `src/s3_quality.py` chooses the Python scorer. It is our own function. XML and CSV always use the transaction score. A PDF uses it only when the transaction list is not empty.

| Function | Purpose |
| --- | --- |
| `score_transactions` | Returns `100` when every row has a `YYYY-MM-DD` date, a numeric amount, a 3-letter currency, and a reference like `INV-1044`. Returns `0` when the list is empty or any row fails. |
| `score_text` | Used for a PDF with no transactions. Returns the percentage of non-space characters that are letters, or `0` when the text is under 50 characters. |
| `judge_text` | Sends the transactions, or the PDF text, to Claude. Claude returns `good` or `bad` and one reason. It does not read `quality_score` and it does not return a number. |
| `apply_quality` | Stores the Python score, calls Claude, and sets `quality` to `good` only when both say good. |
| `place_record` | Writes the scored JSON back to `json/` and copies it to `good/` or `bad/`. |

Both checks look at the same four fields. Python also enforces the exact shape: `YYYY-MM-DD`, a numeric amount, exactly 3 letters for currency, and a reference of letters, a hyphen, then digits. Claude is given the sentence that each item needs a date, a numeric amount, a currency, and a reference like `INV-1042`.

To change what Claude accepts, edit the instruction inside `judge_text`. To change the numeric score, edit `score_transactions`. A file is kept only when both agree, so change both when the pass rule itself should change.

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

## Run it

The workflow is **Pilot pipeline** in `.github/workflows/pilot.yml`. It runs only when started by hand.

1. Add `ANTHROPIC_API_KEY` as a repository secret.
2. On GitHub, open **Actions**, choose **Pilot pipeline**, and click **Run workflow** on `main`.

**Re-run** repeats the previous commit. A new **Run workflow** is required after a code or inbox change.

Stage 3 commits `json/`, `good/`, and `bad/` back to the repository. Each run replaces the previous JSON files.
