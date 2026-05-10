from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import uvicorn
import json
import re
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from dotenv import load_dotenv
from google import genai
from google.genai import types
import asyncio
from fpdf import FPDF
import textwrap

import database as db
from scrapers import scrape_all_platforms
import os

load_dotenv()

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "profile.json")

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

class SaveJobRequest(BaseModel):
    title: str
    company: str
    location: str = ""
    desc: str = ""
    url: str = ""
    url_is_fallback: bool = False
    match: int = 0

class UpdateStatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


# ─────────────────────────────────────────────
# Utility: Profile Loader
# ─────────────────────────────────────────────

def load_profile() -> dict:
    """Load profile from profile.json."""
    try:
        with open(PROFILE_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_profile(data: dict):
    """Save profile to profile.json."""
    with open(PROFILE_PATH, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def build_profile_prompt_block(profile: dict) -> str:
    """Build the profile section for the cover letter prompt from profile data."""
    exp_lines = ""
    for exp in profile.get("experience", []):
        exp_lines += f"\n          — {exp.get('duration', '')} internship at {exp.get('company', '')} as {exp.get('role', '')}"
        for h in exp.get("highlights", []):
            exp_lines += f"\n          — {h}"

    proj_lines = ""
    for i, proj in enumerate(profile.get("projects", []), 1):
        proj_lines += f"\n          {i}. {proj.get('name', '')}: {proj.get('description', '')}"

    return f"""
        NAME: {profile.get('name', '')}
        CONTACT:
          - Location: {profile.get('location', '')}
          - Email: {profile.get('email', '')}
          - Phone: {profile.get('phone', '')}
          - LinkedIn: {profile.get('linkedin', '')}
          - GitHub: {profile.get('github', '')}

        EDUCATION: {profile.get('education', {}).get('degree', '')} , {profile.get('education', {}).get('school', '')}
          — Core disciplines: {', '.join(profile.get('education', {}).get('disciplines', []))}

        TECH STACK: {profile.get('tech_stack', '')}

        ENTERPRISE EXPERIENCE:{exp_lines}

        SIGNATURE PROJECTS (always cite at least one when relevant):{proj_lines}

        LANGUAGES: {', '.join(profile.get('languages', []))}
    """


# ─────────────────────────────────────────────
# Utility: Match Score Calibration
# ─────────────────────────────────────────────

def calibrate_match_score(job: dict, profile: dict) -> dict:
    """
    Compute a calibrated match score combining:
    - Gemini's AI score (subjective relevance)
    - Keyword overlap score (objective skill matching)
    
    Returns dict with: calibrated_score, keyword_score, ai_score, matched_skills
    """
    ai_score = job.get("match", 50)

    # Build searchable text from job
    job_text = f"{job.get('title', '')} {job.get('desc', '')} {job.get('company', '')}".lower()

    # Get profile keywords: skills + tech_stack + education disciplines + project names
    profile_keywords = []
    for skill in profile.get("skills", []):
        profile_keywords.append(skill.lower())
    
    # Add tech stack individual items
    tech_stack = profile.get("tech_stack", "")
    for item in re.split(r'[,/()]', tech_stack):
        item = item.strip().lower()
        if len(item) > 2:
            profile_keywords.append(item)

    # Add education disciplines
    for disc in profile.get("education", {}).get("disciplines", []):
        profile_keywords.append(disc.lower())

    # Add project names as keywords
    for proj in profile.get("projects", []):
        name = proj.get("name", "").lower()
        if name:
            # Split multi-word project names into individual keywords
            for word in name.split():
                if len(word) > 3:
                    profile_keywords.append(word)

    # Deduplicate
    profile_keywords = list(set(profile_keywords))

    # Compute keyword overlap
    matched_skills = []
    for keyword in profile_keywords:
        # Check if keyword or any significant part appears in job text
        if keyword in job_text:
            matched_skills.append(keyword)
        else:
            # Check individual words of multi-word skills (e.g. "Deep Reinforcement Learning")
            words = keyword.split()
            if len(words) > 1:
                significant_matches = sum(1 for w in words if len(w) > 3 and w in job_text)
                if significant_matches >= len(words) * 0.6:
                    matched_skills.append(keyword)

    # Keyword score: percentage of profile keywords found in job
    total_keywords = max(len(profile_keywords), 1)
    keyword_score = min(100, int((len(matched_skills) / total_keywords) * 150))  # Scale up, cap at 100

    # Hybrid formula: 60% AI score + 40% keyword overlap
    calibrated_score = int(ai_score * 0.6 + keyword_score * 0.4)
    calibrated_score = max(0, min(100, calibrated_score))

    return {
        "calibrated_score": calibrated_score,
        "keyword_score": keyword_score,
        "ai_score": ai_score,
        "matched_skills": matched_skills[:8],  # Top 8 for display
    }


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
    """Check if a URL is structurally valid and NOT a Google grounding redirect."""
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
        domain = parsed.netloc.lower()
        # Reject Google's grounding-api-redirect URLs (they expire and 404)
        if "vertexaisearch.cloud.google.com" in domain:
            return False
        if "grounding-api-redirect" in url:
            return False
        # Reject obviously fake patterns
        if "example.com" in domain:
            return False
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
        - NEVER use vertexaisearch.cloud.google.com or grounding-api-redirect URLs. These are internal system URLs and NOT valid job links.
        - Only include real destination URLs like linkedin.com, indeed.com, rekrute.com, emploi.ma, etc.
        - If you cannot find a direct, verified destination URL for a listing, set "url" to an empty string "".
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

        # Run Gemini search and platform scrapers IN PARALLEL
        gemini_task = call_with_retry(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        scraper_task = scrape_all_platforms(request.query, request.location)

        # Wait for both
        gemini_response, scraped_jobs = await asyncio.gather(
            gemini_task, scraper_task, return_exceptions=True
        )

        # ─── Process Gemini results ───
        jobs_data = []
        if isinstance(gemini_response, Exception):
            print(f"[GEMINI] Failed: {gemini_response}")
        else:
            raw_text = gemini_response.text
            print(f"DEBUG - Raw AI Output (first 300 chars): {raw_text[:300]}")

            cleaned = clean_json_response(raw_text)
            try:
                jobs_data = json.loads(cleaned)
            except json.JSONDecodeError as e:
                print(f"JSON PARSE ERROR: {e}\nCleaned text was: {cleaned}")

        # Validate Gemini URLs
        for job in jobs_data:
            url = job.get("url", "")
            if url and not is_valid_job_url(url):
                job["url"] = ""
            job["source"] = "gemini"
            job["url_is_fallback"] = False

        # ─── Process scraped results ───
        scraped_list = []
        if isinstance(scraped_jobs, Exception):
            print(f"[SCRAPERS] Failed: {scraped_jobs}")
        else:
            scraped_list = scraped_jobs if scraped_jobs else []

        # ─── Merge: Try to match scraped URLs to Gemini jobs ───
        # For Gemini jobs missing URLs, try to find a match from scrapers
        for job in jobs_data:
            if not job.get("url"):
                # Try to find a scraped job with matching title/company
                matched = _find_scraper_match(job, scraped_list)
                if matched:
                    job["url"] = matched["url"]
                    job["source"] = matched["source"]
                    job["url_is_fallback"] = False
                else:
                    # Fallback to Google Search
                    search_term = f"{job.get('title', '')} {job.get('company', '')} {job.get('location', 'Morocco')} job"
                    job["url"] = f"https://www.google.com/search?q={quote_plus(search_term)}"
                    job["url_is_fallback"] = True

        # ─── Add scraped jobs not already in Gemini results ───
        existing_titles = {(j.get("title", "").lower(), j.get("company", "").lower()) for j in jobs_data}
        next_id = len(jobs_data) + 1

        for scraped in scraped_list:
            key = (scraped.get("title", "").lower(), scraped.get("company", "").lower())
            if key not in existing_titles and scraped.get("url"):
                existing_titles.add(key)
                jobs_data.append({
                    "id": next_id,
                    "title": scraped["title"],
                    "company": scraped.get("company", "Unknown"),
                    "location": scraped.get("location", request.location),
                    "match": 50,  # Default match score for scraped-only jobs
                    "desc": scraped.get("desc", ""),
                    "url": scraped["url"],
                    "url_is_fallback": False,
                    "source": scraped.get("source", "scraper"),
                })
                next_id += 1

        # Sort: Gemini-scored jobs first, then scraped extras
        jobs_data.sort(key=lambda x: x.get("match", 0), reverse=True)

        # ─── Calibrate match scores using profile keywords ───
        profile = load_profile()
        for job in jobs_data:
            cal = calibrate_match_score(job, profile)
            job["ai_score"] = cal["ai_score"]
            job["keyword_score"] = cal["keyword_score"]
            job["match"] = cal["calibrated_score"]
            job["matched_skills"] = cal["matched_skills"]

        # Re-sort by calibrated score
        jobs_data.sort(key=lambda x: x.get("match", 0), reverse=True)

        # Flag jobs already saved in the database (deduplication)
        for job in jobs_data:
            existing = db.find_duplicates(job.get("title", ""), job.get("company", ""))
            if existing:
                job["already_saved"] = True
                job["saved_status"] = existing["status"]
                job["saved_id"] = existing["id"]
            else:
                job["already_saved"] = False

        return {"status": "success", "results": jobs_data}

    except json.JSONDecodeError as e:
        print(f"JSON PARSE ERROR: {e}\nCleaned text was: {cleaned}")
        return {"status": "error", "message": "AI returned malformed JSON. Please retry."}
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return {"status": "error", "message": str(e)}


def _find_scraper_match(gemini_job: dict, scraped_jobs: list[dict]) -> dict | None:
    """Try to find a scraped job that matches a Gemini result by title similarity."""
    gemini_title = gemini_job.get("title", "").lower().strip()
    gemini_company = gemini_job.get("company", "").lower().strip()

    for scraped in scraped_jobs:
        scraped_title = scraped.get("title", "").lower().strip()
        scraped_company = scraped.get("company", "").lower().strip()

        # Exact title match
        if gemini_title == scraped_title:
            return scraped

        # Company match + title overlap (at least 3 words in common)
        if gemini_company and gemini_company in scraped_title:
            return scraped

        # Fuzzy: check if key words from gemini title appear in scraped title
        gemini_words = set(gemini_title.split())
        scraped_words = set(scraped_title.split())
        overlap = gemini_words & scraped_words
        if len(overlap) >= 3 and (gemini_company == scraped_company or not gemini_company):
            return scraped

    return None


@app.post("/api/generate")
async def generate_cover_letter(request: GenerateRequest):
    print(f"> Generating tailored cover letter for: {request.job.title} @ {request.job.company}")

    try:
        current_date = datetime.now().strftime("%B %d, %Y")
        profile = load_profile()
        profile_block = build_profile_prompt_block(profile)

        prompt = f"""
        Write a highly professional, concise, and compelling cover letter for the position of {request.job.title} at {request.job.company}.

        Job Description: {request.job.desc}

        Candidate Profile — use every relevant detail below to aggressively tailor the letter:
        {profile_block}

        === LETTER DIRECTIVES ===
        - HEADER: Open with a formal header: candidate name + full contact block, then today's date ({current_date}), then employer details if available, then greeting.
        - TONE: Sleek, confident, technically precise, direct. Never desperate or sycophantic.
        - STRATEGY: Identify the 2-3 core technical needs in the job description. Map them explicitly to the candidate's profile. Emphasize the rare bridge between rigorous mathematical theory (stochastic analysis, RL) and production engineering (C#, Python).
        - DIFFERENTIATION: The signature projects are primary differentiators — use them strategically, not decoratively.
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


class ExportPDFRequest(BaseModel):
    text: str
    job_title: str = ""
    company: str = ""


@app.post("/api/export-pdf")
async def export_pdf(request: ExportPDFRequest):
    """Export cover letter text as a professionally formatted PDF."""
    try:
        profile = load_profile()

        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=20)

        # Use built-in fonts (no external font files needed)
        pdf.set_font("Helvetica", size=10)

        # Header: candidate name
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 8, profile.get("name", ""), new_x="LMARGIN", new_y="NEXT")

        # Contact line
        pdf.set_font("Helvetica", "", 9)
        contact_parts = []
        if profile.get("email"):
            contact_parts.append(profile["email"])
        if profile.get("phone"):
            contact_parts.append(profile["phone"])
        if profile.get("location"):
            contact_parts.append(profile["location"])
        if contact_parts:
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 5, " | ".join(contact_parts), new_x="LMARGIN", new_y="NEXT")

        # LinkedIn / GitHub
        links = []
        if profile.get("linkedin"):
            links.append(profile["linkedin"])
        if profile.get("github"):
            links.append(profile["github"])
        if links:
            pdf.cell(0, 5, " | ".join(links), new_x="LMARGIN", new_y="NEXT")

        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        # Separator line
        pdf.set_draw_color(180, 180, 180)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(6)

        # Job target subtitle
        if request.job_title or request.company:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(100, 100, 100)
            target = f"Re: {request.job_title}" + (f" at {request.company}" if request.company else "")
            pdf.cell(0, 5, target, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

        # Body text
        pdf.set_font("Helvetica", "", 10)
        
        # Process text: handle line breaks properly
        lines = request.text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                pdf.ln(4)
            else:
                # Wrap long lines
                pdf.multi_cell(0, 5, line)

        # Generate PDF bytes
        pdf_bytes = pdf.output()

        # Create filename
        safe_company = re.sub(r'[^a-zA-Z0-9]', '_', request.company or "cover_letter")
        filename = f"Cover_Letter_{safe_company}.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"PDF EXPORT ERROR: {e}")
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────
# Job Tracker Endpoints
# ─────────────────────────────────────────────

@app.get("/api/jobs")
async def list_saved_jobs(status: Optional[str] = None):
    """List all saved jobs, optionally filtered by status."""
    try:
        jobs = db.get_all_jobs(status=status)
        return {"status": "success", "results": jobs}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/jobs/stats")
async def job_stats():
    """Get summary statistics for tracked jobs."""
    try:
        stats = db.get_stats()
        return {"status": "success", "stats": stats}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/jobs/save")
async def save_job(request: SaveJobRequest):
    """Save a job from search results to the tracker."""
    try:
        job_data = {
            "title": request.title,
            "company": request.company,
            "location": request.location,
            "desc": request.desc,
            "url": request.url,
            "url_is_fallback": request.url_is_fallback,
            "match": request.match,
        }
        saved = db.save_job(job_data)
        return {"status": "success", "job": saved}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.patch("/api/jobs/{job_id}/status")
async def update_job_status(job_id: int, request: UpdateStatusRequest):
    """Update the application status of a tracked job."""
    try:
        updated = db.update_job_status(job_id, request.status, request.notes)
        if updated:
            return {"status": "success", "job": updated}
        return {"status": "error", "message": "Job not found"}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: int):
    """Remove a job from the tracker."""
    try:
        deleted = db.delete_job(job_id)
        if deleted:
            return {"status": "success", "message": "Job removed"}
        return {"status": "error", "message": "Job not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────
# Profile Endpoints
# ─────────────────────────────────────────────

@app.get("/api/profile")
async def get_profile():
    """Get the current user profile."""
    try:
        profile = load_profile()
        return {"status": "success", "profile": profile}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.put("/api/profile")
async def update_profile(profile: dict):
    """Update the user profile."""
    try:
        save_profile(profile)
        return {"status": "success", "profile": profile}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
