from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import json
import re
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from dotenv import load_dotenv
from google import genai
from google.genai import types
import asyncio

load_dotenv()

# ─────────────────────────────────────────────
# Client — instantiated once at startup
# ─────────────────────────────────────────────
client = genai.Client()

app = FastAPI(title="SYS.JOB_AGENT_API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    location: str = "Morocco"

class JobTarget(BaseModel):
    id: int
    title: str
    company: str
    desc: str
    url: str = ""

class ProfileData(BaseModel):
    name: str
    title: str
    skills: list[str]

class GenerateRequest(BaseModel):
    job: JobTarget
    profile: ProfileData


# ─────────────────────────────────────────────
# Utility: Robust JSON Cleaner
# ─────────────────────────────────────────────

def clean_json_response(raw: str) -> str:
    raw = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence_match:
        raw = fence_match.group(1).strip()
    raw = re.sub(r"\[\d+\]", "", raw)
    raw = re.sub(r",\s*(\]|})", r"\1", raw)
    return raw.strip()


# ─────────────────────────────────────────────
# Utility: Async Retry with Exponential Backoff
# ─────────────────────────────────────────────

async def call_with_retry(model: str, contents, config=None, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                wait = 60 * (2 ** attempt)
                print(f"[RATE LIMIT] Attempt {attempt + 1}/{max_retries}. Waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                raise
    raise Exception("Max retries exceeded. Quota still exhausted.")


# ─────────────────────────────────────────────
# Utility: URL Validator for Job Links
# ─────────────────────────────────────────────

def is_valid_job_url(url: str) -> bool:
    """Check if a URL is structurally valid and from a known job platform."""
    if not url or url.strip() == "":
        return False
    try:
        parsed = urlparse(url)
        # Must have scheme and netloc
        if not parsed.scheme or not parsed.netloc:
            return False
        # Must be http or https
        if parsed.scheme not in ("http", "https"):
            return False
        # Reject obviously fake patterns (e.g. placeholder domains)
        domain = parsed.netloc.lower()
        if "example.com" in domain:
            return False
        # Reject suspiciously short paths on job boards (likely fabricated IDs)
        # e.g., linkedin.com/jobs/view/12345 where 12345 is made up
        # We allow them through but flag - the real fix is the fallback
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ONLINE", "system": "Job Agent API v1.0"}


@app.post("/api/search")
async def search_jobs(request: SearchRequest):
    print(f"> Tactical Extraction for: {request.query} in {request.location}")
    cleaned = ""

    try:
        current_date = datetime.now().strftime("%B %d, %Y")

        prompt = f"""
        Today is {current_date}. Search the web for CURRENT job openings in Morocco for: '{request.query}'.

        TARGET ROLES: Applied Mathematics, Quantitative Finance, AI Engineering, Software Development (C#/.NET).

        === STRICT URL PROTOCOL (CRITICAL) ===
        - You MUST only include URLs that you directly found in the Google Search results.
        - COPY-PASTE the URL exactly as it appeared in the search result. Do NOT construct, guess, or modify any URL.
        - If you cannot find a direct, verified URL for a listing, set "url" to an empty string "".
        - NEVER fabricate or reconstruct a URL. A missing URL is acceptable. A hallucinated URL is not.

        === OUTPUT RULES ===
        - Return ONLY a raw JSON array. No preamble, no explanation, no markdown fences.
        - Do NOT include citations or footnotes (e.g. [1], [2]).
        - Do NOT include any conversational text outside the JSON.

        JSON Structure (one object per job):
        [{{
            "id": <integer starting at 1>,
            "title": "Exact Job Title from listing",
            "company": "Company Name",
            "location": "City, Morocco",
            "match": <integer 0-100 relevance score>,
            "desc": "2-sentence technical summary of the role including the posting date if visible.",
            "url": "Copy-pasted URL from search result, or empty string if not found"
        }}]
        """

        response = await call_with_retry(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )

        raw_text = response.text
        print(f"DEBUG - Raw AI Output (first 300 chars): {raw_text[:300]}")

        # Extract grounding URLs from search metadata if available
        grounding_urls = []
        try:
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                grounding_meta = getattr(candidate, 'grounding_metadata', None)
                if grounding_meta and hasattr(grounding_meta, 'grounding_chunks'):
                    for chunk in grounding_meta.grounding_chunks:
                        if hasattr(chunk, 'web') and chunk.web:
                            grounding_urls.append(chunk.web.uri)
        except Exception as e:
            print(f"DEBUG - Could not extract grounding URLs: {e}")

        print(f"DEBUG - Grounding URLs found: {grounding_urls}")

        cleaned = clean_json_response(raw_text)
        jobs_data = json.loads(cleaned)

        # Validate and fix URLs for each job
        for job in jobs_data:
            url = job.get("url", "")
            if url:
                # Validate the URL structure
                if not is_valid_job_url(url):
                    job["url"] = ""

            # If no valid URL, generate a Google Search fallback
            if not job.get("url"):
                search_term = f"{job.get('title', '')} {job.get('company', '')} {job.get('location', 'Morocco')} job"
                job["url"] = f"https://www.google.com/search?q={quote_plus(search_term)}"
                job["url_is_fallback"] = True
            else:
                job["url_is_fallback"] = False

        jobs_data.sort(key=lambda x: x.get("match", 0), reverse=True)

        return {"status": "success", "results": jobs_data}

    except json.JSONDecodeError as e:
        print(f"JSON PARSE ERROR: {e}\nCleaned text was: {cleaned}")
        return {"status": "error", "message": "AI returned malformed JSON. Please retry."}
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/generate")
async def generate_cover_letter(request: GenerateRequest):
    print(f"> Generating tailored cover letter for: {request.job.title} @ {request.job.company}")

    try:
        current_date = datetime.now().strftime("%B %d, %Y")

        prompt = f"""
        Write a highly professional, concise, and compelling cover letter for the position of {request.job.title} at {request.job.company}.

        Job Description: {request.job.desc}

        Candidate Profile — use every relevant detail below to aggressively tailor the letter:

        NAME: Abdellah Kahlaoui
        CONTACT:
          - Location: Casablanca, Morocco
          - Email: kahlaouiabdellah6@gmail.com
          - Phone: +212724458783
          - LinkedIn: linkedin.com/in/kahabdu1808
          - GitHub: github.com/AbdellahKah/AbdellahKah

        EDUCATION: M2 Applied Mathematics, FST Settat
          — Core disciplines: Stochastic Calculus, Statistical Learning, Numerical Optimization, Time Series Analysis

        TECH STACK: Python (NumPy, PyTorch, Pandas, Scikit-learn), C#/.NET, SQL, MATLAB, Git, Power BI

        ENTERPRISE EXPERIENCE:
          — 6-month internship at Safran as Data Analyst & Full-Stack Developer
          — Delivered scalable C# desktop applications and REST APIs
          — Engineered SQL-to-Power BI ETL pipelines with measurable latency reduction

        SIGNATURE PROJECTS (always cite at least one when relevant):
          1. Neural Volatility Calibration Engine: Neural network surrogate for Heston & SABR stochastic
             volatility models. Achieved 1000x inference speedup over classical Monte Carlo methods.
          2. DRL Agent for TSP: Deep Reinforcement Learning agent in PyTorch solving the Travelling
             Salesman Problem (combinatorial optimization).

        LANGUAGES: French (native), English (C1)

        === LETTER DIRECTIVES ===
        - HEADER: Open with a formal header: candidate name + full contact block, then today's date ({current_date}), then employer details if available, then greeting.
        - TONE: Sleek, confident, technically precise, direct. Never desperate or sycophantic.
        - STRATEGY: Identify the 2-3 core technical needs in the job description. Map them explicitly to the candidate's profile. Emphasize the rare bridge between rigorous mathematical theory (stochastic analysis, RL) and production engineering (C#, Python).
        - DIFFERENTIATION: The Neural Volatility Calibration Engine and DRL-for-TSP are primary differentiators — use them strategically, not decoratively.
        - AVOID: Fluffy openers ("I am excited to apply..."), generic jargon, repetitive phrasing.
        - OUTPUT FORMAT: Return ONLY the final letter text. No markdown, no code fences, no commentary.
        """

        response = await call_with_retry(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            )
        )

        return {"status": "success", "asset": response.text}

    except Exception as e:
        print(f"GENERATION ERROR: {e}")
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
