# filename: sidequest_app.py
# Run: pip install fastapi uvicorn pydantic
# Start: uvicorn sidequest_app:app --reload

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# -----------------------------
# Models (API request/response)
# -----------------------------

app = FastAPI(title="SideQuest Prototype API", version="1.0")

class UserCreate(BaseModel):
    display_name: str = Field(..., example="Alex")
    password: str = Field(..., min_length=3)
    default_energy: str = Field(default="neutral", pattern="^(low|neutral|high)$")
    social_style: str = Field(default="either", pattern="^(quiet|talkative|either)$")
    mode: str = Field(default="either", pattern="^(online|offline|either)$")
    interests: List[str] = Field(default_factory=list)
    area: str = Field(default="NTU")

class UserLogin(BaseModel):
    display_name: str
    password: str

class QuestCreate(BaseModel):
    organizer_id: str
    title: str
    description: str
    area: str = "NTU"
    social_style: str = Field(default="either", pattern="^(quiet|talkative|either)$")
    mode: str = Field(default="either", pattern="^(online|offline|either)$")
    tags: List[str] = Field(default_factory=list)
    start_time_iso: str
    duration_mins: int = Field(ge=10, le=240)
    capacity: int = Field(ge=2, le=50)

class JoinQuest(BaseModel):
    user_id: str

class CompleteQuest(BaseModel):
    user_id: str
    connectedness_rating: int = Field(ge=1, le=5)

class QuestOut(BaseModel):
    quest_id: str
    organizer_name: str
    title: str
    description: str
    area: str
    social_style: str
    mode: str
    tags: List[str]
    start_time_iso: str
    duration_mins: int
    capacity: int
    participants: int
    score: Optional[float] = None
    has_joined: bool = False
    is_completed: bool = False

class DashboardOut(BaseModel):
    area: str
    active_users_7d: int
    quests_created_7d: int
    joins_7d: int

# -----------------------------
# In-memory storage
# -----------------------------

@dataclass
class User:
    user_id: str
    display_name: str
    password: str
    default_energy: str
    social_style: str
    mode: str
    interests: Set[str]
    area: str
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Quest:
    quest_id: str
    organizer_id: str
    title: str
    description: str
    area: str
    social_style: str
    mode: str
    tags: Set[str]
    start_time: datetime
    duration_mins: int
    capacity: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    participant_ids: Set[str] = field(default_factory=set)
    completions: Dict[str, int] = field(default_factory=dict) # user_id -> rating

USERS: Dict[str, User] = {}
QUESTS: Dict[str, Quest] = {}

# -----------------------------
# Logic Helpers
# -----------------------------

def parse_iso(dt_str: str) -> datetime:
    try:
        dt_str = dt_str.replace('Z', '+00:00')
        return datetime.fromisoformat(dt_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format.")

def capacity_available(q: Quest) -> bool:
    return len(q.participant_ids) < q.capacity

def get_organizer_name(uid: str) -> str:
    u = USERS.get(uid)
    return u.display_name if u else "Unknown"

# -----------------------------
# Endpoints
# -----------------------------

@app.post("/users/login")
def login_user(body: UserLogin):
    for u in USERS.values():
        if u.display_name.lower() == body.display_name.lower():
            if u.password == body.password:
                return {"user_id": u.user_id, "display_name": u.display_name, "area": u.area}
            else:
                raise HTTPException(status_code=401, detail="Incorrect password.")
    raise HTTPException(status_code=404, detail="User not found.")

@app.post("/users")
def create_user(body: UserCreate):
    for u in USERS.values():
        if u.display_name.lower() == body.display_name.lower():
             raise HTTPException(status_code=400, detail="Name already taken.")
             
    user_id = str(uuid4())
    u = User(
        user_id=user_id,
        display_name=body.display_name,
        password=body.password,
        default_energy=body.default_energy,
        social_style=body.social_style,
        mode=body.mode,
        interests=set(t.lower() for t in body.interests),
        area=body.area,
    )
    USERS[user_id] = u
    return {"user_id": user_id, "display_name": u.display_name}

@app.post("/quests")
def create_quest(body: QuestCreate):
    if body.organizer_id not in USERS:
        raise HTTPException(status_code=404, detail="Organizer (User) not found")
        
    start_time = parse_iso(body.start_time_iso)
    quest_id = str(uuid4())
    q = Quest(
        quest_id=quest_id,
        organizer_id=body.organizer_id,
        title=body.title,
        description=body.description,
        area=body.area,
        social_style=body.social_style,
        mode=body.mode,
        tags=set(t.lower() for t in body.tags),
        start_time=start_time,
        duration_mins=body.duration_mins,
        capacity=body.capacity,
    )
    QUESTS[quest_id] = q
    # Auto-join organizer? Optional, but let's say no for now to save capacity slots.
    return {"quest_id": quest_id}

@app.get("/users/{user_id}/recommendations", response_model=List[QuestOut])
def get_recommendations(user_id: str, k: int = 3):
    u = USERS.get(user_id)
    if not u: raise HTTPException(status_code=404, detail="User not found")
    
    candidates = []
    for q in QUESTS.values():
        if q.area != u.area: continue
        if user_id in q.participant_ids: continue # Skip if already joined
        if not capacity_available(q): continue
        
        score = 0.5 
        if u.social_style == q.social_style: score += 0.3
        candidates.append((q, score))
        
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    out = []
    for q, score in candidates[:k]:
        out.append(QuestOut(
            quest_id=q.quest_id,
            organizer_name=get_organizer_name(q.organizer_id),
            title=q.title,
            description=q.description,
            area=q.area,
            social_style=q.social_style,
            mode=q.mode,
            tags=sorted(list(q.tags)),
            start_time_iso=q.start_time.isoformat(),
            duration_mins=q.duration_mins,
            capacity=q.capacity,
            participants=len(q.participant_ids),
            score=round(score, 4),
            has_joined=False
        ))
    return out

@app.get("/users/{user_id}/quests", response_model=List[QuestOut])
def get_my_quests(user_id: str):
    # Returns quests the user has joined
    out = []
    for q in QUESTS.values():
        if user_id in q.participant_ids:
            out.append(QuestOut(
                quest_id=q.quest_id,
                organizer_name=get_organizer_name(q.organizer_id),
                title=q.title,
                description=q.description,
                area=q.area,
                social_style=q.social_style,
                mode=q.mode,
                tags=sorted(list(q.tags)),
                start_time_iso=q.start_time.isoformat(),
                duration_mins=q.duration_mins,
                capacity=q.capacity,
                participants=len(q.participant_ids),
                has_joined=True,
                is_completed=(user_id in q.completions)
            ))
    # Sort by start time
    out.sort(key=lambda x: x.start_time_iso)
    return out

@app.get("/quests", response_model=List[QuestOut])
def list_quests():
    out = []
    for q in QUESTS.values():
        out.append(QuestOut(
            quest_id=q.quest_id,
            organizer_name=get_organizer_name(q.organizer_id),
            title=q.title,
            description=q.description,
            area=q.area,
            social_style=q.social_style,
            mode=q.mode,
            tags=sorted(list(q.tags)),
            start_time_iso=q.start_time.isoformat(),
            duration_mins=q.duration_mins,
            capacity=q.capacity,
            participants=len(q.participant_ids),
            score=None,
        ))
    return out

@app.post("/quests/{quest_id}/join")
def join_quest(quest_id: str, body: JoinQuest):
    q = QUESTS.get(quest_id)
    if not q: raise HTTPException(status_code=404, detail="Quest not found")
    if body.user_id in q.participant_ids: return {"ok": True, "msg": "Already joined"}
    if not capacity_available(q): raise HTTPException(status_code=400, detail="Full")
    
    q.participant_ids.add(body.user_id)
    return {"ok": True}

@app.post("/quests/{quest_id}/complete")
def complete_quest(quest_id: str, body: CompleteQuest):
    q = QUESTS.get(quest_id)
    if not q: raise HTTPException(status_code=404, detail="Quest not found")
    q.completions[body.user_id] = body.connectedness_rating
    return {"ok": True}

# -----------------------------
# MODERN UI (HTML/JS/CSS)
# -----------------------------

APP_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SideQuest</title>
  <style>
    :root {
        --bg-color: #E0F7FA;
        --card-bg: #FFFFFF;
        --primary: #00BCD4;
        --sidebar-bg: #006064;
        --text-dark: #263238;
        --accent-pink: #FF4081;
        --accent-gold: #FFD700;
    }
    body { font-family: 'Segoe UI', sans-serif; background-color: var(--bg-color); margin: 0; color: var(--text-dark); }
    
    /* Utility */
    .hidden { display: none !important; }
    .btn { border: none; border-radius: 50px; padding: 12px 24px; font-weight: bold; cursor: pointer; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-top:10px;}
    .btn-pink { background: var(--accent-pink); }
    .btn-blue { background: var(--primary); }
    .btn-disabled { background: #bdc3c7; cursor: not-allowed; }
    
    /* Login Screen */
    #view-auth { height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #E0F7FA, #80DEEA); }
    .auth-card { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); width: 90%; max-width: 400px; text-align: center; }
    .auth-tabs { display: flex; margin-bottom: 20px; border-bottom: 2px solid #eee; }
    .tab { flex: 1; padding: 10px; cursor: pointer; color: #aaa; font-weight: bold; }
    .tab.active { color: var(--primary); border-bottom: 2px solid var(--primary); }
    .auth-input { width: 100%; padding: 12px; margin: 8px 0; border: 2px solid #ddd; border-radius: 10px; box-sizing: border-box; }
    
    /* App Layout */
    #view-app { display: flex; height: 100vh; }
    #sidebar { width: 250px; background: var(--sidebar-bg); padding: 20px; position: fixed; left: -290px; top: 0; bottom: 0; transition: left 0.3s; z-index: 1000; color: white; }
    #sidebar.open { left: 0; }
    .sidebar-btn { background: rgba(255,255,255,0.1); color: white; padding: 15px; margin-bottom: 10px; border-radius: 10px; cursor: pointer; display: block; width: 100%; border: none; text-align: left; }
    .sidebar-btn:hover { background: rgba(255,255,255,0.2); }
    
    main { flex: 1; padding: 20px; margin: 0 auto; max-width: 1200px; width: 100%; transition: margin-left 0.3s; }
    header { display: flex; align-items: center; margin-bottom: 30px; }
    #hamburger { font-size: 2rem; background: none; border: none; color: var(--sidebar-bg); cursor: pointer; margin-right: 20px; }
    
    /* Quest Grid Output */
    #output-area { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
    .quest-card { background: white; padding: 20px; border-radius: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border-left: 5px solid var(--accent-pink); display: flex; flex-direction: column; }
    .quest-card h3 { margin: 0 0 5px 0; color: var(--text-dark); }
    .quest-card .organizer { font-size: 0.85rem; color: #888; margin-bottom: 10px; }
    .quest-card .meta { background: #f0f4f8; padding: 5px 10px; border-radius: 8px; font-size: 0.8rem; color: #555; margin-bottom: 10px; }
    .quest-card .desc { font-size: 0.9rem; color: #444; flex-grow: 1; margin-bottom: 15px; }
    
    /* Rating Stars */
    .star-rating { display: flex; gap: 5px; justify-content: center; font-size: 1.5rem; cursor: pointer; }
    .star { color: #ccc; transition: color 0.2s; }
    .star:hover, .star.active { color: var(--accent-gold); }

  </style>
</head>
<body>

  <div id="view-auth">
    <div class="auth-card">
      <h1 style="color:var(--primary); margin:0;">SideQuest</h1>
      <p style="color:#aaa; margin-bottom:20px;">Your Local Adventure Awaits</p>
      
      <div class="auth-tabs">
        <div id="tab-signup" class="tab active" onclick="switchTab('signup')">Sign Up</div>
        <div id="tab-login" class="tab" onclick="switchTab('login')">Log In</div>
      </div>

      <div id="form-signup">
        <input id="su_name" class="auth-input" placeholder="Display Name (e.g. Alex)" />
        <input id="su_pass" type="password" class="auth-input" placeholder="Password" />
        <select id="su_energy" class="auth-input">
            <option value="neutral">Neutral Energy</option>
            <option value="high">High Energy</option>
            <option value="low">Low Energy</option>
        </select>
        <button class="btn btn-pink" style="width:100%" onclick="doSignup()">Create Account</button>
      </div>

      <div id="form-login" class="hidden">
        <input id="li_name" class="auth-input" placeholder="Your Display Name" />
        <input id="li_pass" type="password" class="auth-input" placeholder="Password" />
        <button class="btn btn-blue" style="width:100%" onclick="doLogin()">Enter World</button>
      </div>
    </div>
  </div>

  <div id="view-app" class="hidden">
    <aside id="sidebar">
        <h2 style="text-align:center; border-bottom:1px solid rgba(255,255,255,0.2); padding-bottom:10px;">Menu</h2>
        <button class="sidebar-btn" onclick="navTo('hub')">🏠 Home</button>
        <button class="sidebar-btn" onclick="navTo('myquests')">🎒 My Signed Up Quests</button>
        <button class="sidebar-btn" onclick="navTo('recs')">✨ Recommendations</button>
        <button class="sidebar-btn" onclick="navTo('list')">📜 All Quests</button>
        <button class="sidebar-btn" onclick="navTo('create')">➕ Create Quest</button>
        <button class="sidebar-btn" onclick="doLogout()">🚪 Logout</button>
    </aside>

    <main>
        <header>
            <button id="hamburger" onclick="toggleSidebar()">☰</button>
            <h2 id="page-title">Home</h2>
            <div style="margin-left:auto; font-weight:bold; color:var(--primary)">
                Hello, <span id="display-user-name">...</span>
            </div>
        </header>

        <div id="view-hub" class="hidden">
            <div style="display:flex; gap:30px; justify-content:center; flex-wrap:wrap; margin-top:50px;">
                <div style="background:white; width:280px; padding:30px; border-radius:30px; text-align:center; box-shadow:0 10px 20px rgba(0,0,0,0.1); cursor:pointer;" onclick="navTo('create')">
                    <div style="font-size:3rem; margin-bottom:10px;">⚔️</div>
                    <h3>Create Quest</h3>
                    <p style="color:#888;">Host an activity</p>
                </div>
                <div style="background:white; width:280px; padding:30px; border-radius:30px; text-align:center; box-shadow:0 10px 20px rgba(0,0,0,0.1); cursor:pointer;" onclick="navTo('recs')">
                    <div style="font-size:3rem; margin-bottom:10px;">🔍</div>
                    <h3>Join Quest</h3>
                    <p style="color:#888;">Find adventures</p>
                </div>
            </div>
        </div>

        <div id="view-create" class="hidden">
            <div style="background:white; padding:30px; border-radius:20px; max-width:600px; margin:auto;">
                <h2 style="color:var(--accent-pink); margin-top:0;">Host a Quest</h2>
                <input class="auth-input" id="q_title" placeholder="Title (e.g. Morning Run)" />
                <textarea class="auth-input" id="q_desc" rows="3" placeholder="Description"></textarea>
                <div style="display:flex; gap:15px;">
                    <div style="flex:1"><label>Duration (mins)</label><input class="auth-input" id="q_duration" type="number" value="60" /></div>
                    <div style="flex:1"><label>Capacity</label><input class="auth-input" id="q_capacity" type="number" value="5" /></div>
                </div>
                <label>Start Time</label>
                <input class="auth-input" id="q_start" type="datetime-local" />
                <button class="btn btn-pink" style="width:100%; margin-top:20px;" onclick="apiCreateQuest()">Publish Quest</button>
            </div>
        </div>

        <div id="view-output" class="hidden">
            <div id="output-area"></div>
        </div>
    </main>
  </div>

  <script>
    let currentUser = null; 

    // --- Auth ---
    function switchTab(mode) {
        if(mode === 'signup') {
            document.getElementById('tab-signup').classList.add('active');
            document.getElementById('tab-login').classList.remove('active');
            document.getElementById('form-signup').classList.remove('hidden');
            document.getElementById('form-login').classList.add('hidden');
        } else {
            document.getElementById('tab-signup').classList.remove('active');
            document.getElementById('tab-login').classList.add('active');
            document.getElementById('form-signup').classList.add('hidden');
            document.getElementById('form-login').classList.remove('hidden');
        }
    }

    async function doSignup() {
        const name = document.getElementById('su_name').value;
        const pass = document.getElementById('su_pass').value;
        if(!name || !pass) return alert("Name & Password required");
        
        try {
            const res = await fetch('/users', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    display_name: name,
                    password: pass,
                    default_energy: document.getElementById('su_energy').value,
                    area: "NTU"
                })
            });
            if(!res.ok) throw await res.json();
            const data = await res.json();
            alert("Account created! Please log in.");
            switchTab('login');
        } catch(e) { alert("Error: " + (e.detail || e)); }
    }

    async function doLogin() {
        const name = document.getElementById('li_name').value;
        const pass = document.getElementById('li_pass').value;
        
        try {
            const res = await fetch('/users/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ display_name: name, password: pass })
            });
            if(!res.ok) throw await res.json();
            const data = await res.json();
            enterApp(data);
        } catch(e) { alert("Login Failed: " + (e.detail || "Incorrect credentials")); }
    }

    function enterApp(userData) {
        currentUser = userData;
        document.getElementById('display-user-name').innerText = currentUser.display_name;
        document.getElementById('view-auth').classList.add('hidden');
        document.getElementById('view-app').classList.remove('hidden');
        navTo('hub');
        
        // Auto-fill datetime
        const now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset() + 60);
        document.getElementById('q_start').value = now.toISOString().slice(0,16);
    }

    function doLogout() {
        location.reload();
    }

    // --- Navigation ---
    function toggleSidebar() {
        document.getElementById('sidebar').classList.toggle('open');
    }

    function navTo(page) {
        document.getElementById('sidebar').classList.remove('open');
        document.getElementById('view-hub').classList.add('hidden');
        document.getElementById('view-create').classList.add('hidden');
        document.getElementById('view-output').classList.add('hidden');
        
        const titles = {
            'hub': 'Home', 'create': 'Create Quest', 'list': 'All Quests', 
            'recs': 'Recommendations', 'myquests': 'My Signed Up Quests'
        };
        document.getElementById('page-title').innerText = titles[page] || 'SideQuest';

        if(page === 'hub') document.getElementById('view-hub').classList.remove('hidden');
        else if(page === 'create') document.getElementById('view-create').classList.remove('hidden');
        else {
            document.getElementById('view-output').classList.remove('hidden');
            if(page === 'list') fetchList();
            else if(page === 'recs') fetchRecs();
            else if(page === 'myquests') fetchMyQuests();
        }
    }

    // --- Logic ---
    async function apiCreateQuest() {
        const startVal = document.getElementById('q_start').value;
        const payload = {
            organizer_id: currentUser.user_id,
            title: document.getElementById('q_title').value || "New Quest",
            description: document.getElementById('q_desc').value || "Join us!",
            area: currentUser.area || "NTU",
            start_time_iso: new Date(startVal).toISOString(),
            duration_mins: parseInt(document.getElementById('q_duration').value),
            capacity: parseInt(document.getElementById('q_capacity').value)
        };
        try {
            const res = await fetch('/quests', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
            if(!res.ok) throw await res.json();
            alert("Quest Created!");
            navTo('myquests');
        } catch(e) { alert("Error: " + e.detail); }
    }

    async function fetchList() {
        const res = await fetch('/quests');
        renderQuests(await res.json());
    }
    async function fetchRecs() {
        const res = await fetch(`/users/${currentUser.user_id}/recommendations?k=10`);
        renderQuests(await res.json());
    }
    async function fetchMyQuests() {
        const res = await fetch(`/users/${currentUser.user_id}/quests`);
        renderQuests(await res.json(), true);
    }

    async function joinQuest(qid) {
        try {
            const res = await fetch(`/quests/${qid}/join`, {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ user_id: currentUser.user_id })
            });
            if(!res.ok) throw await res.json();
            alert("Joined!");
            navTo('myquests');
        } catch(e) { alert(e.detail); }
    }

    async function submitRating(qid, stars) {
        try {
            const res = await fetch(`/quests/${qid}/complete`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ user_id: currentUser.user_id, connectedness_rating: stars })
            });
            if(!res.ok) throw await res.json();
            alert("Rated " + stars + " stars!");
            fetchMyQuests(); // refresh UI
        } catch(e) { alert(e.detail); }
    }

    function renderQuests(quests, isMyPage=false) {
        const area = document.getElementById('output-area');
        area.innerHTML = "";
        if(!quests || quests.length === 0) {
            area.innerHTML = "<p style='text-align:center; width:100%; color:#888'>No quests found.</p>"; return;
        }

        const now = new Date();

        quests.forEach(q => {
            const startTime = new Date(q.start_time_iso);
            const endTime = new Date(startTime.getTime() + q.duration_mins * 60000);
            const hasEnded = now > endTime;
            const dateStr = startTime.toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
            
            let actionBtn = "";
            
            if (isMyPage) {
                if (q.is_completed) {
                    actionBtn = `<div style="text-align:center; color:var(--accent-gold); font-weight:bold;">★ Rated</div>`;
                } else if (hasEnded) {
                    // Feedback UI
                    actionBtn = `
                        <div style="text-align:center;">
                            <small>Quest Ended. Rate it:</small>
                            <div class="star-rating">
                                <span class="star" onclick="submitRating('${q.quest_id}', 1)">★</span>
                                <span class="star" onclick="submitRating('${q.quest_id}', 2)">★</span>
                                <span class="star" onclick="submitRating('${q.quest_id}', 3)">★</span>
                                <span class="star" onclick="submitRating('${q.quest_id}', 4)">★</span>
                                <span class="star" onclick="submitRating('${q.quest_id}', 5)">★</span>
                            </div>
                        </div>
                    `;
                } else {
                    actionBtn = `<button class="btn btn-disabled" style="width:100%">Joined (Upcoming)</button>`;
                }
            } else {
                actionBtn = `<button class="btn btn-blue" style="width:100%" onclick="joinQuest('${q.quest_id}')">Join Quest</button>`;
            }

            const card = document.createElement('div');
            card.className = 'quest-card';
            card.innerHTML = `
                <h3>${q.title}</h3>
                <div class="organizer">By ${q.organizer_name}</div>
                <div class="meta">📅 ${dateStr} • ⏳ ${q.duration_mins}m • 👥 ${q.participants}/${q.capacity}</div>
                <div class="desc">${q.description}</div>
                ${actionBtn}
            `;
            area.appendChild(card);
        });
    }
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def root():
    return APP_HTML

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("sidequest_app:app", host="0.0.0.0", port=8000, reload=True)
