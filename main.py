"""
Discipline OS — Backend v3
AI Manager + Smart Tasks + Telegram Check-ins + DeepSeek
"""

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any
import sqlite3, json, hashlib, hmac, base64, os, time, re, uuid
import asyncio, httpx, uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── CONFIG ────────────────────────────────────────────────────────────────────
SECRET_KEY       = os.environ.get("SECRET_KEY", "")
TOKEN_EXPIRE_DAYS= 30
DB_PATH          = os.environ.get("DB_PATH", "discipline.db")
PORT             = int(os.environ.get("PORT", 5321))
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL     = "https://api.deepseek.com/v1/chat/completions"
FRONTEND_DIR     = os.path.join(os.path.dirname(__file__), "frontend")
TG_TOKEN         = os.environ.get("TG_TOKEN", "")
TG_API           = f"https://api.telegram.org/bot{TG_TOKEN}"

# ─── APP ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Discipline OS", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
security = HTTPBearer(auto_error=False)

# ─── DATABASE ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, created TEXT NOT NULL,
        tg_chat_id TEXT DEFAULT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS habit_data (
        user_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id          TEXT PRIMARY KEY,
        user_id     INTEGER NOT NULL,
        title       TEXT NOT NULL,
        detail      TEXT DEFAULT '',
        task_type   TEXT DEFAULT 'personal',
        status      TEXT DEFAULT 'pending',
        priority    TEXT DEFAULT 'medium',
        target_qty  INTEGER DEFAULT 0,
        done_qty    INTEGER DEFAULT 0,
        start_time  TEXT DEFAULT NULL,
        deadline    TEXT DEFAULT NULL,
        checkin_interval INTEGER DEFAULT 60,
        date        TEXT NOT NULL,
        created     TEXT NOT NULL,
        updated     TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS checkins (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id     TEXT NOT NULL,
        user_id     INTEGER NOT NULL,
        done_qty    INTEGER DEFAULT 0,
        note        TEXT DEFAULT '',
        ai_response TEXT DEFAULT '',
        ts          TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ai_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, ts TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    # Migrate: add tg_chat_id column if not exists
    try:
        c.execute("ALTER TABLE users ADD COLUMN tg_chat_id TEXT DEFAULT NULL")
    except: pass
    # Migrate tasks table columns
    for col, defn in [
        ("task_type","TEXT DEFAULT 'personal'"),
        ("target_qty","INTEGER DEFAULT 0"),
        ("done_qty","INTEGER DEFAULT 0"),
        ("start_time","TEXT DEFAULT NULL"),
        ("deadline","TEXT DEFAULT NULL"),
        ("checkin_interval","INTEGER DEFAULT 60"),
    ]:
        try: c.execute(f"ALTER TABLE tasks ADD COLUMN {col} {defn}")
        except: pass
    conn.commit()
    conn.close()

init_db()

# ─── AUTH ──────────────────────────────────────────────────────────────────────
def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def make_token(uid, uname):
    pl = json.dumps({"uid":uid,"u":uname,"exp":time.time()+TOKEN_EXPIRE_DAYS*86400})
    b  = base64.urlsafe_b64encode(pl.encode()).decode()
    s  = hmac.new(SECRET_KEY.encode(), b.encode(), hashlib.sha256).hexdigest()
    return f"{b}.{s}"

def verify_token(tok):
    try:
        b, s = tok.rsplit(".", 1)
        if not hmac.compare_digest(s, hmac.new(SECRET_KEY.encode(), b.encode(), hashlib.sha256).hexdigest()):
            raise ValueError()
        pl = json.loads(base64.urlsafe_b64decode(b.encode()).decode())
        if pl["exp"] < time.time(): raise ValueError("expired")
        return pl
    except:
        raise HTTPException(401, "Invalid or expired token")

def current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: sqlite3.Connection = Depends(get_db)):
    if not creds: raise HTTPException(401, "Not authenticated")
    pl  = verify_token(creds.credentials)
    row = db.execute("SELECT id,username,tg_chat_id FROM users WHERE id=?", (pl["uid"],)).fetchone()
    if not row: raise HTTPException(401, "User not found")
    return {"id": row["id"], "username": row["username"], "tg_chat_id": row["tg_chat_id"]}

# ─── SCHEMAS ───────────────────────────────────────────────────────────────────
class RegReq(BaseModel):
    username: str; password: str

class LoginReq(BaseModel):
    username: str; password: str

class SaveDataReq(BaseModel):
    data: Any

class TaskReq(BaseModel):
    id:               Optional[str]  = None
    title:            str
    detail:           Optional[str]  = ""
    task_type:        Optional[str]  = "personal"   # 'work' | 'personal'
    status:           Optional[str]  = "pending"
    priority:         Optional[str]  = "medium"
    target_qty:       Optional[int]  = 0            # e.g. 50 PRs
    done_qty:         Optional[int]  = 0
    start_time:       Optional[str]  = None         # "09:00"
    deadline:         Optional[str]  = None         # "17:00"
    checkin_interval: Optional[int]  = 60           # minutes
    date:             Optional[str]  = None

class CheckinReq(BaseModel):
    task_id:  str
    done_qty: int
    note:     Optional[str] = ""

class ChatReq(BaseModel):
    message: str
    context: Optional[Any] = None

class TgChatIdReq(BaseModel):
    chat_id: str

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
async def tg_send(chat_id: str, text: str, parse_mode="Markdown"):
    """Send a Telegram message."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode
            })
    except Exception as e:
        print(f"TG send error: {e}")

async def tg_send_all(text: str):
    """Send to all users who have linked Telegram."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    users = conn.execute("SELECT tg_chat_id FROM users WHERE tg_chat_id IS NOT NULL").fetchall()
    conn.close()
    for row in users:
        await tg_send(row[0], text)

# ─── DEEPSEEK ─────────────────────────────────────────────────────────────────
async def call_deepseek(messages: list, system: str) -> str:
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role":"system","content":system}] + messages,
        "max_tokens": 600, "temperature": 0.8
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(DEEPSEEK_URL,
            headers={"Authorization":f"Bearer {DEEPSEEK_API_KEY}","Content-Type":"application/json"},
            json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

def build_coach_prompt(ctx: dict) -> str:
    today = datetime.now().strftime("%A, %d %B %Y %H:%M")
    tasks_str = ""
    if ctx:
        for t in ctx.get("tasks_today", []):
            prog = f"{t.get('done_qty',0)}/{t.get('target_qty',0)}" if t.get('target_qty',0) > 0 else t.get('status','?')
            tasks_str += f"\n  [{t.get('task_type','?').upper()}] {t.get('title','')} — {prog} ({t.get('priority','med')} priority)"
    return f"""You are Soumen's strict but caring AI discipline manager. Today: {today}

TODAY'S TASKS:{tasks_str or ' (none yet)'}
NOFAP STREAK: {ctx.get('nofap_days',0) if ctx else 0} days

YOUR PERSONALITY:
- Like a strict manager AND an encouraging mentor combined
- When behind on tasks: firm, direct, no excuses accepted
- When on track: genuine praise + push to go further
- Always give ONE practical tip to avoid distraction (no reels, no calls)
- You know he does Bhairav Upasana — reference this energy when motivating
- Max 4 sentences. Punch hard.

TASK CREATION: [ACTION:create_task:{{"title":"...","priority":"high/medium/low","detail":"...","task_type":"work/personal","target_qty":0}}]
TASK DONE: [ACTION:update_task:{{"id":"...","status":"done"}}]
"""

def build_manager_checkin_prompt(task: dict, done: int, total: int, elapsed_hrs: float, remaining_hrs: float) -> str:
    pace_needed = (total - done) / remaining_hrs if remaining_hrs > 0 else 999
    actual_pace = done / elapsed_hrs if elapsed_hrs > 0 else 0
    on_track    = actual_pace >= (total / (elapsed_hrs + remaining_hrs)) if (elapsed_hrs+remaining_hrs) > 0 else False
    pct         = round(done/total*100) if total > 0 else 0

    return f"""You are Soumen's STRICT AI manager doing a check-in on his task.

TASK: "{task['title']}"
TARGET: {total} units | DONE: {done} ({pct}%)
TIME ELAPSED: {elapsed_hrs:.1f}h | TIME REMAINING: {remaining_hrs:.1f}h
ACTUAL PACE: {actual_pace:.1f}/hr | PACE NEEDED TO FINISH: {pace_needed:.1f}/hr
STATUS: {'✅ ON TRACK' if on_track else '⚠️ BEHIND SCHEDULE'}

YOUR ROLE — strict manager + coach:
{"If BEHIND: Be stern. Call out the gap clearly. No sympathy. Then give ONE laser-focused tip to speed up. End with a direct command." if not on_track else "If ON TRACK: Acknowledge the pace. Give genuine praise. Then raise the bar — push to finish early. Keep energy high."}

Also add: block distractions — no phone calls, no reels, no scrolling during work block.
Format: 3-4 sharp sentences. Use numbers. Hit hard.
"""

# ─── SCHEDULER ────────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()

async def task_checkin_job():
    """Every hour: check all active work tasks, send AI manager message via Telegram."""
    now_dt  = datetime.now()
    h       = now_dt.hour
    if h < 7 or h > 22: return
    today   = now_dt.strftime("%Y-%m-%d")
    now_str = now_dt.strftime("%H:%M")

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # Get all pending/inprogress tasks for today that have a target_qty > 0
    tasks = conn.execute("""
        SELECT t.*, u.tg_chat_id FROM tasks t
        JOIN users u ON u.id = t.user_id
        WHERE t.date=? AND t.status IN ('pending','inprogress')
        AND t.target_qty > 0 AND u.tg_chat_id IS NOT NULL
    """, (today,)).fetchall()

    for task in tasks:
        task = dict(task)
        chat_id = task["tg_chat_id"]
        if not chat_id: continue

        # Calculate time elapsed and remaining
        start = task.get("start_time") or "09:00"
        end   = task.get("deadline")   or "18:00"
        try:
            sh, sm = map(int, start.split(":"))
            eh, em = map(int, end.split(":"))
            start_mins   = sh*60+sm
            end_mins     = eh*60+em
            current_mins = h*60+now_dt.minute
            elapsed_hrs  = max(0, (current_mins - start_mins)) / 60
            remaining_hrs= max(0, (end_mins - current_mins)) / 60
        except:
            elapsed_hrs  = 1
            remaining_hrs = 4

        done  = task.get("done_qty", 0)
        total = task.get("target_qty", 0)

        # Get AI manager response
        prompt = build_manager_checkin_prompt(task, done, total, elapsed_hrs, remaining_hrs)
        try:
            ai_msg = await call_deepseek(
                [{"role":"user","content":f"Check-in time. I've done {done} out of {total}."}],
                prompt
            )
        except:
            ai_msg = f"⚡ Check-in: {done}/{total} done. Keep pushing — no distractions!"

        # Save checkin
        conn.execute("""INSERT INTO checkins (task_id,user_id,done_qty,note,ai_response,ts)
            VALUES (?,?,?,?,?,?)""",
            (task["id"], task["user_id"], done, "", ai_msg, now_dt.isoformat()))
        conn.commit()

        # Send to Telegram
        pct = round(done/total*100) if total > 0 else 0
        msg = f"""⏰ *TASK CHECK-IN — {now_str}*

📋 *{task['title']}*
Progress: {done}/{total} ({pct}%) {"🟢" if pct>=50 else "🔴"}

🤖 *Your Manager says:*
{ai_msg}

_Reply with your current progress: just send a number like_ `done 35`"""
        await tg_send(chat_id, msg)

    # Also send summary for tasks without target_qty
    simple_tasks = conn.execute("""
        SELECT t.title, u.tg_chat_id FROM tasks t
        JOIN users u ON u.id = t.user_id
        WHERE t.date=? AND t.status='pending'
        AND t.target_qty=0 AND u.tg_chat_id IS NOT NULL
        LIMIT 5
    """, (today,)).fetchall()
    if simple_tasks:
        # Group by chat_id
        by_chat = {}
        for row in simple_tasks:
            cid = row[1]
            if cid not in by_chat: by_chat[cid] = []
            by_chat[cid].append(row[0])
        for cid, titles in by_chat.items():
            msg = f"⚡ *Pending tasks:*\n" + "\n".join([f"• {t}" for t in titles])
            msg += "\n\n_Open Discipline OS to update progress._"
            await tg_send(cid, msg)

    conn.close()

async def morning_job():
    await tg_send_all("""🌅 *Good morning, Soumen!*

🔱 Bhairav's blessings are with you.
Open Discipline OS and tell the AI your plan for today.

*Rules for today:*
• No reels before tasks are done
• No unnecessary calls during work blocks
• First deep work, then everything else

_What are you building today?_ 💪""")

async def evening_job():
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = sqlite3.connect(DB_PATH, check_same_thread=False)
    users = conn.execute("SELECT id,tg_chat_id FROM users WHERE tg_chat_id IS NOT NULL").fetchall()
    for row in users:
        uid, cid = row[0], row[1]
        done  = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND date=? AND status='done'",   (uid,today)).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND date=?", (uid,today)).fetchone()[0]
        pct   = round(done/total*100) if total else 0
        emoji = "🔥" if pct==100 else "💪" if pct>=70 else "⚠️" if pct>=40 else "😤"
        msg = f"""{emoji} *Evening Summary — {datetime.now().strftime('%d %b')}*

Tasks: *{done}/{total}* done ({pct}%)

{"🏆 Perfect execution today! Bhairav is pleased." if pct==100 else f"Still {total-done} pending. Finish before sleep." if total-done>0 else "Good work today."}

🌙 Wind down by 10:30 PM. Wake up at 4:30 AM.
Sleep = tomorrow's performance."""
        await tg_send(cid, msg)
    conn.close()

scheduler.add_job(task_checkin_job, "cron", minute=0)
scheduler.add_job(morning_job,      "cron", hour=6,  minute=0)
scheduler.add_job(evening_job,      "cron", hour=21, minute=0)

@app.on_event("startup")
async def startup():
    scheduler.start()
    print("🔥 Scheduler started")
    asyncio.create_task(tg_poll_loop())

@app.on_event("shutdown")
async def shutdown(): scheduler.shutdown()

# ─── TELEGRAM POLLING (to capture chat_id + handle replies) ──────────────────
tg_offset = 0

async def tg_poll_loop():
    """Long-poll Telegram for incoming messages — auto-register chat_id + handle progress updates."""
    global tg_offset
    print("📱 Telegram polling started")
    while True:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                r = await client.get(f"{TG_API}/getUpdates",
                    params={"offset": tg_offset, "timeout": 30, "allowed_updates": ["message"]})
            if r.status_code != 200:
                await asyncio.sleep(5)
                continue
            updates = r.json().get("result", [])
            for upd in updates:
                tg_offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text    = msg.get("text", "").strip()
                if not chat_id or not text: continue
                await handle_tg_message(chat_id, text)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"TG poll error: {e}")
            await asyncio.sleep(5)

async def handle_tg_message(chat_id: str, text: str):
    """Handle incoming Telegram messages."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)

    # /start — register chat_id
    if text.lower().startswith("/start"):
        # Try to find user with this chat_id already
        existing = conn.execute("SELECT id,username FROM users WHERE tg_chat_id=?", (chat_id,)).fetchone()
        if existing:
            await tg_send(chat_id, f"✅ Already linked to *{existing['username']}*!\n\nYour hourly check-ins are active. 🔥")
        else:
            await tg_send(chat_id, f"""🔱 *Discipline OS — Manager Bot*

Welcome! To link this Telegram to your account, open the app and go to *Config → Link Telegram*.

Your Chat ID is: `{chat_id}`

Or send: `/link YOUR_USERNAME YOUR_PASSWORD`""")
        conn.close()
        return

    # /link username password  (password may contain spaces/special chars)
    if text.lower().startswith("/link"):
        # Split only on first two spaces — rest is password
        rest = text[6:].strip()   # remove "/link "
        if " " in rest:
            uname, pwd = rest.split(" ", 1)
            uname = uname.strip()
            pwd   = pwd.strip()
            user  = conn.execute("SELECT id FROM users WHERE username=? AND password=?",
                (uname, hash_pw(pwd))).fetchone()
            if user:
                conn.execute("UPDATE users SET tg_chat_id=? WHERE id=?", (chat_id, user["id"]))
                conn.commit()
                await tg_send(chat_id, f"✅ *Linked successfully!*\n\nAccount: *{uname}*\n\nYou'll now receive:\n• 🌅 6 AM morning briefing\n• ⏰ Hourly task check-ins with AI manager\n• 🌙 9 PM evening summary\n\n🔥 Send /tasks to see today's tasks.")
            else:
                await tg_send(chat_id, "❌ Invalid username or password.\n\nMake sure you're using the exact username shown in the app.")
        else:
            await tg_send(chat_id, "⚠️ Format: `/link username password`")
        conn.close()
        return

    # "done 35" — progress update
    done_match = re.match(r'^(?:done|completed?|progress|finished?)\s+(\d+)', text.lower())
    if done_match:
        qty = int(done_match.group(1))
        # Find active task for this user today
        today = datetime.now().strftime("%Y-%m-%d")
        user  = conn.execute("SELECT id FROM users WHERE tg_chat_id=?", (chat_id,)).fetchone()
        if user:
            uid  = user["id"]
            task = conn.execute("""SELECT * FROM tasks WHERE user_id=? AND date=?
                AND status IN ('pending','inprogress') AND target_qty>0
                ORDER BY updated DESC LIMIT 1""", (uid, today)).fetchone()
            if task:
                task = dict(task)
                conn.execute("UPDATE tasks SET done_qty=?,status='inprogress',updated=? WHERE id=?",
                    (qty, datetime.utcnow().isoformat(), task["id"]))
                conn.commit()
                # Save checkin
                total = task["target_qty"]
                pct   = round(qty/total*100) if total else 0
                elapsed_hrs  = 1.0
                remaining_hrs= 3.0
                try:
                    now_h = datetime.now().hour
                    end_h = int((task.get("deadline") or "18:00").split(":")[0])
                    remaining_hrs = max(0.5, end_h - now_h)
                except: pass

                prompt = build_manager_checkin_prompt(task, qty, total, elapsed_hrs, remaining_hrs)
                try:
                    ai_reply = await call_deepseek(
                        [{"role":"user","content":f"I've done {qty} out of {total} so far."}],
                        prompt
                    )
                except:
                    ai_reply = f"{'Good pace!' if pct>=50 else 'Need to speed up!'} {qty}/{total} done ({pct}%)."

                conn.execute("INSERT INTO checkins (task_id,user_id,done_qty,note,ai_response,ts) VALUES (?,?,?,?,?,?)",
                    (task["id"], uid, qty, text, ai_reply, datetime.utcnow().isoformat()))
                conn.commit()

                msg = f"""✅ *Progress logged: {qty}/{total} ({pct}%)*

🤖 *Manager:*
{ai_reply}"""
                await tg_send(chat_id, msg)
            else:
                await tg_send(chat_id, "No active tracked task found for today. Open the app to add tasks.")
        conn.close()
        return

    # /tasks — list today's tasks
    if text.lower() in ["/tasks", "/today"]:
        today = datetime.now().strftime("%Y-%m-%d")
        user  = conn.execute("SELECT id FROM users WHERE tg_chat_id=?", (chat_id,)).fetchone()
        if user:
            tasks = conn.execute("SELECT * FROM tasks WHERE user_id=? AND date=? ORDER BY created",
                (user["id"], today)).fetchall()
            if tasks:
                lines = [f"📋 *Today's Tasks — {today}*\n"]
                for t in tasks:
                    t = dict(t)
                    icon = "✅" if t["status"]=="done" else "🔄" if t["status"]=="inprogress" else "⏳"
                    prog = f" ({t['done_qty']}/{t['target_qty']})" if t["target_qty"]>0 else ""
                    lines.append(f"{icon} {t['title']}{prog} [{t['priority'].upper()}]")
                await tg_send(chat_id, "\n".join(lines))
            else:
                await tg_send(chat_id, "No tasks for today. Open the app to plan your day.")
        conn.close()
        return

    # /help
    if text.lower() in ["/help", "/commands"]:
        await tg_send(chat_id, """📱 *Discipline OS — Commands*

`/start` — Welcome & setup
`/link username password` — Link to your account
`/tasks` — See today's tasks
`done 35` — Log progress (e.g. done 35 PRs)
`done 100%` — Mark as complete

You'll automatically receive:
• 🌅 6 AM morning briefing
• ⏰ Hourly task check-ins with AI manager
• 🌙 9 PM evening summary""")
        conn.close()
        return

    # Free-form chat → DeepSeek
    user = conn.execute("SELECT id FROM users WHERE tg_chat_id=?", (chat_id,)).fetchone()
    if user:
        today = datetime.now().strftime("%Y-%m-%d")
        tasks = conn.execute("SELECT * FROM tasks WHERE user_id=? AND date=?",
            (user["id"], today)).fetchall()
        ctx = {"tasks_today": [dict(t) for t in tasks], "nofap_days": 0}
        history = conn.execute(
            "SELECT role,content FROM ai_messages WHERE user_id=? ORDER BY ts DESC LIMIT 6",
            (user["id"],)).fetchall()
        messages = [{"role":r["role"],"content":r["content"]} for r in reversed(history)]
        messages.append({"role":"user","content":text})
        try:
            reply = await call_deepseek(messages, build_coach_prompt(ctx))
            clean = re.sub(r'\[ACTION:.*?\]','',reply).strip()
        except:
            clean = "⚠️ AI temporarily unavailable."
        now = datetime.utcnow().isoformat()
        conn.execute("INSERT INTO ai_messages (user_id,role,content,ts) VALUES (?,?,?,?)",
            (user["id"],"user",text,now))
        conn.execute("INSERT INTO ai_messages (user_id,role,content,ts) VALUES (?,?,?,?)",
            (user["id"],"assistant",clean,now))
        conn.commit()
        await tg_send(chat_id, f"🤖 {clean}")
    conn.close()

# ─── ROUTES ────────────────────────────────────────────────────────────────────
@app.get("/")
def root(): return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/sw.js")
def sw(): return FileResponse(os.path.join(FRONTEND_DIR, "sw.js"),
    media_type="application/javascript", headers={"Service-Worker-Allowed":"/"})

@app.post("/register", status_code=201)
def register(req: RegReq, db=Depends(get_db)):
    if len(req.username)<3: raise HTTPException(400,"Username too short")
    if len(req.password)<6: raise HTTPException(400,"Password too short")
    if db.execute("SELECT id FROM users WHERE username=?",(req.username,)).fetchone():
        raise HTTPException(409,"Username taken")
    db.execute("INSERT INTO users (username,password,created) VALUES (?,?,?)",
        (req.username, hash_pw(req.password), datetime.utcnow().isoformat()))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?",(req.username,)).fetchone()["id"]
    return {"token":make_token(uid,req.username),"username":req.username}

@app.post("/login")
def login(req: LoginReq, db=Depends(get_db)):
    row = db.execute("SELECT id,username FROM users WHERE username=? AND password=?",
        (req.username, hash_pw(req.password))).fetchone()
    if not row: raise HTTPException(401,"Invalid credentials")
    return {"token":make_token(row["id"],row["username"]),"username":row["username"]}

@app.get("/data")
def get_data(user=Depends(current_user), db=Depends(get_db)):
    row = db.execute("SELECT data FROM habit_data WHERE user_id=?",(user["id"],)).fetchone()
    return {"data":json.loads(row["data"]) if row else None}

@app.post("/save")
def save_data(req: SaveDataReq, user=Depends(current_user), db=Depends(get_db)):
    now = datetime.utcnow().isoformat()
    ds  = json.dumps(req.data)
    if db.execute("SELECT user_id FROM habit_data WHERE user_id=?",(user["id"],)).fetchone():
        db.execute("UPDATE habit_data SET data=?,updated=? WHERE user_id=?",(ds,now,user["id"]))
    else:
        db.execute("INSERT INTO habit_data (user_id,data,updated) VALUES (?,?,?)",(user["id"],ds,now))
    db.commit()
    return {"status":"saved","updated":now}

# Link Telegram from app
@app.post("/user/link-telegram")
def link_telegram(req: TgChatIdReq, user=Depends(current_user), db=Depends(get_db)):
    db.execute("UPDATE users SET tg_chat_id=? WHERE id=?", (req.chat_id, user["id"]))
    db.commit()
    return {"status":"linked"}

@app.get("/user/me")
def get_me(user=Depends(current_user), db=Depends(get_db)):
    row = db.execute("SELECT username,tg_chat_id FROM users WHERE id=?",(user["id"],)).fetchone()
    return {"username":row["username"],"tg_linked":bool(row["tg_chat_id"])}

# Tasks CRUD
@app.get("/tasks")
def get_tasks(date: Optional[str]=None, user=Depends(current_user), db=Depends(get_db)):
    d = date or datetime.now().strftime("%Y-%m-%d")
    rows = db.execute("SELECT * FROM tasks WHERE user_id=? AND date=? ORDER BY created",(user["id"],d)).fetchall()
    return {"tasks":[dict(r) for r in rows]}

@app.post("/tasks")
def create_task(req: TaskReq, user=Depends(current_user), db=Depends(get_db)):
    tid  = req.id or str(uuid.uuid4())[:8]
    now  = datetime.utcnow().isoformat()
    date = req.date or datetime.now().strftime("%Y-%m-%d")
    db.execute("""INSERT OR REPLACE INTO tasks
        (id,user_id,title,detail,task_type,status,priority,target_qty,done_qty,start_time,deadline,checkin_interval,date,created,updated)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid,user["id"],req.title,req.detail or "",req.task_type,req.status,req.priority,
         req.target_qty,req.done_qty,req.start_time,req.deadline,req.checkin_interval,date,now,now))
    db.commit()
    return {"status":"created","id":tid}

@app.patch("/tasks/{tid}")
def update_task_status(tid: str, req: dict, user=Depends(current_user), db=Depends(get_db)):
    # Accept any fields
    status   = req.get("status")
    done_qty = req.get("done_qty")
    now = datetime.utcnow().isoformat()
    if status:
        db.execute("UPDATE tasks SET status=?,updated=? WHERE id=? AND user_id=?",
            (status,now,tid,user["id"]))
    if done_qty is not None:
        db.execute("UPDATE tasks SET done_qty=?,updated=? WHERE id=? AND user_id=?",
            (done_qty,now,tid,user["id"]))
    db.commit()
    return {"status":"updated"}

@app.delete("/tasks/{tid}")
def delete_task(tid: str, user=Depends(current_user), db=Depends(get_db)):
    db.execute("DELETE FROM tasks WHERE id=? AND user_id=?",(tid,user["id"]))
    db.commit()
    return {"status":"deleted"}

@app.post("/tasks/{tid}/checkin")
async def task_checkin(tid: str, req: CheckinReq, user=Depends(current_user), db=Depends(get_db)):
    task = db.execute("SELECT * FROM tasks WHERE id=? AND user_id=?",(tid,user["id"])).fetchone()
    if not task: raise HTTPException(404,"Task not found")
    task = dict(task)

    # Update done_qty
    db.execute("UPDATE tasks SET done_qty=?,status='inprogress',updated=? WHERE id=?",
        (req.done_qty, datetime.utcnow().isoformat(), tid))
    db.commit()

    # Calculate time context
    total = task.get("target_qty",0)
    now_h = datetime.now().hour
    try:
        sh = int((task.get("start_time") or "09:00").split(":")[0])
        eh = int((task.get("deadline")   or "18:00").split(":")[0])
        elapsed_hrs   = max(0.1, now_h - sh)
        remaining_hrs = max(0.1, eh - now_h)
    except:
        elapsed_hrs, remaining_hrs = 1.0, 3.0

    prompt = build_manager_checkin_prompt(task, req.done_qty, total, elapsed_hrs, remaining_hrs)
    try:
        ai_reply = await call_deepseek(
            [{"role":"user","content":f"I've done {req.done_qty} out of {total}. {req.note}"}],
            prompt
        )
    except Exception as e:
        ai_reply = f"Keep pushing! {req.done_qty}/{total} done."

    # Save checkin record
    db.execute("INSERT INTO checkins (task_id,user_id,done_qty,note,ai_response,ts) VALUES (?,?,?,?,?,?)",
        (tid,user["id"],req.done_qty,req.note or "",ai_reply,datetime.utcnow().isoformat()))
    db.commit()

    # Send to Telegram
    tg_row = db.execute("SELECT tg_chat_id FROM users WHERE id=?",(user["id"],)).fetchone()
    if tg_row and tg_row[0]:
        pct = round(req.done_qty/total*100) if total else 0
        tg_msg = f"📊 *Progress: {req.done_qty}/{total} ({pct}%)*\n\n🤖 *Manager:*\n{ai_reply}"
        asyncio.create_task(tg_send(tg_row[0], tg_msg))

    return {"ai_response": ai_reply}

@app.get("/tasks/{tid}/checkins")
def get_checkins(tid: str, user=Depends(current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM checkins WHERE task_id=? AND user_id=? ORDER BY ts",
        (tid,user["id"])).fetchall()
    return {"checkins":[dict(r) for r in rows]}

# AI Chat
@app.post("/ai/chat")
async def ai_chat(req: ChatReq, user=Depends(current_user), db=Depends(get_db)):
    history = db.execute(
        "SELECT role,content FROM ai_messages WHERE user_id=? ORDER BY ts DESC LIMIT 12",(user["id"],)
    ).fetchall()
    messages = [{"role":r["role"],"content":r["content"]} for r in reversed(history)]
    messages.append({"role":"user","content":req.message})
    try:
        reply = await call_deepseek(messages, build_coach_prompt(req.context or {}))
    except Exception as e:
        raise HTTPException(500,f"AI error: {e}")
    now = datetime.utcnow().isoformat()
    db.execute("INSERT INTO ai_messages (user_id,role,content,ts) VALUES (?,?,?,?)",(user["id"],"user",req.message,now))
    db.execute("INSERT INTO ai_messages (user_id,role,content,ts) VALUES (?,?,?,?)",(user["id"],"assistant",reply,now))
    db.commit()
    actions = []
    for m in re.finditer(r'\[ACTION:(\w+):(\{.*?\})\]', reply):
        try: actions.append({"type":m.group(1),"data":json.loads(m.group(2))})
        except: pass
    return {"reply": re.sub(r'\[ACTION:.*?\]','',reply).strip(), "actions": actions}

@app.delete("/ai/history")
def clear_chat(user=Depends(current_user), db=Depends(get_db)):
    db.execute("DELETE FROM ai_messages WHERE user_id=?",(user["id"],))
    db.commit()
    return {"status":"cleared"}

if __name__ == "__main__":
    print(f"\n🔥 Discipline OS v3 → http://0.0.0.0:{PORT}\n")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
