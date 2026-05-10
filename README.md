# SYS.JOB_AGENT v2.0

A tactical AI-powered job hunting agent that automates discovery, matching, tracking, and application material generation for Quantitative Analysts, AI Engineers, and Software Developers.

## Features

### Search & Discovery
- **Gemini AI Search**: Real-time job discovery via Google's Gemini 2.5 Flash with grounded web search
- **Multi-Platform Scraping**: Parallel scrapers for Rekrute.com, Emploi.ma, LinkedIn, and Indeed — returns real, persistent URLs
- **Smart URL Handling**: Rejects Google's grounding-api-redirect URLs, falls back to Google Search links when direct URLs unavailable

### Match Score Calibration
- **Hybrid Scoring**: 60% Gemini AI relevance + 40% keyword overlap against your profile
- **Keyword Extraction**: Automatically pulls skills, tech stack, education disciplines, and project names from your profile
- **Matched Skills Display**: Shows which of your skills matched each job listing
- **3-Tier Visual**: Green (≥80%) / Yellow (≥50%) / Red (<50%) with tooltip breakdown

### Job Tracker (SQLite)
- **Persistent Database**: Jobs survive page refreshes and server restarts
- **Status Pipeline**: saved → applied → interview → offer / rejected / archived
- **Deduplication**: Search results flag jobs you've already saved
- **Stats Dashboard**: Live counts by status

### Cover Letter Generator
- **Profile-Aware**: Reads from `profile.json` — no hardcoded data
- **Hyper-Tailored**: Maps your specific projects and skills to each job's requirements
- **One-Click Copy**: Generated letters ready to paste

### Profile Editor (UI)
- **Full CRUD**: Edit name, contact, skills, tech stack, education, projects, languages
- **Persisted to Disk**: Saved as `backend/profile.json`
- **Live Sync**: Profile sidebar updates immediately after save
- **Used Everywhere**: Cover letter generation + match calibration both read from it

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.11+) |
| AI | Google GenAI SDK (Gemini 2.5 Flash) |
| Scraping | httpx + BeautifulSoup4 (async) |
| Database | SQLite (WAL mode) |
| Frontend | React 18 + Tailwind CSS (CDN) |

## Setup

### 1. Clone
```bash
git clone https://github.com/AbdellahKah/JobAgent-AI.git
cd JobAgent-AI/backend
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure API Key
```bash
echo "GOOGLE_API_KEY=your_gemini_api_key_here" > .env
```
Get a key at [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

### 4. Launch
```bash
python main.py
```

### 5. Open the UI
Open `index.html` in your browser (or serve it via any static server).

The backend runs at `http://127.0.0.1:8000`.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/search` | Search jobs (Gemini + scrapers in parallel) |
| POST | `/api/generate` | Generate tailored cover letter |
| GET | `/api/profile` | Get current profile |
| PUT | `/api/profile` | Update profile |
| GET | `/api/jobs` | List tracked jobs (optional `?status=` filter) |
| GET | `/api/jobs/stats` | Get job counts by status |
| POST | `/api/jobs/save` | Save a job to tracker |
| PATCH | `/api/jobs/{id}/status` | Update job status |
| DELETE | `/api/jobs/{id}` | Remove job from tracker |

## Project Structure

```
JobAgent-AI/
├── backend/
│   ├── main.py           # FastAPI app + all endpoints
│   ├── database.py       # SQLite job tracker
│   ├── scrapers.py       # Multi-platform async scrapers
│   ├── profile.json      # Your profile data (editable via UI)
│   ├── requirements.txt  # Python dependencies
│   ├── .env              # API key (not committed)
│   └── jobs.db           # SQLite database (auto-created)
├── index.html            # Full React frontend (single file)
├── .gitignore
├── LICENSE
└── README.md
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND (React)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │  Search  │  │ Tracker  │  │ Profile  │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
└───────┼──────────────┼─────────────┼────────────────────┘
        │              │             │
┌───────┼──────────────┼─────────────┼────────────────────┐
│       ▼              ▼             ▼     BACKEND (FastAPI)│
│  ┌─────────┐   ┌──────────┐  ┌──────────┐              │
│  │ /search │   │  /jobs/* │  │/profile  │              │
│  └────┬────┘   └────┬─────┘  └────┬─────┘              │
│       │              │             │                     │
│  ┌────┴────┐    ┌────┴────┐  ┌────┴─────┐              │
│  │ Gemini  │    │ SQLite  │  │profile.  │              │
│  │  + 4x   │    │  jobs   │  │  json    │              │
│  │Scrapers │    │   .db   │  │          │              │
│  └────┬────┘    └─────────┘  └──────────┘              │
│       │                                                  │
│  ┌────┴──────────────────┐                              │
│  │  Match Calibration    │                              │
│  │  (AI×0.6 + KW×0.4)   │                              │
│  └───────────────────────┘                              │
└─────────────────────────────────────────────────────────┘
```

## License

MIT
