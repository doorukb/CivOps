# CivOps

A hackathon prototype (HackUMass XIV) that turns an illustrative copy of Amherst's CRESS dispatch rules into software, used at three points: during a call (Live Call Copilot), after a month of calls (Monthly Audit), and before a staffing decision (What-If Simulator).

> **Synthetic demonstration only.** This is not a 911 system or an official Amherst/CRESS tool, and it does not make dispatch decisions. The rulebook is illustrative and all data is synthetic. A human reviews every recommendation.

For the current state, known gaps and next steps, see [docs/BASELINE.md](docs/BASELINE.md).

## Run locally (Windows PowerShell)

**Backend** (from `backend/`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in ANTHROPIC_API_KEY and DEEPGRAM_API_KEY
python -m uvicorn app.main:app --reload
```

API docs: http://127.0.0.1:8000/docs. Tests (no paid API calls): `python -m pytest tests/ -q`.

**Frontend** (from `frontend/`):

```powershell
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies `/api/*` and `/ws/*` to the backend on port 8000. Production build check: `npm run build`.

**Start Call** records from the microphone of the machine that runs the backend, not the browser's microphone. Keep the backend bound to localhost.
