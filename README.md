# SeenIt

**SeenIt** is a Chrome extension + FastAPI backend that detects when you're reading a news article you've already encountered in a different form — tracking story repetition across sources so you spend less time re-reading the same news.

---

## How it works

When you visit a news article, the Chrome extension sends the page content to the backend. The backend:

1. Extracts clean article text (via trafilatura, readability, or a fallback HTML parser)
2. Embeds the title + body using a sentence-transformer model
3. Compares the embedding against everything you've previously read (cosine similarity)
4. If a match is found above the similarity threshold (`TAU_EMBED = 0.7`), a banner is shown in the browser
5. Articles are grouped into clusters, and a **novelty score** is computed to tell you how much new information the current article adds

---

## Project structure

```
seenit/
├── api-server/               # FastAPI backend (Python / Poetry)
│   ├── tests/                # pytest test suite
│   ├── app.py                # Entry point — all API endpoints
│   ├── auth.py               # JWT auth via fastapi-users
│   ├── engine.py             # Sentence-transformer embedding
│   ├── storage.py            # SQLite persistence, URL normalisation
│   ├── models.py             # Pydantic request/response models
│   ├── extract_content.py    # Article content extraction
│   ├── cluster_utils.py      # Centroid + novelty computation
│   ├── conftest.py           # pytest path setup
│   ├── llm_summarizer.py     # LLM-based article summarisation
│   ├── whats_new.py          # "What's new" diff across clusters
├── experiments/              # Research & offline evals
└── extension/                # Chrome extension (JS)
    ├── icons/
    ├── background.js         # Service worker — tab detection & API calls
    ├── content.js            # Injected script — banner UI
    ├── popup.html            # Extension popup page
    ├── popup.js              # Popup logic — history & settings
    └── manifest.json
```

---

## Backend setup

### Prerequisites

- Python 3.10+
- [Poetry](https://python-poetry.org/)

### Install dependencies

```bash
cd api-server
poetry install
```

### Environment variables

Create a `.env` file in `api-server/` ans set variables as in .env.example to use locally

To generate a secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Run the server locally

```bash
cd api-server
poetry run uvicorn app:app --reload --port 8000
```

Interactive API docs are available at `http://localhost:8000/docs`.

### Run tests

```bash
cd api-server
poetry run pytest tests/ -v
```

---

## Password requirements

Passwords must be at least 8 characters and contain at least one uppercase letter and one digit.

---

## Deployment

The backend is deployed at `https://seenit.doc.ic.ac.uk`
