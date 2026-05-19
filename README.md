# JobCooked 🍳 — AI Interview Prep Platform

A full-stack Flask application for AI-powered interview preparation.

## Project Structure

```
jobcooked/
├── app.py                    ← Flask backend (routes + OpenRouter API)
├── requirements.txt          ← Python dependencies
├── users.json                ← Auto-created on first register
├── uploads/                  ← Temp resume uploads (auto-cleared)
└── templates/
    ├── base.html             ← Shared navbar, styles, toast
    ├── register.html         ← Registration page
    ├── login.html            ← Login page
    ├── home.html             ← Dashboard with 3 mode cards
    ├── resume_interview.html ← Resume-based interview
    ├── role_interview.html   ← Role-based interview
    └── aptitude.html         ← Aptitude MCQ test
```

## Setup & Run

### 1. Install dependencies
```bash
cd jobcooked
pip install -r requirements.txt
```

### 2. Set your OpenRouter API key

**Option A — Environment variable (recommended)**
```bash
# Linux / macOS
export OPENROUTER_API_KEY="sk-or-v1-xxxxxxxxxxxxxxxxxxxx"

# Windows CMD
set OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxx

# Windows PowerShell
$env:OPENROUTER_API_KEY="sk-or-v1-xxxxxxxxxxxxxxxxxxxx"
```

**Option B — Edit app.py directly**
```python
# Line 10 in app.py
OPENROUTER_API_KEY = "sk-or-v1-xxxxxxxxxxxxxxxxxxxx"
```

Get your API key free at: https://openrouter.ai/keys

### 3. (Optional) Change the AI model

In `app.py` line 11, set any OpenRouter model:
```python
OPENROUTER_MODEL = "openai/gpt-3.5-turbo"          # Default — fast & cheap
OPENROUTER_MODEL = "openai/gpt-4o"                 # Better quality
OPENROUTER_MODEL = "anthropic/claude-3-haiku"      # Fast Claude
OPENROUTER_MODEL = "anthropic/claude-3.5-sonnet"   # Best quality
OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct" # Free tier
```

### 4. Run the app
```bash
python app.py
```

Open your browser at: **http://localhost:5000**

---

## User Flow

```
/ (root)
  ├── Not logged in  →  /register
  └── Logged in      →  /home

/register  →  fill form  →  /login
/login     →  sign in    →  /home

/home
  ├── Click "Resume Interview"  →  /resume-interview
  ├── Click "Role-Based"        →  /role-interview
  └── Click "Aptitude Test"     →  /aptitude

Each page:  Settings → Loading (AI generates Qs) → Quiz/Interview → Results
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/register` | Register page |
| GET | `/login` | Login page |
| GET | `/home` | Dashboard (auth required) |
| GET | `/resume-interview` | Resume interview (auth required) |
| GET | `/role-interview` | Role interview (auth required) |
| GET | `/aptitude` | Aptitude test (auth required) |
| GET | `/logout` | Clear session & redirect to login |
| POST | `/api/register` | JSON: `{name, email, password}` |
| POST | `/api/login` | JSON: `{email, password}` |
| POST | `/api/resume/generate` | Multipart: `{resume file, difficulty, q_count, interview_type}` |
| POST | `/api/role/generate` | JSON: `{role, difficulty, q_count, interview_type}` |
| POST | `/api/aptitude/generate` | JSON: `{level, category, q_count}` |

---

## Features

### Auth
- Register & login with email + password
- Passwords hashed with Werkzeug (bcrypt-style)
- Sessions managed via Flask secure cookies
- Protected routes — unauthenticated users redirected to login

### Resume Interview
- Upload PDF / DOC / DOCX / TXT resume
- AI reads content and generates personalised questions
- Voice answer (Web Speech API) with live waveform
- Timer per question (1 / 2 / 3 min or unlimited)
- Score + feedback in results

### Role-Based Interview
- 22 job roles across Engineering, Data & AI, Design, Product, Management, Finance
- Search + category filter
- Fresher / Mid-Level / Senior difficulty
- Technical / Behavioral / Mixed focus
- Voice answers + scoring

### Aptitude Test
- Easy 🌱 / Medium 🔥 / Hard 💀 levels
- 6 topic categories: All, Logical, Quantitative, Verbal, Data, Coding
- Timed MCQs with auto-skip on timeout
- Correct/wrong highlighting + AI explanation
- Dot navigator to jump between questions
- Detailed review with stats (correct, wrong, skipped, avg time)

### Fallback
- If OpenRouter API key is not set or fails, all three modes serve
  high-quality hardcoded fallback questions automatically.
  A toast notification informs the user.

---

## Production Tips

```python
# app.py — change for production
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret!")

# Use a proper database (SQLite / PostgreSQL) instead of users.json
# Add SMTP integration for "Send Report to Email" feature
# Deploy with gunicorn: gunicorn -w 4 app:app
```
"# jcmock-interview" 
"# jcmock-interview" 
"# jcmock" 
