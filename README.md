# UML Class Diagram Builder

A local-first web application that generates UML class diagrams from source code or natural language prompts. Built with FastAPI and vanilla JavaScript, powered by your choice of LLM provider.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Mermaid](https://img.shields.io/badge/Mermaid.js-10.9-purple)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

- **Two generation modes** — describe a diagram in plain English, or parse real source code files
- **Multi-provider LLM support** — works with Anthropic (Claude), OpenAI (GPT), and Google (Gemini)
- **Python AST parsing** — extracts classes, methods, attributes, inheritance, and associations directly from Python source without needing an LLM
- **Cross-file import analysis** — statically detects which files import from each other and draws the correct dependency arrows
- **LLM relationship review pass** — optionally sends the AST-generated diagram back to the LLM to add semantic relationships (usage patterns, orchestration, wiring) that static analysis alone cannot detect
- **Module-level functions** — standalone functions outside of classes are shown as `<<module>>` blocks
- **Interactive diagram** — zoom, pan, and drag the rendered diagram
- **Visual editor** — edit the raw Mermaid source and apply changes live
- **Export** — download the diagram as SVG
- **Prompt refinement** — use the Prompt tab to iteratively update an existing diagram
- **Diagram legend** — floating legend explaining every line type and arrowhead

---

## How It Works

### Mode 1 — Prompt

Describe what you want and the LLM generates a Mermaid `classDiagram` directly. The current diagram is kept as context so follow-up prompts refine it rather than starting over.

### Mode 2 — Code Files

A two-pass pipeline:

```
Source files
    │
    ├─ Python files ──► AST Parser ──► ClassInfo + ModuleInfo
    │                        │
    │                        ▼
    │               Cross-file import analysis
    │               (detects which files import which classes)
    │                        │
    ├─ Other files ──► LLM extraction
    │                        │
    └──────────────────────► Mermaid Builder
                                    │
                            (optional) LLM review pass
                            adds semantic relationships
                                    │
                             Final diagram
```

**Pass 1 — AST (offline, no LLM cost):**
- Extracts classes, attributes (with types), methods (with signatures)
- Detects visibility from naming conventions (`_` → protected, `__` → private)
- Detects `<<abstract>>`, `<<interface>>`, `<<enumeration>>` from base classes
- Converts `@property` decorators to attributes
- Extracts module-level standalone functions as `<<module>>` blocks
- Resolves cross-file imports to class-level arrows (`generate ..> DiagramRequest`)

**Pass 2 — LLM review (optional, toggle in UI):**
- Sends the AST diagram + original source back to the LLM
- LLM adds relationships that static analysis cannot see: usage patterns, `include_router`, dependency injection, factory patterns
- Original class blocks are preserved exactly — only relationship arrows are added

---

## Diagram Relationship Types

| Line | Meaning |
|------|---------|
| Solid → filled triangle | Inheritance (`<\|--`) |
| Solid → filled diamond | Composition (`*--`) |
| Solid → empty diamond | Aggregation (`o--`) |
| Solid → open arrow | Association (`-->`) |
| Dashed → open arrow | Dependency / Import (`..>`) |
| Dashed → filled triangle | Realization (`\|>`) |

A floating legend in the diagram panel shows all types at a glance.

---

## Supported Languages

| Language | Method |
|----------|--------|
| Python | Full AST parsing (no LLM needed) |
| JavaScript / TypeScript | LLM extraction |
| Java | LLM extraction |
| C# | LLM extraction |
| Other | LLM extraction |

For non-Python files, the LLM is used to extract classes and relationships directly.

---

## Requirements

- Python 3.11+
- An API key for at least one of: Anthropic, OpenAI, or Google Gemini

---

## Installation

```bash
# Clone the repo
git clone https://github.com/flop2106/uml_class_diagram_builder.git
cd uml_class_diagram_builder

# Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Running

```bash
uvicorn app.main:app --port 8001 --reload
```

Open [http://localhost:8001](http://localhost:8001) in your browser.

---

## Usage

### Configuration

At the top of the page, enter:
- **Token** — your API key (never stored, only used per-request)
- **Provider** — Anthropic, OpenAI, or Gemini
- **Model** — e.g. `claude-sonnet-4-6`, `gpt-4o`, `gemini-1.5-flash`

### Prompt Mode

1. Click the **Prompt** tab in the sidebar
2. Describe what you want to build, e.g.:
   > *A class diagram for a REST API with User, Post, and Comment. User has many Posts. Post has many Comments.*
3. Press **Generate** or `Ctrl+Enter`
4. Follow-up with refinements — the current diagram is kept as context automatically

### Code Files Mode

1. Click the **Code Files** tab
2. Drop files onto the drop zone, click **Browse files**, or click **+ Add blank file** to paste code manually
3. Multiple files are supported — cross-file relationships will be detected automatically
4. Optionally add extra instructions in the text area (e.g. *highlight the facade pattern*)
5. Toggle **LLM relationship review** on to enrich the diagram with semantic relationships beyond what AST can see
6. Click **Parse & Generate**

### Editing and Exporting

- **Mermaid Source tab** — view and edit the raw Mermaid syntax, then click **Apply to Diagram**
- **↓ SVG** — download the diagram as a vector SVG file
- **⎘ Copy** — copy the Mermaid source to clipboard
- **Zoom / Pan** — scroll to zoom, click and drag to pan

---

## Project Structure

```
uml_class_diagram_builder/
├── app/
│   ├── main.py                     # FastAPI app entry point (port 8001)
│   ├── routers/
│   │   ├── generate.py             # POST /api/diagram  — prompt → diagram
│   │   └── parse.py                # POST /api/parse    — code files → diagram
│   ├── schemas/
│   │   └── models.py               # Pydantic request/response contracts
│   ├── services/
│   │   ├── code_parser.py          # Python AST parser + cross-file import analysis
│   │   ├── mermaid_builder.py      # Converts parsed data → Mermaid syntax
│   │   ├── llm_factory.py          # Routes requests to the correct LLM provider
│   │   ├── anthropic_service.py    # Anthropic Claude integration
│   │   ├── openai_service.py       # OpenAI GPT integration
│   │   └── gemini_service.py       # Google Gemini integration
│   └── static/
│       └── index.html              # Single-page frontend (vanilla JS, no build step)
└── requirements.txt
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/diagram` | Generate or refine a diagram from a natural language prompt |
| `POST` | `/api/parse` | Parse source code files and generate a diagram |
| `GET` | `/health` | Health check |
| `GET` | `/` | Serves the frontend |

---

## Security Notes

- **Tokens are never stored** — the API key you enter lives only in browser memory for the duration of the session. It is not saved to localStorage, cookies, or any server-side storage. A page refresh clears it.
- **Local only** — the app is intended for local use on `localhost`. Do not expose it to the public internet without adding authentication.
- **No telemetry** — no analytics, no external calls beyond the LLM API you explicitly configure.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) |
| HTTP client | [httpx](https://www.python-httpx.org/) (async) |
| Data validation | [Pydantic v2](https://docs.pydantic.dev/) |
| AST parsing | Python standard library `ast` module |
| Diagram rendering | [Mermaid.js 10.9](https://mermaid.js.org/) |
| Frontend | Vanilla HTML / CSS / JavaScript (no build step) |

---

## License

MIT
