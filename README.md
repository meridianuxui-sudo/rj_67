# MERADION

**Where student voices come alive.** MERADION is a private, API-first educational audio platform for families, educators, and students. It intentionally uses authenticated playback for recordings and authenticated WebRTC signaling for live audio—never public radio streams.

## What is implemented

- FastAPI REST API with JWT access/refresh credentials, Argon2 password hashing, role dependencies, OpenAPI docs, CORS, and secure error responses.
- SQLAlchemy 2 models for users/profiles, approved parent–student links, classes, enrollments, podcasts, live sessions, notifications, and devices.
- Server-side visibility enforcement for `PRIVATE`, `PARENTS`, `CLASS`, and `SCHOOL` content; private audio only streams after authenticated authorization.
- Student podcast drafting/upload/publishing flow (MP3/M4A/WAV, private filesystem development adapter) and parent-wide published podcast discovery.
- Private WebRTC signaling websocket which authenticates its JWT and validates live-session authorization before accepting signaling messages.
- Live session creation emits personalized in-app notifications to approved parents.
- A responsive Next.js interface featuring landing, auth, parent, teacher, student, and administrator route surfaces, waveform motion, dashboard/library views, and secure API client.

## Run locally

```bash
docker compose up -d postgres
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. API documentation is available at http://localhost:8000/docs.

## Bootstrap and test users

Register the initial administrator with `POST /api/auth/register` and `role: ADMIN`; then use its access token with `POST /api/admin/parent-students` to approve guardian links. Register parent, teacher, and student accounts with the same endpoint or UI. No credentials are committed to this repository.

## Environment

See [`backend/.env.example`](backend/.env.example). Configure PostgreSQL, a unique `JWT_SECRET`, CORS origin, Supabase-compatible storage credentials for production, and STUN/TURN infrastructure. The development storage adapter writes protected files to `backend/private_uploads`; replace it with Supabase in deployment.

## Verification

```bash
cd backend && pytest
cd frontend && npm run build
```

## Deployment notes

WebRTC needs a TURN service for restrictive networks. This implementation provides authorized signaling and ICE server configuration; a production SFU/TURN layer is required to fan out large live audiences. Password recovery and external push providers need an email/provider integration before enabling those flows.
