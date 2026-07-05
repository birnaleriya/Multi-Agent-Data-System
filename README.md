<!--
title: mada
app_file: main.py
sdk: gradio
sdk_version: 5.25.0
-->

<div align="center">

# ⚡ Multi-Agent Data Analyst

**Talk to your data. Get instant analysis and interactive charts.**

Powered by GPT-4o · LangGraph · PydanticAI · Plotly · Gradio

[![Live Demo](https://img.shields.io/badge/🤗%20Hugging%20Face-Live%20Demo-orange)](https://huggingface.co/spaces/birnaleriya/mada)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](./LICENSE)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/shakil1819/Multi-Agent-Data-Analyst)

</div>

---

## What is this?

Multi-Agent Data Analyst (MADA) is a conversational AI system that lets you analyze data using plain English. Upload a CSV, connect a database, and ask questions — the system figures out the best way to answer, writes the code, runs it, and returns results with interactive Plotly visualizations.

No SQL knowledge required. No Python scripting. Just ask.

---

## How it works

User queries are routed through an **Orchestrator Agent** (PydanticAI + GPT-4o) that delegates to the right specialist:

```
User Query
    └── Orchestrator Agent
            ├── DataFrame Agent     → analyzes CSV / Excel files
            ├── SQL Agent           → queries databases, auto-generates SQL
            └── Visualization Agent → creates interactive Plotly charts
```

Results stream back in real time through a Gradio chat interface.

---

## Features

- **Natural language queries** — describe what you want, not how to get it
- **Auto data source detection** — upload a file or paste a DB connection string; the system picks the right agent
- **SQL auto-generation** — the SQL agent inspects your schema and writes queries for you
- **Interactive visualizations** — Plotly charts rendered inline with hover, zoom, and dropdown filters
- **Streaming responses** — results appear progressively as the agents work
- **Dark / Light theme** — toggle with persistent `localStorage` preference
- **CLI mode** — run headless from the terminal for scripting and automation

---

## Supported Data Sources

| Source | Formats |
|--------|---------|
| Files | `.csv`, `.xlsx`, `.xls` |
| Databases | Any SQLAlchemy-compatible DB (SQLite, PostgreSQL, MySQL, etc.) |

---

## Project Structure

```
├── main.py                          # Gradio UI + CLI entry point
├── app/
│   ├── agent_orchestrator.py        # Master orchestrator (PydanticAI)
│   ├── visualization_server.py      # Local HTTP server for Plotly HTML
│   └── tools/
│       ├── data_analyst_agent.py    # DataFrame + visualization agent
│       └── sql_data_analyst_agent.py# SQL query + visualization agent
├── tests/                           # pytest test suite
├── notebook/poc.ipynb               # Proof-of-concept notebook
├── Dockerfile                       # Container setup
├── docker-compose.yml
└── pyproject.toml                   # Dependencies (uv)
```

---

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- OpenAI API key

### Install

```bash
# Install uv (Windows)
irm https://astral.sh/uv/install.ps1 | iex

# Clone and install dependencies
git clone https://github.com/shakil1819/Multi-Agent-Data-Analyst
cd Multi-Agent-Data-Analyst

uv venv
uv sync
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
OPENAI_API_KEY=sk-...
```

### Run

```bash
# Activate virtual environment
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# Launch Gradio UI
python main.py
```

Open `http://localhost:7860` in your browser.

---

## CLI Usage

Run analysis directly from the terminal without the UI:

```bash
# Analyze a CSV file
python main.py --prompt "Show top 5 products by revenue" --file data.csv

# Query a database
python main.py --prompt "Monthly sales by region" --db sqlite:///sales.db --mode sql

# Stream output
python main.py --prompt "Find outliers" --file data.csv --stream

# Adjust limits
python main.py --prompt "..." --file data.csv --token-limit 8000 --request-limit 20
```

**CLI flags:**

| Flag | Description | Default |
|------|-------------|---------|
| `--prompt`, `-p` | Analysis question | (interactive input) |
| `--file`, `-f` | Path to CSV or Excel file | — |
| `--db`, `-d` | SQLAlchemy connection string | — |
| `--mode`, `-m` | `auto` / `dataframe` / `sql` | `auto` |
| `--stream`, `-s` | Stream output to terminal | off |
| `--token-limit` | Max tokens per session | 4000 |
| `--request-limit` | Max API calls | 10 |
| `--sheet` | Sheet name for Excel files | — |

---

## Docker

```bash
docker compose up --build
```

The app will be available at `http://localhost:8000`.

---

## Testing

```bash
# Run tests
python -m pytest

# With coverage report
python -m pytest --cov=app
```

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key |  
| `GRADIO_SERVER_PORT` | Port for the Gradio UI | No (default: `7860`) |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Orchestration | [PydanticAI](https://ai.pydantic.dev/) + GPT-4o |
| Agent Graphs | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM Provider | [OpenAI](https://openai.com/) |
| UI | [Gradio 5](https://gradio.app/) |
| Visualization | [Plotly](https://plotly.com/) |
| Data | [Pandas](https://pandas.pydata.org/) · [SQLAlchemy](https://www.sqlalchemy.org/) |
| Package Manager | [uv](https://github.com/astral-sh/uv) |

---
