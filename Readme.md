# SideQuest 🗺️

A local activity-matching platform built during the Beyond Binary Hackathon (Team: Half Price, 4 members). SideQuest helps users discover and join casual social "quests" — activities like morning runs, study sessions, or meetups — based on shared social style and location.

**My role:** Lead programmer — built the backend architecture, API, and frontend.

## What it does

- **User accounts** — sign up with display name, password, and social preferences (energy level, social style, online/offline preference)
- **Create quests** — host an activity with a title, description, time, duration, and capacity
- **Join quests** — browse and sign up for activities posted by others
- **Recommendations** — a matching algorithm surfaces quests based on shared area and social style compatibility
- **Post-quest feedback** — rate completed quests on a "connectedness" scale (1-5 stars), feeding into future recommendation tuning

## Tech stack

- **Backend:** FastAPI + Pydantic for validation
- **Frontend:** Vanilla HTML/CSS/JS served directly from the FastAPI app (no separate frontend build)
- **Storage:** In-memory

## Running it locally

```bash
pip install fastapi uvicorn pydantic
uvicorn sidequest_app:app --reload
```

Then open `http://localhost:8000` in your browser.
