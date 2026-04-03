# AP Insurance Partners App

Agency portal and leaderboard for AP Insurance Partners — built with FastAPI (backend) and React + TypeScript + Tailwind CSS (frontend).

## Features
- Agent leaderboard (daily, weekly, monthly)
- Admin dashboard with commission stats
- Deal submission form (syncs with GHL)
- Commission CSV upload & tracking
- Agent management (auto-create from GHL)
- Submission agents management
- Hourly report (CallTools integration)

## Setup

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Environment Variables (Backend)
- `DATABASE_URL` — PostgreSQL connection string
- `GHL_API_KEY` — GHL Private Integration Token
- `GHL_LOCATION_ID` — GHL Location ID
- `JWT_SECRET` — Stable secret for JWT signing
- `SUPER_ADMIN_EMAIL` — Admin login email
- `SUPER_ADMIN_PASSWORD` — Admin login password

### Environment Variables (Frontend)
- `VITE_API_URL` — Backend API URL
