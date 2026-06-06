# Son of Anton — Frontend

Next.js 16 chat + voice UI for the Son of Anton recruiter-facing AI persona.

## Stack

- **Next.js 16** (App Router, Turbopack)
- **React 19**
- **Vapi** for live voice (WebRTC)
- Backend: FastAPI + LangGraph + ChromaDB + Redis (see `../backend/`)

## Local dev

```bash
npm install
npm run dev
```

Open <http://localhost:3000>. The app talks to `http://localhost:8000` by default —
override with `NEXT_PUBLIC_BACKEND_URL` in `.env.local`.

## Required env vars (`.env.local`)

| Key | Purpose |
|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | FastAPI base URL |
| `NEXT_PUBLIC_VAPI_PUBLIC_KEY` | Public Vapi key (browser-safe) |
| `NEXT_PUBLIC_VAPI_ASSISTANT_ID` | Anton's Vapi assistant ID |

Never put the private `VAPI_API_KEY`, `OPENAI_API_KEY`, or GCal credentials here —
those live on the backend.

## Build

```bash
npm run build
npm start
```

## Deploy

Vercel — root directory is `frontend/`, framework preset = Next.js. The
`vercel.json` in this folder pins the build command, framework, and deploy
regions (`bom1`, `sin1`) for low latency to India.
