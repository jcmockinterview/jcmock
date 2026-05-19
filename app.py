from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import os, json, requests, uuid, re, smtplib, random, io
from functools import wraps
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from report_generator import report_generator
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jobcooked-secret-key-change-in-prod")

# ==================== DATABASE CONFIG ====================
# PostgreSQL in production (set DATABASE_URL env var on Render/Railway)
# SQLite locally (zero setup needed)
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # Render gives postgres:// but SQLAlchemy needs postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    # Local SQLite fallback
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        os.path.dirname(__file__), "jobcooked.db"
    )

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ==================== USER MODEL ====================

class User(db.Model):
    __tablename__ = "users"

    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name       = db.Column(db.String(255), nullable=False)
    password   = db.Column(db.String(512), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "email": self.email, "name": self.name}

# Create tables on first run
with app.app_context():
    db.create_all()
    print("✅ Database tables ready")

# ==================== DB HELPER FUNCTIONS ====================
# Same interface as the old load_users/save_users so all routes work unchanged

def get_user_by_email(email: str) -> User | None:
    return User.query.filter_by(email=email.lower().strip()).first()

def create_user(name: str, email: str, hashed_password: str) -> User:
    user = User(name=name, email=email.lower().strip(), password=hashed_password)
    db.session.add(user)
    db.session.commit()
    return user

def update_user_password(email: str, hashed_password: str):
    user = get_user_by_email(email)
    if user:
        user.password = hashed_password
        db.session.commit()

# ==================== OPENROUTER CONFIG ====================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL   = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat")

# ==================== EMAIL CONFIG ====================
GMAIL_USER         = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# In-memory OTP store  {email: {otp, expiry, verified}}
otp_storage: dict = {}

# Report + upload folders
REPORT_FOLDER = os.path.join(os.path.dirname(__file__), "reports")
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024   # 10 MB

os.makedirs(REPORT_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==================== AUTH DECORATOR ====================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_email" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== PAGE ROUTES ====================

@app.route("/")
def index():
    return redirect(url_for("home") if "user_email" in session else url_for("register"))

@app.route("/register", methods=["GET"])
def register():
    return redirect(url_for("home")) if "user_email" in session else render_template("register.html")

@app.route("/login", methods=["GET"])
def login():
    return redirect(url_for("home")) if "user_email" in session else render_template("login.html")

@app.route("/home")
@login_required
def home():
    user = get_user_by_email(session["user_email"])
    return render_template("home.html", user_name=user.name if user else "User")

@app.route("/resume-interview")
@login_required
def resume_interview():
    return render_template("resume_interview.html")

@app.route("/role-interview")
@login_required
def role_interview():
    return render_template("role_interview.html")

@app.route("/aptitude")
@login_required
def aptitude():
    return render_template("aptitude.html")

@app.route("/forgot-password", methods=["GET"])
def forgot_password():
    return render_template("forgot_password.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ==================== AUTH API ====================

@app.route("/api/register", methods=["POST"])
def api_register():
    data  = request.get_json()
    name  = data.get("name",     "").strip()
    email = data.get("email",    "").strip().lower()
    pwd   = data.get("password", "")

    if not name or not email or not pwd:
        return jsonify({"ok": False, "msg": "All fields are required."}), 400
    if len(pwd) < 8:
        return jsonify({"ok": False, "msg": "Password must be at least 8 characters."}), 400
    if get_user_by_email(email):
        return jsonify({"ok": False, "msg": "An account with this email already exists."}), 409

    create_user(name, email, generate_password_hash(pwd))
    return jsonify({"ok": True, "msg": "Account created! Redirecting..."})


@app.route("/api/login", methods=["POST"])
def api_login():
    data  = request.get_json()
    email = data.get("email",    "").strip().lower()
    pwd   = data.get("password", "")

    user = get_user_by_email(email)
    if not user or not check_password_hash(user.password, pwd):
        return jsonify({"ok": False, "msg": "Invalid email or password."}), 401

    session["user_email"] = user.email
    session["user_name"]  = user.name
    return jsonify({"ok": True, "redirect": url_for("home")})

# ==================== OPENROUTER CORE ====================

def call_openrouter(prompt: str, temperature: float = 0.5, max_tokens: int = 2000) -> str | None:
    print(f"🌐 Calling OpenRouter (model: {OPENROUTER_MODEL})...")
    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer":  "https://jobcooked.app",
                "X-Title":       "JobCooked",
                "Content-Type":  "application/json",
            },
            json={
                "model":       OPENROUTER_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens":  max_tokens,
            },
            timeout=60,
        )
        if response.status_code == 200:
            result = response.json()["choices"][0]["message"]["content"]
            print(f"   ✅ Success ({len(result)} chars)")
            return result
        else:
            print(f"   ❌ OpenRouter error {response.status_code}: {response.text[:300]}")
            return None
    except requests.exceptions.Timeout:
        print("   ❌ Request timed out (60s)")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ Connection error: {e}")
        return None
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        return None


def parse_numbered_questions(raw: str, expected: int) -> list | None:
    questions = []
    for line in raw.split("\n"):
        match = re.match(r"^\s*(\d+)\.\s+(.+)", line)
        if match:
            num  = int(match.group(1))
            text = match.group(2).strip()
            text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text).strip()
            if text and 1 <= num <= expected:
                questions.append({"id": num, "question": text, "category": "General"})
    questions = sorted(questions, key=lambda x: x["id"])[:expected]
    if len(questions) < expected:
        print(f"   ❌ Only parsed {len(questions)}/{expected} questions.")
        return None
    return questions


def parse_mcq_questions(raw: str, expected: int) -> list | None:
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        s = clean.find("["); e = clean.rfind("]")
        if s != -1 and e != -1:
            parsed = json.loads(clean[s:e+1])
            if isinstance(parsed, list) and len(parsed) >= expected:
                for i, q in enumerate(parsed):
                    q.setdefault("id", i + 1)
                    q.setdefault("category", "General")
                    q.setdefault("explanation", "See correct answer above.")
                    if "correct" not in q or not isinstance(q["correct"], int):
                        q["correct"] = 0
                return parsed[:expected]
    except Exception:
        pass

    questions = []
    blocks    = re.split(r"\n(?=\d+\.)", raw.strip())
    keys      = ["A", "B", "C", "D"]

    for block in blocks:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue
        q_match = re.match(r"^\s*(\d+)\.\s+(.+)", lines[0])
        if not q_match:
            continue
        q_num  = int(q_match.group(1))
        q_text = q_match.group(2).strip()
        options = []; correct = 0; explanation = ""
        for line in lines[1:]:
            opt_match = re.match(r"^[A-D][)\.]\s+(.+)", line)
            if opt_match: options.append(opt_match.group(1).strip())
            ans_match = re.match(r"(?i)answer\s*[:\-]\s*([A-D])", line)
            if ans_match: correct = keys.index(ans_match.group(1).upper())
            exp_match = re.match(r"(?i)explanation\s*[:\-]\s*(.+)", line)
            if exp_match: explanation = exp_match.group(1).strip()
        if len(options) == 4 and 1 <= q_num <= expected:
            questions.append({"id": q_num, "question": q_text, "options": options,
                              "correct": correct, "explanation": explanation or "See correct answer above.",
                              "category": "General"})

    questions = sorted(questions, key=lambda x: x["id"])[:expected]
    if len(questions) < expected:
        print(f"   ❌ Only parsed {len(questions)}/{expected} MCQ questions.")
        return None
    return questions

# ==================== TEST KEY ====================

@app.route("/api/test-key", methods=["GET"])
@login_required
def api_test_key():
    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                     "HTTP-Referer": "https://jobcooked.app", "X-Title": "JobCooked",
                     "Content-Type": "application/json"},
            json={"model": OPENROUTER_MODEL,
                  "messages": [{"role": "user", "content": "Reply with one word: ready"}],
                  "max_tokens": 5},
            timeout=20,
        )
        if response.status_code == 200:
            return jsonify({"ok": True, "msg": f"✅ API key working! Model: {OPENROUTER_MODEL}", "model": OPENROUTER_MODEL})
        codes = {401: "401 — API key invalid.", 402: "402 — No credits.", 404: f"404 — Model not found."}
        return jsonify({"ok": False, "msg": codes.get(response.status_code, f"Error {response.status_code}"), "model": OPENROUTER_MODEL})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e), "model": OPENROUTER_MODEL})

# ==================== RESUME INTERVIEW ====================

@app.route("/api/resume/generate", methods=["POST"])
@login_required
def api_resume_generate():
    difficulty     = request.form.get("difficulty",     "mid")
    q_count        = int(request.form.get("q_count",    10))
    interview_type = request.form.get("interview_type", "mixed")

    resume_text = ""
    if "resume" in request.files:
        f = request.files["resume"]
        if f and f.filename and allowed_file(f.filename):
            filename = secure_filename(f.filename)
            path     = os.path.join(app.config["UPLOAD_FOLDER"], f"{uuid.uuid4()}_{filename}")
            f.save(path)
            try:
                ext = filename.rsplit(".", 1)[1].lower()
                if ext == "txt":
                    with open(path, encoding="utf-8", errors="ignore") as fp:
                        resume_text = fp.read(20000)
                elif ext == "pdf":
                    try:
                        from pypdf import PdfReader
                        reader = PdfReader(path)
                        for page in reader.pages:
                            t = page.extract_text()
                            if t: resume_text += t + "\n"
                        resume_text = resume_text[:20000]
                    except ImportError:
                        try:
                            from pdfminer.high_level import extract_text as pdf_extract
                            resume_text = pdf_extract(path)[:20000]
                        except ImportError:
                            resume_text = f"[PDF uploaded: {filename}]"
                elif ext in ("doc", "docx"):
                    try:
                        import docx2txt
                        resume_text = docx2txt.process(path)[:20000]
                    except ImportError:
                        resume_text = f"[Word document uploaded: {filename}]"
            finally:
                if os.path.exists(path): os.remove(path)

    level_map = {
        "fresher": "Fresher / Entry-Level (0-1 year of experience)",
        "mid":     "Mid-Level Professional (2-4 years of experience)",
        "senior":  "Senior Professional (5+ years of experience)",
    }
    focus_map = {
        "technical":  "Technical - assess coding, tools, architecture, and domain knowledge",
        "behavioral": "Behavioral - assess soft skills, teamwork, and ownership via STAR method",
        "mixed":      "Mixed - equal balance of technical and behavioral questions",
    }
    level_desc = level_map.get(difficulty, level_map["mid"])
    focus_desc = focus_map.get(interview_type, focus_map["mixed"])

    if interview_type == "technical":
        tech_n, proj_n, hr_n, scen_n = q_count - 3, 2, 1, 0
    elif interview_type == "behavioral":
        tech_n, proj_n, hr_n, scen_n = 0, 2, q_count - 4, 2
    else:
        tech_n = max(1, q_count // 3); proj_n = max(1, q_count // 4)
        hr_n   = max(1, q_count // 4); scen_n = q_count - tech_n - proj_n - hr_n

    tech_n = max(tech_n, 0); proj_n = max(proj_n, 0)
    hr_n   = max(hr_n,   1); scen_n = max(scen_n, 0)

    if resume_text.strip():
        prompt = f"""You are an expert interview question generator.

Based on this resume, generate EXACTLY {q_count} interview questions in the following format:

**Technical Questions ({tech_n}):**
{chr(10).join(f"{i+1}. [Question]" for i in range(tech_n))}

**Project-Based Questions ({proj_n}):**
{chr(10).join(f"{tech_n+i+1}. [Question]" for i in range(proj_n))}

**HR Questions ({hr_n}):**
{chr(10).join(f"{tech_n+proj_n+i+1}. [Question]" for i in range(hr_n))}

**Scenario-Based Questions ({scen_n}):**
{chr(10).join(f"{tech_n+proj_n+hr_n+i+1}. [Question]" for i in range(scen_n))}

STRICT RULES:
- Every question MUST be directly tied to something visible in this resume
- Do NOT ask generic questions a stranger to this resume could answer
- Probe deeply: ask WHY, HOW, what were the outcomes, what would you do differently
- Candidate level: {level_desc}
- Interview focus: {focus_desc}
- Number them 1-{q_count} exactly as shown above
- No bold markers, no extra text - just numbered questions

Resume:
{resume_text}
"""
    else:
        prompt = f"""You are an expert interview question generator.

Generate EXACTLY {q_count} strong interview questions for a candidate with NO resume provided.

**Technical Questions ({tech_n}):**
{chr(10).join(f"{i+1}. [Question]" for i in range(tech_n))}

**Project-Based Questions ({proj_n}):**
{chr(10).join(f"{tech_n+i+1}. [Question]" for i in range(proj_n))}

**HR Questions ({hr_n}):**
{chr(10).join(f"{tech_n+proj_n+i+1}. [Question]" for i in range(hr_n))}

**Scenario-Based Questions ({scen_n}):**
{chr(10).join(f"{tech_n+proj_n+hr_n+i+1}. [Question]" for i in range(scen_n))}

STRICT RULES:
- Questions should uncover the candidate's background, experience, and depth of expertise
- Candidate level: {level_desc}
- Interview focus: {focus_desc}
- Number them 1-{q_count} exactly as shown
- Open-ended questions only - no yes/no answers
"""

    print(f"\n{'='*60}\n🎬 RESUME INTERVIEW - generating {q_count} questions\n{'='*60}")
    raw = call_openrouter(prompt, temperature=0.3, max_tokens=2500)
    if not raw:
        return jsonify({"ok": False, "msg": "OpenRouter returned no response."}), 503

    questions = parse_numbered_questions(raw, q_count)
    if not questions:
        return jsonify({"ok": False, "msg": f"Parsed fewer than {q_count} questions. Try again."}), 500

    for q in questions:
        n = q["id"]
        if n <= tech_n:                           q["category"] = "Technical"
        elif n <= tech_n + proj_n:                q["category"] = "Project-Based"
        elif n <= tech_n + proj_n + hr_n:         q["category"] = "HR"
        else:                                     q["category"] = "Scenario-Based"

    print(f"✅ {len(questions)} resume questions generated")
    return jsonify({"ok": True, "questions": questions})

# ==================== ROLE-BASED INTERVIEW ====================

@app.route("/api/role/generate", methods=["POST"])
@login_required
def api_role_generate():
    data           = request.get_json()
    role           = data.get("role", "Software Engineer").strip()
    difficulty     = data.get("difficulty",     "mid")
    q_count        = int(data.get("q_count",    10))
    interview_type = data.get("interview_type", "technical")

    level_map = {
        "fresher": "Fresher / Entry-Level (0-1 year) - test conceptual understanding and learning ability",
        "mid":     "Mid-Level (2-4 years) - test applied knowledge, real-world problem solving, and ownership",
        "senior":  "Senior (5+ years) - test architectural thinking, leadership, and advanced expertise",
    }
    focus_map = {
        "technical":  "Technical - role-specific tools, frameworks, design patterns, and architecture decisions",
        "behavioral": "Behavioral - leadership, conflict resolution, ownership, collaboration, STAR-method situations",
        "mixed":      "Mixed - 50% technical role-specific questions, 50% behavioral/situational questions",
    }
    level_desc = level_map.get(difficulty, level_map["mid"])
    focus_desc = focus_map.get(interview_type, focus_map["mixed"])

    if interview_type == "technical":
        tech_n, behav_n, design_n, career_n = max(1, q_count - 3), 1, max(1, q_count // 4), 1
    elif interview_type == "behavioral":
        tech_n, behav_n, design_n, career_n = 1, max(1, q_count - 3), 1, 1
    else:
        tech_n   = max(1, q_count // 3); behav_n  = max(1, q_count // 3)
        design_n = max(1, q_count // 6); career_n = max(0, q_count - tech_n - behav_n - design_n)

    prompt = f"""You are a principal engineer and elite interviewer at a FAANG-level company who has personally hired dozens of {role}s.

Based on the role "{role}", generate EXACTLY {q_count} interview questions in the following format:

**Technical Questions ({tech_n}):**
{chr(10).join(f"{i+1}. [Question]" for i in range(tech_n))}

**Behavioral Questions ({behav_n}):**
{chr(10).join(f"{tech_n+i+1}. [Question]" for i in range(behav_n))}

**System Design / Architecture Questions ({design_n}):**
{chr(10).join(f"{tech_n+behav_n+i+1}. [Question]" for i in range(design_n))}

**Career & Growth Questions ({career_n}):**
{chr(10).join(f"{tech_n+behav_n+design_n+i+1}. [Question]" for i in range(career_n))}

STRICT RULES:
- Every question MUST be specific to a {role} - not generic for any software job
- Technical questions: ask HOW things work, WHEN to choose X over Y, trade-offs, not definitions
- Behavioral: frame real scenarios a {role} actually faces on the job
- System design: scalability, architecture, real-world implementation challenges
- Candidate level: {level_desc}
- Interview focus: {focus_desc}
- Number them 1-{q_count} exactly as shown
- No bold markers, no extra text - just numbered questions
"""

    print(f"\n{'='*60}\n💼 ROLE INTERVIEW ({role}) - generating {q_count} questions\n{'='*60}")
    raw = call_openrouter(prompt, temperature=0.3, max_tokens=2500)
    if not raw:
        return jsonify({"ok": False, "msg": "OpenRouter returned no response."}), 503

    questions = parse_numbered_questions(raw, q_count)
    if not questions:
        return jsonify({"ok": False, "msg": f"Parsed fewer than {q_count} questions. Try again."}), 500

    for q in questions:
        n = q["id"]
        if n <= tech_n:                            q["category"] = "Technical"
        elif n <= tech_n + behav_n:                q["category"] = "Behavioral"
        elif n <= tech_n + behav_n + design_n:     q["category"] = "System Design"
        else:                                      q["category"] = "Career Growth"

    print(f"✅ {len(questions)} role questions generated")
    return jsonify({"ok": True, "questions": questions})

# ==================== APTITUDE ROUND ====================

@app.route("/api/aptitude/generate", methods=["POST"])
@login_required
def api_aptitude_generate():
    data     = request.get_json()
    level    = data.get("level",    "medium").strip().lower()
    category = data.get("category", "all").strip().lower()
    q_count  = int(data.get("q_count", 10))

    cat_map = {
        "all":     "a balanced mix of logical reasoning, quantitative aptitude, verbal ability, and data interpretation",
        "logical": "logical reasoning (number series, letter series, analogies, syllogisms, blood relations, coding-decoding, direction sense, seating arrangements)",
        "quant":   "quantitative aptitude (percentages, profit & loss, simple & compound interest, time & work, pipes & cisterns, speed & distance, ratio & proportion, averages, mixtures)",
        "verbal":  "verbal ability (synonyms, antonyms, sentence completion, fill in the blanks, spotting errors, one-word substitution, para-jumbles, idioms)",
        "data":    "data interpretation (describe inline data tables, bar/pie/line charts in text form, then ask multi-step calculation questions about them)",
        "coding":  "basic programming concepts (time & space complexity, output prediction for code snippets, arrays, linked lists, sorting algorithms, recursion, OOP, SQL basics)",
    }
    diff_map = {
        "easy":   "EASY - single or two-step reasoning, small clean numbers, solvable in under 45 seconds, no tricks",
        "medium": "MEDIUM - 3-5 step reasoning, moderate numbers, some plausible distractors, typical TCS/Infosys placement level, solvable in under 60 seconds",
        "hard":   "HARD - 5+ step multi-concept reasoning, complex logic chains, CAT/ELITMUS level difficulty, solvable in under 90 seconds only by well-prepared candidates",
    }
    topic_desc = cat_map.get(category, cat_map["all"])
    diff_desc  = diff_map.get(level,   diff_map["medium"])

    prompt = f"""You are a senior aptitude test designer with 15+ years of experience creating placement exam questions for TCS, Infosys, Wipro, Amazon, and Google.

Generate EXACTLY {q_count} multiple-choice aptitude questions.

Topic: {topic_desc}
Difficulty: {diff_desc}

For EACH question output it in this EXACT format:

{{number}}. {{question text}}
A) {{option 1}}
B) {{option 2}}
C) {{option 3}}
D) {{option 4}}
Answer: {{correct letter A/B/C/D}}
Explanation: {{step-by-step working}}

STRICT RULES:
- Every question must be fully self-contained (embed any data inline)
- Exactly 4 options per question labelled A) B) C) D)
- Exactly one correct answer per question
- The correct answer letter must VARY - do NOT always put the answer as A or B
- The explanation must show complete step-by-step working
- All arithmetic and logic must be mathematically verified and correct
- Questions must be genuinely distinct
- Output ONLY the questions in the format above - no preamble, no summary, no extra text
"""

    print(f"\n{'='*60}\n🧩 APTITUDE ({level.upper()} / {category}) - generating {q_count} MCQs\n{'='*60}")
    raw = call_openrouter(prompt, temperature=0.4, max_tokens=3500)
    if not raw:
        return jsonify({"ok": False, "msg": "OpenRouter returned no response."}), 503

    questions = parse_mcq_questions(raw, q_count)
    if not questions:
        return jsonify({"ok": False, "msg": f"Parsed fewer than {q_count} MCQ questions. Try again."}), 500

    subcat_map = {
        "logical": "Logical Reasoning", "quant": "Quantitative",
        "verbal":  "Verbal Ability",    "data":  "Data Interpretation",
        "coding":  "Coding Basics",     "all":   "Aptitude",
    }
    default_cat = subcat_map.get(category, "Aptitude")
    for q in questions:
        q.setdefault("category", default_cat)

    print(f"✅ {len(questions)} aptitude MCQs generated")
    return jsonify({"ok": True, "questions": questions})

# ==================== EMAIL HELPER ====================

def send_email(to_email: str, subject: str, html_body: str,
               attachment_path: str = None, attachment_name: str = None) -> bool:
    def build_msg():
        msg = MIMEMultipart()
        msg["From"]    = GMAIL_USER
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition",
                f'attachment; filename="{attachment_name or os.path.basename(attachment_path)}"')
            msg.attach(part)
        return msg

    try:
        print(f"📧 Sending email to {to_email} via port 587...")
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        server.ehlo(); server.starttls(); server.ehlo()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(build_msg()); server.quit()
        print(f"✅ Email sent to {to_email}"); return True
    except Exception as e1:
        print(f"⚠ Port 587 failed: {e1}")

    try:
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=15) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(build_msg())
        print(f"✅ Email sent via port 465"); return True
    except Exception as e2:
        print(f"⚠ Port 465 failed: {e2}")

    print(f"❌ Email delivery failed for {to_email}"); return False


def otp_email_html(otp: str, purpose: str = "verification") -> str:
    label = "Password Reset" if purpose == "reset" else "Email Verification"
    return f"""<html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:30px;">
      <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;">
        <div style="background:#f97316;padding:28px;text-align:center;">
          <h2 style="color:#fff;margin:0;font-size:22px;">JobCooked</h2>
          <p style="color:#ffe0c8;margin:6px 0 0;font-size:13px;">AI Interview Prep Platform</p>
        </div>
        <div style="padding:32px;">
          <h3 style="color:#1e1e2e;margin-top:0;">{label}</h3>
          <p style="color:#444;line-height:1.6;">Your one-time verification code is:</p>
          <div style="background:#fff7f0;border:2px solid #f97316;border-radius:10px;text-align:center;padding:20px;margin:20px 0;">
            <span style="font-size:38px;font-weight:bold;color:#f97316;letter-spacing:8px;">{otp}</span>
          </div>
          <p style="color:#888;font-size:13px;">This code expires in <b>10 minutes</b>.</p>
        </div>
      </div>
    </body></html>"""


def report_email_html(candidate_name: str, interview_type: str, score: float) -> str:
    score_color = "#22c55e" if score >= 70 else "#fbbf24" if score >= 40 else "#ef4444"
    type_label  = {"resume":"Resume Interview","role":"Role-Based Interview",
                   "aptitude":"Aptitude Test"}.get(interview_type.lower(), interview_type)
    return f"""<html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:30px;">
      <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;">
        <div style="background:#f97316;padding:28px;text-align:center;">
          <h2 style="color:#fff;margin:0;font-size:22px;">JobCooked</h2>
          <p style="color:#ffe0c8;margin:6px 0 0;font-size:13px;">Your Interview Report is Ready!</p>
        </div>
        <div style="padding:32px;">
          <h3 style="color:#1e1e2e;margin-top:0;">Hi {candidate_name},</h3>
          <p style="color:#444;line-height:1.6;">Congratulations on completing your <b>{type_label}</b>!</p>
          <div style="background:#fff7f0;border-radius:10px;padding:20px;margin:20px 0;text-align:center;">
            <p style="margin:0;color:#888;font-size:13px;">Overall Score</p>
            <p style="margin:6px 0 0;font-size:42px;font-weight:bold;color:{score_color};">{score:.1f}%</p>
          </div>
          <p style="color:#888;font-size:13px;">Keep practising - every interview makes you better!</p>
        </div>
      </div>
    </body></html>"""

# ==================== OTP ROUTES ====================

@app.route("/api/send-otp", methods=["POST"])
def api_send_otp():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"ok": False, "msg": "Email is required."}), 400
    if not get_user_by_email(email):
        return jsonify({"ok": False, "msg": "No account found with this email."}), 404

    otp = str(random.randint(100000, 999999))
    otp_storage[email] = {"otp": otp, "expiry": datetime.now() + timedelta(minutes=10), "verified": False}

    sent = send_email(to_email=email, subject="JobCooked - Password Reset OTP",
                      html_body=otp_email_html(otp, purpose="reset"))
    if not sent:
        print(f"⚠ DEV MODE OTP for {email}: {otp}")
    return jsonify({"ok": True, "msg": f"OTP sent to {email}"})


@app.route("/api/verify-otp", methods=["POST"])
def api_verify_otp():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    otp   = data.get("otp",   "").strip()

    if not email or not otp:
        return jsonify({"ok": False, "msg": "Email and OTP are required."}), 400
    if email not in otp_storage:
        return jsonify({"ok": False, "msg": "OTP not found. Please request a new one."}), 404

    stored = otp_storage[email]
    if datetime.now() > stored["expiry"]:
        del otp_storage[email]
        return jsonify({"ok": False, "msg": "OTP has expired. Please request a new one."}), 400
    if stored["otp"] != otp:
        return jsonify({"ok": False, "msg": "Incorrect OTP. Please try again."}), 400

    otp_storage[email]["verified"] = True
    return jsonify({"ok": True, "msg": "OTP verified successfully."})


@app.route("/api/reset-password", methods=["POST"])
def api_reset_password():
    data    = request.get_json()
    email   = data.get("email",        "").strip().lower()
    new_pwd = data.get("new_password", "").strip()

    if not email or not new_pwd:
        return jsonify({"ok": False, "msg": "Email and new password are required."}), 400
    if len(new_pwd) < 8:
        return jsonify({"ok": False, "msg": "Password must be at least 8 characters."}), 400
    if email not in otp_storage or not otp_storage[email].get("verified"):
        return jsonify({"ok": False, "msg": "Please verify your OTP first."}), 400
    if not get_user_by_email(email):
        return jsonify({"ok": False, "msg": "Account not found."}), 404

    update_user_password(email, generate_password_hash(new_pwd))
    del otp_storage[email]
    print(f"✅ Password reset for {email}")
    return jsonify({"ok": True, "msg": "Password reset successfully. You can now log in."})

# ==================== REPORT GENERATION + EMAIL ====================

@app.route("/api/report/generate", methods=["POST"])
@login_required
def api_generate_report():
    data  = request.get_json()
    user  = get_user_by_email(session["user_email"])
    candidate_name  = user.name  if user else "Candidate"
    candidate_email = user.email if user else session["user_email"]

    interview_type = data.get("interview_type", "interview")
    overall_score  = float(data.get("overall_score", 0))
    questions      = data.get("questions", [])

    if not questions:
        return jsonify({"ok": False, "msg": "No questions provided for report."}), 400

    report_data = {
        "candidate_name":  candidate_name,
        "candidate_email": candidate_email,
        "interview_type":  interview_type,
        "overall_score":   overall_score,
        "date":            datetime.now().strftime("%d %B %Y, %I:%M %p"),
        "questions":       questions,
    }
    for key in ("speech_score", "content_score", "role", "level", "category"):
        if data.get(key) is not None:
            report_data[key] = float(data[key]) if key.endswith("_score") else data[key]

    safe_name  = re.sub(r'[^a-zA-Z0-9]', '_', candidate_name).strip('_')
    type_label = {"resume": "Resume", "role": "Role_Interview", "aptitude": "Aptitude"}.get(interview_type, interview_type.capitalize())
    pdf_name   = f"JobCooked_{type_label}_Report_{safe_name}.pdf"
    pdf_path   = os.path.join(REPORT_FOLDER, pdf_name)

    if not report_generator.generate_report(report_data, pdf_path):
        return jsonify({"ok": False, "msg": "PDF generation failed."}), 500

    sent = send_email(
        to_email        = candidate_email,
        subject         = f"JobCooked - Your {interview_type.capitalize()} Interview Report",
        html_body       = report_email_html(candidate_name, interview_type, overall_score),
        attachment_path = pdf_path,
        attachment_name = pdf_name,
    )
    msg = f"Report sent to {candidate_email}" if sent else "Report generated but email failed. Check GMAIL config."
    return jsonify({"ok": True, "msg": msg, "emailed": sent, "filename": pdf_name})

# ==================== ANSWER ANALYSIS ====================

@app.route("/api/analyze-answer", methods=["POST"])
@login_required
def api_analyze_answer():
    data           = request.get_json()
    question       = data.get("question", "").strip()
    answer         = data.get("answer",   "").strip()
    interview_type = data.get("interview_type", "resume")
    category       = data.get("category", "General")

    if not answer or len(answer.strip()) < 5:
        return jsonify({"ok": True,
            "speaking":       {"score":0,"clarity":0,"pace":0,"confidence":0,"structure":0,
                               "feedback":"No answer was given.","filler_words":[],"word_count":0},
            "answer_quality": {"score":0,"relevance":0,"depth":0,"accuracy":0,"examples":0,
                               "feedback":"No answer provided.","strengths":[],"improvements":["Give a complete answer","Use the STAR method"]},
            "overall_score":0, "verdict":"No Answer"})

    words          = answer.split()
    word_count     = len(words)
    sentences      = [s.strip() for s in re.split(r'[.!?]', answer) if s.strip()]
    sentence_count = max(len(sentences), 1)
    avg_wps        = word_count / sentence_count

    FILLER_WORDS  = ["um","uh","like","you know","basically","actually","literally","honestly","kind of","sort of","right","okay so"]
    found_fillers = [fw for fw in FILLER_WORDS if fw in answer.lower()]
    filler_count  = sum(answer.lower().count(fw) for fw in FILLER_WORDS)

    prompt = f"""You are an expert interview coach and communication skills evaluator.

Analyze this candidate's interview answer on TWO separate dimensions.

INTERVIEW TYPE: {interview_type}
QUESTION CATEGORY: {category}
QUESTION: {question}
CANDIDATE'S ANSWER: {answer}

WORD COUNT: {word_count} words | SENTENCES: {sentence_count} | AVG WORDS/SENTENCE: {avg_wps:.1f}
FILLER WORDS DETECTED: {', '.join(found_fillers) if found_fillers else 'None'}

=== DIMENSION 1: SPEAKING QUALITY ===
- Clarity (0-100): Are sentences clear, well-formed, and easy to follow?
- Pace (0-100): Is the length appropriate? Too short (<20 words)=30, ideal (40-120 words)=85-95, too long (>200 words)=60
- Confidence (0-100): Does the language sound confident? Penalize heavily for filler words and hedging
- Structure (0-100): Is the answer organized logically with a beginning, middle, end?

=== DIMENSION 2: ANSWER QUALITY ===
- Relevance (0-100): Does the answer directly address the question asked?
- Depth (0-100): Does it go beyond surface level and show genuine understanding?
- Accuracy (0-100): Is the technical/factual content correct and credible?
- Examples (0-100): Does it include specific examples, numbers, outcomes, or real experiences?

BE HONEST AND STRICT. A short vague answer should score LOW. A detailed specific answer should score HIGH.

Respond ONLY with this exact JSON (no markdown, no extra text):
{{
  "speaking": {{
    "clarity": <0-100>, "pace": <0-100>, "confidence": <0-100>, "structure": <0-100>,
    "feedback": "<2-3 sentences: specific actionable speaking feedback>",
    "top_issue": "<single biggest speaking problem>"
  }},
  "answer_quality": {{
    "relevance": <0-100>, "depth": <0-100>, "accuracy": <0-100>, "examples": <0-100>,
    "feedback": "<2-3 sentences: specific actionable content feedback>",
    "strengths": ["<strength 1>", "<strength 2>"],
    "improvements": ["<improvement 1>", "<improvement 2>"]
  }}
}}"""

    try:
        raw    = call_openrouter(prompt, temperature=0.3, max_tokens=600)
        if not raw: raise ValueError("No response from AI")
        clean  = raw.replace("```json","").replace("```","").strip()
        s      = clean.find("{"); e = clean.rfind("}")
        result = json.loads(clean[s:e+1])
        sp     = result.get("speaking",       {})
        aq     = result.get("answer_quality", {})
        sp_score = round((sp.get("clarity",0)+sp.get("pace",0)+sp.get("confidence",0)+sp.get("structure",0))/4)
        aq_score = round((aq.get("relevance",0)+aq.get("depth",0)+aq.get("accuracy",0)+aq.get("examples",0))/4)
        overall  = round(sp_score * 0.35 + aq_score * 0.65)
        verdict  = "Excellent" if overall>=80 else "Good" if overall>=60 else "Fair" if overall>=40 else "Needs Work"
        return jsonify({"ok":True,
            "speaking":       {"score":sp_score,"clarity":sp.get("clarity",0),"pace":sp.get("pace",0),
                               "confidence":sp.get("confidence",0),"structure":sp.get("structure",0),
                               "feedback":sp.get("feedback",""),"top_issue":sp.get("top_issue",""),
                               "filler_words":found_fillers,"word_count":word_count},
            "answer_quality": {"score":aq_score,"relevance":aq.get("relevance",0),"depth":aq.get("depth",0),
                               "accuracy":aq.get("accuracy",0),"examples":aq.get("examples",0),
                               "feedback":aq.get("feedback",""),"strengths":aq.get("strengths",[]),
                               "improvements":aq.get("improvements",[])},
            "overall_score":overall, "verdict":verdict})
    except Exception as e:
        print(f"Analysis error: {e}")
        sp_score = max(20, min(85, 50 + (word_count-20)*0.5 - filler_count*5))
        aq_score = max(20, min(90, 40 + word_count*0.8))
        overall  = round(sp_score*0.35 + aq_score*0.65)
        return jsonify({"ok":True,
            "speaking":       {"score":round(sp_score),"clarity":round(sp_score),"pace":round(sp_score),
                               "confidence":round(sp_score),"structure":round(sp_score),
                               "feedback":"Speak clearly and avoid filler words.","top_issue":"See feedback",
                               "filler_words":found_fillers,"word_count":word_count},
            "answer_quality": {"score":round(aq_score),"relevance":round(aq_score),"depth":round(aq_score),
                               "accuracy":round(aq_score),"examples":round(aq_score),
                               "feedback":"Add specific examples and quantifiable outcomes.",
                               "strengths":["Attempted the question"],"improvements":["Add more examples","Use STAR method"]},
            "overall_score":overall, "verdict":"Good" if overall>=60 else "Fair"})

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error"}), 500

# ==================== RUN ====================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("JobCooked - AI Interview Prep")
    print("="*60)
    db_type = "PostgreSQL" if os.environ.get("DATABASE_URL") else "SQLite (local)"
    print(f"  Database : {db_type}")
    print(f"  Model    : {OPENROUTER_MODEL}")
    print(f"  URL      : http://localhost:5000")
    print("="*60 + "\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
