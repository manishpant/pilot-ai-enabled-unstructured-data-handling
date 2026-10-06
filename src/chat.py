"""Chat page. The service stays up and sends each question to the agent."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent import ask

app = FastAPI(title="Transaction Assistant")


class Question(BaseModel):
    question: str


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Transaction Assistant</title>
  <style>
    body { font-family: sans-serif; margin: 2rem auto; max-width: 40rem; }
    form { display: flex; gap: 0.5rem; }
    input { flex: 1; padding: 0.5rem; }
    button { padding: 0.5rem 1rem; }
    #answer { white-space: pre-wrap; margin-top: 1.5rem; }
  </style>
</head>
<body>
  <h1>Transaction Assistant</h1>
  <p>Ask about a Transaction</p>
  <form id="ask">
    <input name="question" placeholder="Your question" autocomplete="off" required>
    <button type="submit">Ask</button>
  </form>
  <div id="answer"></div>
  <script>
    const form = document.getElementById("ask");
    const answer = document.getElementById("answer");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      answer.textContent = "Looking up the records...";
      const question = new FormData(form).get("question");
      const response = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question })
      });
      const body = await response.json();
      answer.textContent = body.answer;
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return PAGE


@app.post("/ask")
def ask_question(body: Question) -> dict:
    question = body.question.strip()
    if not question:
        return {"answer": "Type a question."}
    return {"answer": ask(question)}
