#!/usr/bin/env python3
"""
Study Planner — Flask App (Clean GitHub Version)
Converted from Colab version by removing:
- !pip install
- %%writefile
- start_colab
- google.colab proxy functions

Everything else remains functional.
"""

from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, io, csv, json, os, threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

DB_PATH = "study_planner.db"
SECRET_KEY = os.environ.get("STUDY_SECRET", "replace-with-secure-secret")
APP_NAME = "Study Planner"
DEBUG = True

app = Flask(__name__)
app.secret_key = SECRET_KEY

scheduler = BackgroundScheduler(executors={"default": ThreadPoolExecutor(4)})
scheduler.start()

# ---------------- DB helpers ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        full_name TEXT,
        education_level TEXT,
        interests TEXT,
        created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS profiles (
        user_id INTEGER PRIMARY KEY,
        learning_style TEXT,
        baseline INTEGER,
        goals TEXT,
        playlist TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        title TEXT,
        subject TEXT,
        due_date TEXT,
        priority INTEGER DEFAULT 3,
        done INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        task_id INTEGER,
        minutes INTEGER,
        mood TEXT,
        note TEXT,
        timestamp TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        message TEXT,
        fire_at TEXT,
        recurring INTEGER DEFAULT 0,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

def get_db_rows(query, params=(), one=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows[0] if one else rows

def run_db(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    last = cur.lastrowid
    conn.close()
    return last
  # ---------------- Reminder scheduling ----------------
def schedule_reminder_job(rem_id, user_id, message, fire_at_iso, recurring_minutes):
    job_id = f"reminder_{rem_id}"

    def job_func():
        run_db(
            'INSERT INTO sessions (user_id, task_id, minutes, mood, note, timestamp) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, None, 0, 'neutral', f'REMINDER: {message}',
             datetime.utcnow().isoformat())
        )
        print(f"[Reminder fired] uid={user_id} msg={message}")

    try:
        fire_dt = datetime.fromisoformat(fire_at_iso)
    except:
        print("Invalid date format")
        return

    try:
        scheduler.remove_job(job_id)
    except:
        pass

    if recurring_minutes and recurring_minutes > 0:
        scheduler.add_job(
            job_func,
            'interval',
            minutes=recurring_minutes,
            id=job_id,
            next_run_time=fire_dt
        )
    else:
        scheduler.add_job(job_func, 'date', run_date=fire_dt, id=job_id)


for r in get_db_rows("SELECT id, user_id, message, fire_at, recurring FROM reminders"):
    try:
        schedule_reminder_job(r["id"], r["user_id"], r["message"], r["fire_at"], r["recurring"])
    except Exception as e:
        print("Failed to load reminder", e)


# ---------------- Templates ----------------
BASE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{title}}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body{font-family:Inter,Arial;margin:18px;max-width:1100px}
    nav a{margin-right:10px}
    .card{border:1px solid #ddd;padding:14px;border-radius:8px;margin-bottom:12px}
    input,textarea,select{padding:8px;width:100%;margin:6px 0;border-radius:6px;border:1px solid #ccc}
  </style>
</head>
<body>
<header>
  <h2>{{app_name}}</h2>
  <nav>
    <a href="{{url_for('home')}}">Home</a>
    {% if session.get('user') %}
      <a href="{{url_for('dashboard')}}">Dashboard</a>
      <a href="{{url_for('profile')}}">Profile</a>
      <a href="{{url_for('tasks')}}">Tasks</a>
      <a href="{{url_for('sessions')}}">Sessions</a>
      <a href="{{url_for('reminders')}}">Reminders</a>
      <a href="{{url_for('logout')}}">Logout</a>
    {% else %}
      <a href="{{url_for('login')}}">Login</a>
      <a href="{{url_for('register')}}">Register</a>
    {% endif %}
  </nav>
</header>
<hr>
<main>
{{ body|safe }}
</main>
</body>
</html>
"""


# ---------------- Helper ----------------
def current_user():
    if "user_id" in session:
        return get_db_rows("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)
    return None


# ---------------- Routes ----------------
@app.route("/")
def home():
    return render_template_string(
        BASE_HTML,
        title="Home",
        app_name=APP_NAME,
        body="<div class='card'><h3>Welcome to Study Planner</h3></div>"
    )


# -------- Register --------
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        full = request.form.get("full_name")
        level = request.form.get("education_level")
        interests = request.form.get("interests")
        if not u or not p:
            return "Username & password required", 400
        hashed = generate_password_hash(p)
        try:
            run_db(
                "INSERT INTO users (username,password,full_name,education_level,interests,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (u,hashed,full,level,interests,datetime.utcnow().isoformat())
            )
        except Exception as e:
            return f"Error: {e}"
        return redirect(url_for('login'))

    body = """
    <div class='card'>
      <h3>Register</h3>
      <form method="post">
        Full name <input name="full_name">
        Username <input name="username" required>
        Password <input type="password" name="password" required>
        Education <input name="education_level">
        Interests <input name="interests">
        <button>Register</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, title="Register", app_name=APP_NAME, body=body)


# -------- Login --------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        user = get_db_rows("SELECT * FROM users WHERE username=?", (u,), one=True)
        if user and check_password_hash(user["password"], p):
            session["user_id"] = user["id"]
            session["user"] = user["username"]
            return redirect(url_for("dashboard"))
        return "Invalid credentials", 401

    body = """
    <div class='card'>
      <h3>Login</h3>
      <form method="post">
        Username <input name="username">
        Password <input type="password" name="password">
        <button>Login</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, title="Login", app_name=APP_NAME, body=body)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# -------- Tasks --------
@app.route("/tasks", methods=["GET","POST"])
def tasks():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        subject = request.form.get("subject")
        due = request.form.get("due_date") or ""
        priority = int(request.form.get("priority") or 3)
        run_db(
            "INSERT INTO tasks (user_id,title,subject,due_date,priority,created_at) VALUES (?,?,?,?,?,?)",
            (user["id"],title,subject,due,priority,datetime.utcnow().isoformat())
        )
        return redirect(url_for("tasks"))

    rows = get_db_rows("SELECT * FROM tasks WHERE user_id=? ORDER BY priority ASC", (user["id"],))
    html = ""
    for r in rows:
        html += f"<div class='card'><b>{r['title']}</b> — {r['subject']} (Due: {r['due_date']})</div>"

    form = """
    <div class='card'>
      <h3>Add Task</h3>
      <form method="post">
        Title <input name="title" required>
        Subject <input name="subject">
        Due date <input type="date" name="due_date">
        Priority <input name="priority" placeholder="3">
        <button>Add Task</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, title="Tasks", app_name=APP_NAME, body=form+html)


# -------- Sessions --------
@app.route("/sessions", methods=["GET","POST"])
def sessions():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        minutes = int(request.form.get("minutes") or 0)
        mood = request.form.get("mood") or "neutral"
        note = request.form.get("note") or ""
        run_db(
            "INSERT INTO sessions (user_id,minutes,mood,note,timestamp) VALUES (?,?,?,?,?)",
            (user["id"],minutes,mood,note,datetime.utcnow().isoformat())
        )
        return redirect(url_for("sessions"))

    rows = get_db_rows("SELECT * FROM sessions WHERE user_id=? ORDER BY timestamp DESC", (user["id"],))
    html = ""
    for s in rows:
        html += f"<div class='card'>{s['timestamp']} — {s['minutes']} min — {s['note']}</div>"

    form = """
    <div class='card'>
      <h3>Log Session</h3>
      <form method="post">
        Minutes <input name="minutes" required>
        Mood <input name="mood">
        Note <textarea name="note"></textarea>
        <button>Save</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, title="Sessions", app_name=APP_NAME, body=form+html)


# -------- Reminders --------
@app.route("/reminders", methods=["GET","POST"])
def reminders():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        msg = request.form.get("message")
        t = request.form.get("fire_at")
        recurring = int(request.form.get("recurring") or 0)

        dt = datetime.fromisoformat(t)
        iso = dt.isoformat()

        rid = run_db(
            "INSERT INTO reminders (user_id,message,fire_at,recurring,created_at) VALUES (?,?,?,?,?)",
            (user["id"],msg,iso,recurring,datetime.utcnow().isoformat())
        )

        schedule_reminder_job(rid, user["id"], msg, iso, recurring)
        return redirect(url_for("reminders"))

    rows = get_db_rows("SELECT * FROM reminders WHERE user_id=? ORDER BY fire_at", (user["id"],))
    html = ""
    for r in rows:
        html += f"<div class='card'>At: {r['fire_at']} — {r['message']}</div>"

    form = """
    <div class='card'>
      <h3>Set Reminder</h3>
      <form method="post">
        Message <input name="message" required>
        Fire at (YYYY-MM-DD HH:MM) <input name="fire_at" required>
        Recurring minutes <input name="recurring" placeholder="0">
        <button>Save</button>
      </form>
    </div>
    """
    return render_template_string(BASE_HTML, title="Reminders", app_name=APP_NAME, body=form+html)


# -------- Dashboard --------
@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    total_minutes = get_db_rows(
        "SELECT SUM(minutes) as s FROM sessions WHERE user_id=?",
        (user["id"],),
        one=True
    )["s"]

    tasks = get_db_rows(
        "SELECT COUNT(*) as c FROM tasks WHERE user_id=?",
        (user["id"],),
        one=True
    )["c"]

    done = get_db_rows(
        "SELECT COUNT(*) as c FROM tasks WHERE user_id=? AND done=1",
        (user["id"],),
        one=True
    )["c"]

    body = f"""
    <div class='card'>
      <h3>Dashboard</h3>
      <p>Total Minutes: {total_minutes}</p>
      <p>Total Tasks: {tasks}</p>
      <p>Completed: {done}</p>
    </div>
    """
    return render_template_string(BASE_HTML, title="Dashboard", app_name=APP_NAME, body=body)


# -------- Export CSV --------
@app.route("/export/sessions")
def export_sessions():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    rows = get_db_rows("SELECT * FROM sessions WHERE user_id=?", (user["id"],))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id","minutes","mood","note","timestamp"])
    for r in rows:
        writer.writerow([r["id"],r["minutes"],r["mood"],r["note"],r["timestamp"]])

    mem = io.BytesIO(output.getvalue().encode())
    mem.seek(0)
    return send_file(mem, download_name="sessions.csv", as_attachment=True)


# ---------------- Run Server ----------------
if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=DEBUG)
