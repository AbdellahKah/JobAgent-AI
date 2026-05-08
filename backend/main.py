from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

app = FastAPI(title="SYS.JOB_AGENT_API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Data Models ---
class SearchRequest(BaseModel):
    query: str
    location: str = "Morocco"

class JobTarget(BaseModel):
    id: int
    title: str
    company: str
    desc: str
    url: str = "" # Added URL field

class ProfileData(BaseModel):
    name: str
    title: str
    skills: list[str]

class GenerateRequest(BaseModel):
    job: JobTarget
    profile: ProfileData

# --- Endpoints ---

@app.get("/")
async def root():
    return {"status": "ONLINE", "system": "Job Agent API v1.0"}

@app.post("/api/search")
async def search_jobs(request: SearchRequest):
    print(f"> Tactical Extraction for: {request.query} in {request.location}")
    
    try:
        client = genai.Client()
        current_date = datetime.now().strftime("%B %d, %Y")
        
        prompt = f"""
        Today is {current_date}. Search the web for CURRENT job openings in Morocco for: '{request.query}'.
        
        TARGET ROLES: Focus on Applied Mathematics, Quantitative Finance, AI Engineering, and Software Development (C#).
        
        INSTRUCTIONS:
        - Use Google Search to find real, active listings from Rekrute, LinkedIn, or official career sites.
        - DO NOT include citations or footnotes (like [1]). 
        - DO NOT include any conversational text.
        - Return ONLY a raw JSON array.
        
        JSON Structure:
        [{{
            "id": int,
            "title": "Job Title",
            "company": "Company",
            "location": "City, Morocco",
            "match": int,
            "desc": "A 2-sentence technical summary including the posting date.",
            "url": "Direct link to application"
        }}]
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2, # Low temperature for strictness
                tools=[types.Tool(google_search=types.GoogleSearch())] 
            )
        )
        
        # --- ROBUST JSON CLEANING ---
        raw_text = response.text.strip()
        print(f"DEBUG - Raw AI Output: {raw_text[:200]}...") # See the start of the output in your terminal

        # Remove markdown backticks if they exist
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        
        # Remove common AI citations that break JSON
        import re
        raw_text = re.sub(r'\[\d+\]', '', raw_text) 

        jobs_data = json.loads(raw_text.strip())
        jobs_data.sort(key=lambda x: x.get("match", 0), reverse=True)
        
        return {"status": "success", "results": jobs_data}

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return {"status": "error", "message": "Failed to parse search results. Try again."}


        

@app.post("/api/generate")
async def generate_cover_letter(request: GenerateRequest):
    print(f"> Generating AI tailored assets for: {request.job.company}")
    
    try:
        client = genai.Client()
        current_date = datetime.now().strftime("%B %d, %Y")
        
        prompt = f"""
        Write a highly professional, concise, and compelling cover letter for the position of {request.job.title} at {request.job.company}.
        
        Job Description: {request.job.desc}
        
        Candidate Profile (Use these specific details to aggressively tailor the letter to the job description):
        - Name: Abdellah Kahlaoui
        - Contact Information:
            - Location: Casablanca, Morocco
            - Email: kahlaouiabdellah6@gmail.com
            - Phone: +212724458783
            - LinkedIn: [linkedin.com/in/kahabdu1808
            - GitHub: github.com/AbdellahKah/AbdellahKah
        - Target Role: Applied Mathematician, Quantitative Analyst, and AI Engineer
        - Education: Master of Applied Mathematics from FST Settat (Focus: Stochastic Calculus, Statistical Learning, Numerical Optimization, Time Series).
        - Tech Stack: Python (NumPy, PyTorch, Pandas, Scikit-learn), C#, SQL, MATLAB, Git, Power BI.
        - Enterprise Experience: 6-month Data Analyst & Full Stack Intern at Safran. Built scalable C# desktop apps/REST APIs and engineered SQL-to-Power BI ETL pipelines that reduced latency.
        - Advanced Projects: 
            1. Designed a Deep Reinforcement Learning (DRL) agent in PyTorch to solve combinatorial optimization (TSP).
            2. Built a Neural Network Stochastic Volatility Calibration Engine (Heston & SABR models) achieving 1000x inference speedup over classical methods using Monte Carlo simulations.
        - Languages: Bilingual (French Native, English C1).

        Directives for the Letter:
        - Header formatting: You MUST start the letter with a formal, professional header containing the candidate's name and all Contact Information provided above. Below that, include today's date ({current_date}), followed by the employer's details (if available), and then the greeting.
        - Tone: Sleek, confident, highly technical, and direct. 
        - Strategy: Identify the core needs in the Job Description and match them directly to the Candidate Profile. Emphasize the rare ability to bridge advanced mathematical theory (Stochastic analysis/RL) with production-level software engineering (C#/Python).
        - Avoid: Overly fluffy language, desperate tones, generic corporate jargon, or repeating the exact same phrasing in every letter.
        - Output Format: Return ONLY the final letter text. Do not include markdown blocks like ```text.
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        return {
            "status": "success", 
            "asset": response.text
        }

    except Exception as e:
        print(f"Error during AI generation: {e}")
        return {"status": "error", "message": str(e)}

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
      

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)