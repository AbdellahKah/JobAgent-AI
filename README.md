# SYS.JOB_AGENT_v1.0

A tactical AI agent designed to bridge the gap between advanced mathematical research and the job market. This tool automates the discovery and application process for Quantitative Analysts and AI Engineers.

## 🚀 Core Features
- **Live Search Grounding**: Utilizes Gemini 2.5 Flash to execute real-time web searches for active job postings.
- **Dynamic Match Scoring**: Automatically evaluates job descriptions against a profile specialized in Stochastic Calculus, DRL, and Numerical Optimization.
- **Automated Asset Generation**: Produces hyper-tailored cover letters that leverage complex project experience (e.g., Neural Volatility Engines & Monte Carlo simulations).

## 🛠️ Tech Stack
- **Backend**: FastAPI (Python 3.14)
- **AI Brain**: Google GenAI SDK (Gemini 2.5 Flash)
- **Frontend**: React (Tailwind CSS)
- **Environment**: Fedora 44 (KDE Plasma)

## 📦 Setup
1. Clone the repository.
2. Add your `GEMINI_API_KEY` to `backend/.env`.
3. Install dependencies: `pip install fastapi uvicorn google-genai python-dotenv`.
4. Launch: `uvicorn main:app --reload`.
