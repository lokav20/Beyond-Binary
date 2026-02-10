# filename: sidequest_app.py
# Run: pip install fastapi uvicorn pydantic
# Start: uvicorn sidequest_app:app --reload

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# -----------------------------
# Models (API request/response)
# -----------------------------

class UserCreate(BaseModel):
    display_name: str
    # "low" | "neutral" | "high"
    default_energy: str = Field(default="neutral", pattern="^(low|neutral|high)$")
    # "quiet" | "talkative" | "either"
    social_style: str = Field(default="either", pattern="^(quiet|talkative|either)$")
    # "online" | "offline" | "either"
    mode: str = Field(default="either", pattern="^(online|offline|either)$")
    interests: List[str] = Field(default_factory=list)
    # simple location bucket for prototype (e.g. "NTU", "Jurong", "Tampines")
    area: str = "NTU"


class UserCheckIn(BaseModel):
    energy: str = Field(pattern="^(low|neutral|high)$")


class QuestCreate(BaseModel):
    title: str
    description: str
    area: str = "NTU"
    # "quiet" | "talkative" | "either"
    social_style: str = Field(default="either", pattern="^(quiet|talkative|either)$")
    # "online" | "offline" | "either"
    mode: str = Field(default="either", pattern="^(online|offline|either)$")
    tags: List[str] = Field(default_factory=list)
    start_time_iso: str  # ISO string like "2026-02-11T19:00:00"
    duration_mins: int = Field(ge=10, le=240)
    capacity: int = Field(ge=2, le=50)


class JoinQuest(BaseModel):
    user_id: str


class CompleteQuest(BaseModel):
    user_id: str
    connectedness_rating: int = Field(ge=1, le=5)


class QuestOut(BaseModel):
    quest_id: str
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


class DashboardOut(BaseModel):
    area: str
    # engagement
    active_users_7d: int
    quests_created_7d: int
    joins_7d: int
    completions_7d: int
    repeat_participation_rate_30d: float
    avg_connectedness_7d: Optional[float]
    time_to_first_connection_hours_avg: Optional[float]
    # what works
    top_tags_7d: List[Tuple[str, int]]


# -----------------------------
# In-memory storage (prototype)
# -----------------------------

@dataclass
class User:
    user_id: str
    display_name: str
    default_energy: str
    social_style: str
    mode: str
    interests: Set[str]
    area: str
    last_checkin_energy: str = "neutral"
    last_checkin_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    first_join_at: Optional[datetime] = None
    last_join_at: Optional[datetime] = None


@dataclass
class Quest:
    quest_id: str
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
    completions: Dict[str, int] = field(default_factory=dict)  # user_id -> rating (1-5)


USERS: Dict[str, User] = {}
QUESTS: Dict[str, Quest] = {}

# For simple analytics
EVENT_LOG: List[Tuple[str, datetime, Dict]] = []  # (event_type, timestamp, payload)


def log_event(event_type: str, payload: Dict):
    EVENT_LOG.append((event_type, datetime.utcnow(), payload))


# -----------------------------
# Matching / scoring logic
# -----------------------------

def parse_iso(dt_str: str) -> datetime:
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO, e.g. 2026-02-11T19:00:00")


def within_next_hours(q: Quest, hours: int = 48) -> bool:
    now = datetime.utcnow()
    return now <= q.start_time <= now + timedelta(hours=hours)


def preference_match(user_val: str, quest_val: str) -> float:
    """
    Returns a score contribution [0..1] for matching fields like mode/social_style.
    """
    if user_val == "either" or quest_val == "either":
        return 0.7
    return 1.0 if user_val == quest_val else 0.0


def energy_fit(user_energy: str, quest: Quest) -> float:
    """
    Low energy users should prefer smaller/quieter/shorter quests.
    High energy users can handle talkative/longer/groupy.
    """
    base = 0.5
    if user_energy == "low":
        # reward short + quiet
        base += 0.2 if quest.duration_mins <= 45 else -0.1
        base += 0.2 if quest.social_style in ("quiet", "either") else -0.1
    elif user_energy == "high":
        # reward talkative + longer
        base += 0.2 if quest.duration_mins >= 60 else 0.0
        base += 0.2 if quest.social_style in ("talkative", "either") else 0.0
    else:
        # neutral: prefer balanced
        base += 0.1 if 30 <= quest.duration_mins <= 90 else 0.0
    return max(0.0, min(1.0, base))


def tag_overlap(user_tags: Set[str], quest_tags: Set[str]) -> float:
    if not user_tags or not quest_tags:
        return 0.2  # small default value
    overlap = len(user_tags.intersection(quest_tags))
    return min(1.0, 0.2 + 0.2 * overlap)


def capacity_available(q: Quest) -> bool:
    return len(q.participant_ids) < q.capacity


def recommend_quests_for_user(user: User, top_k: int = 3) -> List[Tuple[Quest, float]]:
    candidates: List[Tuple[Quest, float]] = []

    for q in QUESTS.values():
        # basic filters
        if q.area != user.area:
            continue
        if not within_next_hours(q, 72):
            continue
        if not capacity_available(q):
            continue
        if user.user_id in q.participant_ids:
            continue

        # scoring
        score = 0.0
        score += 0.35 * preference_match(user.mode, q.mode)
        score += 0.25 * preference_match(user.social_style, q.social_style)
        score += 0.25 * energy_fit(user.last_checkin_energy, q)
        score += 0.15 * tag_overlap(user.interests, q.tags)

        candidates.append((q, score))

    # sort by score desc
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:top_k]


# -----------------------------
# Analytics helpers
# -----------------------------

def since(ts: datetime, days: int) -> List[Tuple[str, datetime, Dict]]:
    cutoff = ts - timedelta(days=days)
    return [e for e in EVENT_LOG if e[1] >= cutoff]


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def dashboard(area: str) -> DashboardOut:
    now = datetime.utcnow()
    events_7d = [e for e in since(now, 7) if e[2].get("area") == area]
    events_30d = [e for e in since(now, 30) if e[2].get("area") == area]

    # active users = users who checked in or joined/completed within 7d
    active_users: Set[str] = set()
    for et, _, payload in events_7d:
        uid = payload.get("user_id")
        if uid:
            active_users.add(uid)

    quests_created_7d = sum(1 for et, _, _ in events_7d if et == "quest_created")
    joins_7d = sum(1 for et, _, _ in events_7d if et == "quest_joined")
    completions_7d = sum(1 for et, _, _ in events_7d if et == "quest_completed")

    # repeat participation rate: users with >=2 joins in last 30d / users with >=1 join in last 30d
    join_counts: Dict[str, int] = {}
    for et, _, payload in events_30d:
        if et == "quest_joined":
            uid = payload.get("user_id")
            if uid:
                join_counts[uid] = join_counts.get(uid, 0) + 1

    users_with_join = sum(1 for v in join_counts.values() if v >= 1)
    users_with_repeat = sum(1 for v in join_counts.values() if v >= 2)
    repeat_rate = safe_div(users_with_repeat, users_with_join)

    # avg connectedness rating last 7d
    ratings = [payload["rating"] for et, _, payload in events_7d if et == "quest_completed"]
    avg_connectedness = (sum(ratings) / len(ratings)) if ratings else None

    # time to first connection (join) in hours avg: from user created_at -> first_join_at
    ttf_list: List[float] = []
    for u in USERS.values():
        if u.area != area:
            continue
        if u.first_join_at is not None:
            ttf_list.append((u.first_join_at - u.created_at).total_seconds() / 3600.0)
    ttf_avg = (sum(ttf_list) / len(ttf_list)) if ttf_list else None

    # top tags 7d by joins
    tag_counts: Dict[str, int] = {}
    for et, _, payload in events_7d:
        if et == "quest_joined":
            qid = payload.get("quest_id")
            if qid and qid in QUESTS:
                for t in QUESTS[qid].tags:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return DashboardOut(
        area=area,
        active_users_7d=len(active_users),
        quests_created_7d=quests_created_7d,
        joins_7d=joins_7d,
        completions_7d=completions_7d,
        repeat_participation_rate_30d=round(repeat_rate, 4),
        avg_connectedness_7d=(round(avg_connectedness, 2) if avg_connectedness is not None else None),
        time_to_first_connection_hours_avg=(round(ttf_avg, 2) if ttf_avg is not None else None),
        top_tags_7d=top_tags,
    )


# -----------------------------
# FastAPI app + endpoints
# -----------------------------

app = FastAPI(title="SideQuest Prototype API", version="1.0")


@app.post("/users")
def create_user(body: UserCreate):
    user_id = str(uuid4())
    u = User(
        user_id=user_id,
        display_name=body.display_name,
        default_energy=body.default_energy,
        social_style=body.social_style,
        mode=body.mode,
        interests=set(t.lower() for t in body.interests),
        area=body.area,
        last_checkin_energy=body.default_energy,
    )
    USERS[user_id] = u
    log_event("user_created", {"user_id": user_id, "area": u.area})
    return {"user_id": user_id}


@app.post("/users/{user_id}/checkin")
def user_checkin(user_id: str, body: UserCheckIn):
    u = USERS.get(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.last_checkin_energy = body.energy
    u.last_checkin_at = datetime.utcnow()
    log_event("user_checkin", {"user_id": user_id, "area": u.area, "energy": body.energy})
    return {"ok": True}


@app.post("/quests")
def create_quest(body: QuestCreate):
    start_time = parse_iso(body.start_time_iso)
    quest_id = str(uuid4())
    q = Quest(
        quest_id=quest_id,
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
    log_event("quest_created", {"quest_id": quest_id, "area": q.area})
    return {"quest_id": quest_id}


@app.get("/users/{user_id}/recommendations", response_model=List[QuestOut])
def get_recommendations(user_id: str, k: int = 3):
    u = USERS.get(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    recs = recommend_quests_for_user(u, top_k=max(1, min(10, k)))
    out: List[QuestOut] = []
    for q, score in recs:
        out.append(
            QuestOut(
                quest_id=q.quest_id,
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
            )
        )
    log_event("recommendations_viewed", {"user_id": user_id, "area": u.area, "k": k})
    return out


@app.post("/quests/{quest_id}/join")
def join_quest(quest_id: str, body: JoinQuest):
    q = QUESTS.get(quest_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quest not found")

    u = USERS.get(body.user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if u.area != q.area:
        raise HTTPException(status_code=400, detail="User area does not match quest area")
    if not capacity_available(q):
        raise HTTPException(status_code=400, detail="Quest is full")
    if body.user_id in q.participant_ids:
        return {"ok": True, "message": "Already joined"}

    q.participant_ids.add(body.user_id)

    # first join time tracking
    now = datetime.utcnow()
    if u.first_join_at is None:
        u.first_join_at = now
    u.last_join_at = now

    log_event("quest_joined", {"user_id": body.user_id, "quest_id": quest_id, "area": q.area})
    return {"ok": True}


@app.post("/quests/{quest_id}/complete")
def complete_quest(quest_id: str, body: CompleteQuest):
    q = QUESTS.get(quest_id)
    if not q:
        raise HTTPException(status_code=404, detail="Quest not found")

    if body.user_id not in q.participant_ids:
        raise HTTPException(status_code=400, detail="User has not joined this quest")

    q.completions[body.user_id] = body.connectedness_rating
    log_event(
        "quest_completed",
        {"user_id": body.user_id, "quest_id": quest_id, "area": q.area, "rating": body.connectedness_rating},
    )
    return {"ok": True}


@app.get("/dashboard/{area}", response_model=DashboardOut)
def get_dashboard(area: str):
    # area-level aggregated stats
    return dashboard(area=area)


@app.get("/quests", response_model=List[QuestOut])
def list_quests(area: Optional[str] = None):
    out: List[QuestOut] = []
    for q in QUESTS.values():
        if area and q.area != area:
            continue
        out.append(
            QuestOut(
                quest_id=q.quest_id,
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
            )
        )
    # upcoming first
    out.sort(key=lambda x: x.start_time_iso)
    return out

