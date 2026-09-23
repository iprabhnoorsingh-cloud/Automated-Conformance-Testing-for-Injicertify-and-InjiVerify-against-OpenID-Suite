# Frontend — MOSIP Conformance Center

Minimal Next.js dashboard shell for Milestone 1 (project foundation). No
conformance execution UI exists yet — navigation items are placeholders.

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local
```

## Run

```bash
npm run dev
```

## Build

```bash
npm run build
```

## Configuration

- `NEXT_PUBLIC_API_URL` — base URL of the backend API (default
  `http://localhost:8000`). The dashboard uses this to check backend health.
