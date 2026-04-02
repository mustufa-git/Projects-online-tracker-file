from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json, os, sqlite3, hashlib
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "tracker_secret_2026_xyz")

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker.db")

# ── Database setup ──────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT,
            pc_name TEXT
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client TEXT NOT NULL,
            project TEXT NOT NULL,
            deadline TEXT,
            payment INTEGER DEFAULT 0,
            status TEXT DEFAULT 'নতুন কাজ',
            paid TEXT DEFAULT 'বাকি',
            path TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS project_assignments (
            project_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (project_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            detail TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        """)
        # Default admin
        existing = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        if not existing:
            db.execute("INSERT INTO users (name, username, password, role) VALUES (?,?,?,?)",
                ("Admin", "admin", hash_pw("admin123"), "admin"))
            db.commit()

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def log_activity(user_id, action, detail=""):
    with get_db() as db:
        db.execute("INSERT INTO activity_log (user_id, action, detail) VALUES (?,?,?)",
            (user_id, action, detail))
        db.commit()

# ── Auth helpers ────────────────────────────────────────────
def current_user():
    uid = session.get("user_id")
    if not uid: return None
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(row) if row else None

def require_login(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        u = current_user()
        if not u or u["role"] != "admin":
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

# ── Pages ───────────────────────────────────────────────────
@app.route("/")
def index():
    u = current_user()
    if u: return redirect(url_for("dashboard"))
    return redirect(url_for("login_page"))

@app.route("/login")
def login_page():
    if current_user(): return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/dashboard")
@require_login
def dashboard():
    return render_template("app.html", user=current_user())

# ── Auth API ────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def do_login():
    d = request.get_json()
    with get_db() as db:
        u = db.execute("SELECT * FROM users WHERE username=? AND password=?",
            (d.get("username",""), hash_pw(d.get("password","")))).fetchone()
        if u:
            u = dict(u)
            session["user_id"] = u["id"]
            session.permanent = True
            db.execute("UPDATE users SET last_login=?, pc_name=? WHERE id=?",
                (datetime.now().isoformat(), d.get("pc_name",""), u["id"]))
            db.commit()
            log_activity(u["id"], "login", f"Login from {d.get('pc_name','unknown')}")
            return jsonify({"ok": True, "user": {k: u[k] for k in ["id","name","username","role"]}})
    return jsonify({"ok": False, "error": "Username বা password ভুল!"})

@app.route("/api/logout", methods=["POST"])
def do_logout():
    u = current_user()
    if u: log_activity(u["id"], "logout", "")
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/me")
def me():
    u = current_user()
    return jsonify({"user": u})

@app.route("/api/change-password", methods=["POST"])
@require_login
def change_password():
    d = request.get_json()
    u = current_user()
    with get_db() as db:
        row = db.execute("SELECT password FROM users WHERE id=?", (u["id"],)).fetchone()
        if row["password"] != hash_pw(d.get("oldPassword","")):
            return jsonify({"ok": False, "error": "পুরানো password ভুল!"})
        if len(d.get("newPassword","")) < 4:
            return jsonify({"ok": False, "error": "Password কমপক্ষে ৪ অক্ষর হতে হবে"})
        db.execute("UPDATE users SET password=? WHERE id=?", (hash_pw(d["newPassword"]), u["id"]))
        db.commit()
        log_activity(u["id"], "password_change", "")
    return jsonify({"ok": True})

# ── Users API ────────────────────────────────────────────────
@app.route("/api/users")
@require_login
def get_users():
    with get_db() as db:
        rows = db.execute("SELECT id,name,username,role,last_login,pc_name FROM users").fetchall()
        users = []
        for r in rows:
            u = dict(r)
            # count projects assigned
            cnt = db.execute("SELECT COUNT(*) as c FROM project_assignments WHERE user_id=?", (u["id"],)).fetchone()["c"]
            done = db.execute("""SELECT COUNT(*) as c FROM projects p
                JOIN project_assignments pa ON p.id=pa.project_id
                WHERE pa.user_id=? AND p.status='সম্পন্ন'""", (u["id"],)).fetchone()["c"]
            u["project_count"] = cnt
            u["done_count"] = done
            users.append(u)
    return jsonify({"users": users})

@app.route("/api/users/add", methods=["POST"])
@require_admin
def add_user():
    d = request.get_json()
    if not d.get("name") or not d.get("username") or not d.get("password"):
        return jsonify({"ok": False, "error": "সব তথ্য দাও"})
    try:
        with get_db() as db:
            db.execute("INSERT INTO users (name,username,password,role) VALUES (?,?,?,?)",
                (d["name"], d["username"], hash_pw(d["password"]), d.get("role","viewer")))
            db.commit()
            log_activity(current_user()["id"], "add_user", d["username"])
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "এই username আগেই আছে!"})

@app.route("/api/users/delete", methods=["POST"])
@require_admin
def delete_user():
    uid = request.get_json().get("id")
    if uid == current_user()["id"]:
        return jsonify({"ok": False, "error": "নিজেকে বাদ দেওয়া যাবে না!"})
    with get_db() as db:
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.execute("DELETE FROM project_assignments WHERE user_id=?", (uid,))
        db.commit()
        log_activity(current_user()["id"], "delete_user", str(uid))
    return jsonify({"ok": True})

@app.route("/api/users/reset-password", methods=["POST"])
@require_admin
def reset_password():
    d = request.get_json()
    with get_db() as db:
        db.execute("UPDATE users SET password=? WHERE id=?", (hash_pw(d["newPassword"]), d["id"]))
        db.commit()
    return jsonify({"ok": True})

# ── Projects API ─────────────────────────────────────────────
@app.route("/api/projects")
@require_login
def get_projects():
    u = current_user()
    with get_db() as db:
        if u["role"] == "admin":
            rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        else:
            rows = db.execute("""SELECT p.* FROM projects p
                JOIN project_assignments pa ON p.id=pa.project_id
                WHERE pa.user_id=? ORDER BY p.created_at DESC""", (u["id"],)).fetchall()
        projects = []
        for r in rows:
            p = dict(r)
            assigned = db.execute("SELECT u.id,u.name FROM users u JOIN project_assignments pa ON u.id=pa.user_id WHERE pa.project_id=?", (p["id"],)).fetchall()
            p["assignedTo"] = [{"id": a["id"], "name": a["name"]} for a in assigned]
            projects.append(p)
    return jsonify({"projects": projects})

@app.route("/api/projects/add", methods=["POST"])
@require_admin
def add_project():
    d = request.get_json()
    u = current_user()
    with get_db() as db:
        cur = db.execute("""INSERT INTO projects (client,project,deadline,payment,status,paid,path,notes,created_by)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (d["client"], d["project"], d.get("deadline",""), d.get("payment",0),
             d.get("status","নতুন কাজ"), d.get("paid","বাকি"), d.get("path",""), d.get("notes",""), u["id"]))
        pid = cur.lastrowid
        for uid in d.get("assignedTo", []):
            db.execute("INSERT OR IGNORE INTO project_assignments VALUES (?,?)", (pid, uid))
        db.commit()
        log_activity(u["id"], "add_project", d["project"])
    return jsonify({"ok": True})

@app.route("/api/projects/update", methods=["POST"])
@require_admin
def update_project():
    d = request.get_json()
    pid = d["id"]
    with get_db() as db:
        db.execute("""UPDATE projects SET client=?,project=?,deadline=?,payment=?,status=?,paid=?,path=?,notes=?,updated_at=datetime('now')
            WHERE id=?""",
            (d["client"], d["project"], d.get("deadline",""), d.get("payment",0),
             d.get("status","নতুন কাজ"), d.get("paid","বাকি"), d.get("path",""), d.get("notes",""), pid))
        db.execute("DELETE FROM project_assignments WHERE project_id=?", (pid,))
        for uid in d.get("assignedTo", []):
            db.execute("INSERT OR IGNORE INTO project_assignments VALUES (?,?)", (pid, uid))
        db.commit()
        log_activity(current_user()["id"], "update_project", d["project"])
    return jsonify({"ok": True})

@app.route("/api/projects/toggle-status", methods=["POST"])
@require_admin
def toggle_status():
    pid = request.get_json()["id"]
    cycle = ["নতুন কাজ","চলছে","সম্পন্ন"]
    with get_db() as db:
        cur = db.execute("SELECT status FROM projects WHERE id=?", (pid,)).fetchone()
        if cur:
            nxt = cycle[(cycle.index(cur["status"])+1) % len(cycle)]
            db.execute("UPDATE projects SET status=?,updated_at=datetime('now') WHERE id=?", (nxt, pid))
            db.commit()
    return jsonify({"ok": True})

@app.route("/api/projects/toggle-paid", methods=["POST"])
@require_admin
def toggle_paid():
    pid = request.get_json()["id"]
    with get_db() as db:
        cur = db.execute("SELECT paid FROM projects WHERE id=?", (pid,)).fetchone()
        if cur:
            nxt = "পেয়েছি" if cur["paid"]=="বাকি" else "বাকি"
            db.execute("UPDATE projects SET paid=?,updated_at=datetime('now') WHERE id=?", (nxt, pid))
            db.commit()
    return jsonify({"ok": True})

@app.route("/api/projects/delete", methods=["POST"])
@require_admin
def delete_project():
    pid = request.get_json()["id"]
    with get_db() as db:
        db.execute("DELETE FROM projects WHERE id=?", (pid,))
        db.execute("DELETE FROM project_assignments WHERE project_id=?", (pid,))
        db.commit()
        log_activity(current_user()["id"], "delete_project", str(pid))
    return jsonify({"ok": True})

# ── Stats & Activity ─────────────────────────────────────────
@app.route("/api/stats")
@require_login
def get_stats():
    u = current_user()
    with get_db() as db:
        if u["role"] == "admin":
            total = db.execute("SELECT COUNT(*) as c FROM projects").fetchone()["c"]
            done = db.execute("SELECT COUNT(*) as c FROM projects WHERE status='সম্পন্ন'").fetchone()["c"]
            paona = db.execute("SELECT COALESCE(SUM(payment),0) as s FROM projects WHERE paid='বাকি'").fetchone()["s"]
            peyechi = db.execute("SELECT COALESCE(SUM(payment),0) as s FROM projects WHERE paid='পেয়েছি'").fetchone()["s"]
            online_users = db.execute("SELECT COUNT(*) as c FROM users WHERE last_login IS NOT NULL").fetchone()["c"]
            logs = db.execute("""SELECT al.*, u.name FROM activity_log al
                JOIN users u ON al.user_id=u.id ORDER BY al.timestamp DESC LIMIT 10""").fetchall()
            return jsonify({
                "total": total, "done": done, "pending": total-done,
                "paona": paona, "peyechi": peyechi, "online_users": online_users,
                "logs": [dict(l) for l in logs]
            })
        else:
            total = db.execute("SELECT COUNT(*) as c FROM project_assignments WHERE user_id=?", (u["id"],)).fetchone()["c"]
            done = db.execute("""SELECT COUNT(*) as c FROM projects p JOIN project_assignments pa ON p.id=pa.project_id
                WHERE pa.user_id=? AND p.status='সম্পন্ন'""", (u["id"],)).fetchone()["c"]
            return jsonify({"total": total, "done": done, "pending": total-done})

@app.route("/api/activity")
@require_admin
def get_activity():
    with get_db() as db:
        logs = db.execute("""SELECT al.*, u.name FROM activity_log al
            JOIN users u ON al.user_id=u.id ORDER BY al.timestamp DESC LIMIT 20""").fetchall()
    return jsonify({"logs": [dict(l) for l in logs]})

if __name__ == '__main__':
    with app.app_context():
        try:
            init_db()
        except Exception as e:
            print(f"Database error: {e}")
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
