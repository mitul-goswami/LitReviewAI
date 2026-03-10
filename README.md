# 🔬 LitReview AI — Autonomous Literature Review Generator

> A publishable quality multi-agent system that autonomously generates academic literature reviews from a single topic input.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Groq](https://img.shields.io/badge/LLM-Groq%20Llama%203.3%2070B-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 🏗️ Architecture

```
User Input (Topic)
      │
      ▼
┌─────────────────┐
│  Planner Agent  │  ← Orchestrates the pipeline
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│  Paper Search Agent │  ← Semantic Scholar API + Groq query expansion
└────────┬────────────┘
         │  (raw papers)
         ▼
┌─────────────────────┐
│  PDF Extraction     │  ← OA PDFs + ArXiv + abstract fallback
│  Agent              │
└────────┬────────────┘
         │  (paper text)
         ▼
┌─────────────────────┐
│  Summarization      │  ← Groq: methods, results, limitations per paper
│  Agent              │
└────────┬────────────┘
         │  (structured summaries)
         ▼
┌─────────────────────┐
│  Comparison Agent   │  ← Themes, gaps, contradictions, comparisons
└────────┬────────────┘
         │  (analysis)
         ▼
┌─────────────────────┐
│  Writer Agent       │  ← Full literature review → Markdown + LaTeX
└────────┬────────────┘
         │
         ▼
   literature_review.md + .tex
```

---

## ✨ Features

- **Fully autonomous pipeline** — one topic in, full literature review out
- **Multi-source paper discovery** — AI-expanded search queries on Semantic Scholar (200M+ papers)
- **Full-text extraction** — downloads open-access PDFs, falls back to ArXiv, then abstracts
- **Structured analysis** — methods, results, limitations, research gaps per paper
- **Thematic clustering** — identifies research themes and cross-paper relationships
- **Research gap detection** — surfaces open problems and future directions
- **Dual output** — publishable Markdown + compilable LaTeX with BibTeX
- **Real-time progress** — live agent log terminal in the browser
- **Dark academic UI** — beautiful frontend with preview, raw markdown, and LaTeX views
- **Ready to deploy** — Docker, Render, Railway, Heroku support

---

## 📁 Project Structure

```
litreview/
├── backend/
│   ├── main.py                    # FastAPI app + routing
│   ├── agents/
│   │   ├── planner_agent.py       # Pipeline orchestrator
│   │   ├── search_agent.py        # Semantic Scholar + query expansion
│   │   ├── pdf_agent.py           # PDF extraction + ArXiv fallback
│   │   ├── summarization_agent.py # Per-paper Groq summarization
│   │   ├── comparison_agent.py    # Theme/gap analysis
│   │   └── writer_agent.py        # Markdown + LaTeX generation
│   ├── routers/
│   │   └── review_router.py       # REST API endpoints
│   └── utils/
│       ├── groq_client.py         # Groq API wrapper
│       └── state_manager.py       # In-memory job state
├── frontend/
│   ├── templates/
│   │   └── index.html             # Main SPA
│   └── static/
│       ├── css/style.css          # Dark academic design
│       └── js/app.js              # Frontend logic + polling
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── render.yaml                    # Render.com config
├── Procfile                       # Heroku/Railway config
├── runtime.txt
└── README.md
```

---

## 🚀 Local Setup

### Prerequisites

- Python 3.11+
- A **Groq API key** (free at [console.groq.com](https://console.groq.com))

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/litreview-ai.git
cd litreview-ai
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Linux/macOS
# OR
venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set environment variables

```bash
cp .env.example .env
# Edit .env and add your Groq API key:
# GROQ_API_KEY=gsk_xxxxxxxxxxxx
```

On Linux/macOS you can also just export:
```bash
export GROQ_API_KEY=gsk_xxxxxxxxxxxx
```

### 5. Run the server

```bash
cd backend
python main.py
```

Open your browser at **http://localhost:8000** 🎉

---

## 🐳 Docker

```bash
# Build and run
docker compose up --build

# Or without compose:
docker build -t litreview-ai .
docker run -p 8000:8000 -e GROQ_API_KEY=gsk_xxx litreview-ai
```

---

## ☁️ Deployment

### Option A: Render (Recommended — Free Tier Available)

1. Push your code to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your repo
4. Render auto-detects `render.yaml` — or manually configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variable: `GROQ_API_KEY = your_key`
6. Deploy 🚀

### Option B: Railway

1. Push to GitHub
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add `GROQ_API_KEY` as an environment variable
4. Railway uses `Procfile` automatically

### Option C: Heroku

```bash
heroku create your-app-name
heroku config:set GROQ_API_KEY=gsk_xxx
git push heroku main
```

### Option D: Fly.io

```bash
fly launch
fly secrets set GROQ_API_KEY=gsk_xxx
fly deploy
```

---

## 🔌 REST API

### POST `/api/review`
Start a new literature review job.

**Request:**
```json
{
  "topic": "Quantum Kolmogorov-Arnold Networks",
  "max_papers": 10
}
```

**Response:**
```json
{
  "job_id": "uuid-here",
  "status": "queued",
  "message": "Literature review generation started..."
}
```

---

### GET `/api/review/{job_id}/status`
Poll job status and live logs.

**Response:**
```json
{
  "job_id": "...",
  "status": "running",
  "progress": 55,
  "current_agent": "⚖️ Comparison Agent",
  "papers_found": [{"title": "...", "year": 2024, "paperId": "..."}],
  "logs": [{"timestamp": "...", "level": "info", "message": "..."}],
  "error": null
}
```

**Status values:** `queued` → `running` → `completed` | `failed`

---

### GET `/api/review/{job_id}/result`
Get the completed literature review.

**Response:**
```json
{
  "job_id": "...",
  "topic": "...",
  "markdown": "# A Survey of ...\n\n...",
  "latex": "\\documentclass...",
  "papers_count": 10,
  "papers": [...]
}
```

---

### GET `/api/review/{job_id}/markdown`
Download raw Markdown file.

### GET `/api/review/{job_id}/latex`
Download LaTeX `.tex` file.

---

## 🧠 How Each Agent Works

### 🔍 Search Agent (`search_agent.py`)
1. Calls Groq to expand the topic into 5 diverse search queries
2. Queries Semantic Scholar for each (15 results per query)
3. Deduplicates and filters (abstract required, year ≥ 2015)
4. Uses Groq to intelligently select the most relevant N papers

### 📄 PDF Agent (`pdf_agent.py`)
1. Tries Semantic Scholar's open-access PDF link
2. Falls back to ArXiv PDF if paper has ArXiv ID
3. Extracts text with PyPDF (first 15 pages, ~8000 chars)
4. Falls back to abstract if PDF unavailable
5. Processes 3 papers concurrently

### 🧠 Summarization Agent (`summarization_agent.py`)
Per paper, Groq extracts:
- Key contribution, methodology, datasets/benchmarks
- Results, limitations, research gaps
- Keywords, paper type (empirical/theoretical/survey/system)
- Research domain

### ⚖️ Comparison Agent (`comparison_agent.py`)
Three parallel Groq calls:
1. **Theme identification** — clusters papers into research themes
2. **Gap analysis** — finds open problems, contradictions, consensus
3. **Methodology comparison** — structured cross-paper comparison table

### ✍️ Writer Agent (`writer_agent.py`)
Produces a full literature review with:
- Abstract + Introduction
- Background and Preliminaries  
- Thematic sections (one per identified cluster)
- Comparative Analysis + Research Gaps
- Conclusion and Future Directions
- Properly formatted References
- Full LaTeX with BibTeX entries

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | required | Your Groq API key |
| `PORT` | `8000` | Server port |

To change the Groq model, edit `DEFAULT_MODEL` in `backend/utils/groq_client.py`:
```python
DEFAULT_MODEL = "llama-3.3-70b-versatile"   # default
# alternatives:
# "llama-3.1-70b-versatile"
# "mixtral-8x7b-32768"
# "gemma2-9b-it"
```

---

## ⏱️ Performance

| Papers | Estimated Time |
|--------|---------------|
| 3–5    | ~1.5–2 min    |
| 10     | ~3–4 min      |
| 15–20  | ~5–7 min      |

Bottleneck: Groq rate limits (RPM). The agents use semaphores to stay within free-tier limits.

---

## 📄 Output Example

For topic **"Quantum Kolmogorov-Arnold Networks"**, the system produces:

```
# A Survey of Quantum Kolmogorov-Arnold Networks: Methods, Advances...

## Abstract
This literature review examines 10 papers covering...

## 1. Introduction
Quantum computing and neural networks have converged...

## 2. Background and Preliminaries
### 2.1 Kolmogorov-Arnold Networks
### 2.2 Quantum Machine Learning

## 3. Hybrid Quantum-Classical Architectures
...

## 4. Expressibility and Trainability
...

## 5. Comparative Analysis and Discussion
...

## 6. Conclusion and Future Directions
...

## References
[1] Doe et al. (2024). KAN: Kolmogorov-Arnold Networks...
```

Plus a compilable `.tex` file you can build with:
```bash
pdflatex literature_review.tex
bibtex literature_review
pdflatex literature_review.tex
pdflatex literature_review.tex
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push: `git push origin feature/my-feature`
5. Open a Pull Request

---

## 📜 License

MIT License — free to use, modify, and distribute.

---

## 🙏 Acknowledgements

- [Semantic Scholar API](https://api.semanticscholar.org/) for open academic paper data
- [Groq](https://groq.com/) for ultra-fast LLM inference
- [FastAPI](https://fastapi.tiangolo.com/) for the elegant Python web framework
- [ArXiv](https://arxiv.org/) for open-access preprints
