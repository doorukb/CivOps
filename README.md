# CivOps

A hackathon prototype (HackUMass XIV) that turns an illustrative copy of Amherst's CRESS dispatch rules into software, used at three points: during a call (Live Call Copilot), after a month of calls (Monthly Audit), and before a staffing decision (What-If Simulator).

> **Synthetic demonstration only.** This is not a 911 system or an official Amherst/CRESS tool, and it does not make dispatch decisions. The rulebook is illustrative and all data is synthetic. A human reviews every recommendation.

For the current state, known gaps and next steps, see [docs/BASELINE.md](docs/BASELINE.md).

## Run locally

Needs Python 3.13 and Node.js. Run the backend and the frontend in two terminals.

### Backend (from `backend/`)

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in ANTHROPIC_API_KEY and DEEPGRAM_API_KEY
python -m uvicorn app.main:app --reload
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then fill in ANTHROPIC_API_KEY and DEEPGRAM_API_KEY
python -m uvicorn app.main:app --reload
```

On Linux, **Start Call** also needs PortAudio (`sudo apt install libportaudio2` on Debian/Ubuntu). On macOS, allow microphone access for your terminal app when asked.

API docs: http://127.0.0.1:8000/docs. Tests (no paid API calls): `python -m pytest tests/ -q`.

### Frontend (from `frontend/`)

Same on every OS:

```bash
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api/*` and `/ws/*` to the backend on port 8000. Production build check: `npm run build`.

**Start Call** records from the microphone of the machine that runs the backend, not the browser's microphone. Keep the backend bound to localhost.

### Demo day

Start the backend without `--reload` and bound to localhost:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`--reload` restarts the server whenever a file changes, and a restart in the middle of the demo drops the transcript WebSocket.

## Scripted calls (no microphone needed)

A scripted call is the backup if the microphone, Deepgram or the Wi-Fi fails. The backend replays a fictional transcript through the same WebSocket path as a live call, so the tripwire banner, extraction and decision card behave the same way.

In **Live Call**, while no call is running and the transcript connection is up, a button appears for each script:

| Script ID | What it shows |
|-|-|
| `routine_wellbeing` | A wellbeing check with every safety answer clear → CRESS (or CRESS follow-up outside duty hours) |
| `hidden_knife` | A noise dispute that turns into a knife sighting → the tripwire sends it to human review |
| `incomplete_screening` | An argument with unknown safety details → `SCREEN-INCOMPLETE` |

Deepgram isn't used. When the script ends, the page runs Claude extraction automatically, which needs `ANTHROPIC_API_KEY`. Without the key, fill in the fields by hand and click Evaluate. The tripwire and the rules work without any key.

You can also start a script from a terminal while the page is open (`curl.exe` on Windows):

```bash
curl -X POST "http://127.0.0.1:8000/scenarios/hidden_knife/play?speed=2"
```

`GET /scenarios` lists the scripts. `speed` speeds up playback (1 is real time, up to 100). Only one call or script runs at a time. A second request gets `{"status": "already_running"}` and nothing new starts.

## Limits

- **The simulator shows a ceiling.** It sends every eligible on-duty call to CRESS, so its numbers show the most CRESS could take, not what dispatch sends today. The arrivals are synthetic, with weights fitted to the brief's coverage table rather than copied from LEAP's data.
- **"Caller asked for CRESS" is display-only.** Claude extracts `caller_requests_cress` and the Live Call view shows it, but no rule uses it.
- **Evidence quotes prove existence, not meaning.** The backend keeps a safety answer only if Claude's quote appears in the transcript, ignoring speaker labels, case and spacing. That proves the words were said, not that they support the answer. A real quote can still back a wrong one, for example a negation read the wrong way. Check the quote before you trust the field.
- **The tripwire is a keyword list.** It ignores negation, so "he does not have a gun" still raises a flag. A flag only asks for human review.
- **Localhost only, no login.** The backend refuses requests from browser pages that aren't on `localhost` / `127.0.0.1`, so another website can't start the microphone or read the transcript. Any program on the same machine can still call it, so never bind it to `0.0.0.0` or expose it with ngrok as it is.
- **Nothing is stored.** Calls, decisions and edited fields live in memory and are lost when the backend stops.
