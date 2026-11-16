# CivOps console (frontend)

React 19 + TypeScript + Vite. Three screens, all in `src/`:

| File | Screen |
|-|-|
| `LiveCall.tsx` | Live Call: transcript stream, tripwire banner, extracted facts with evidence quotes, rule-based recommendation, dispatcher review |
| `MonthlyAudit.tsx` | Monthly Audit: a synthetic month replayed through the rulebook and sorted into four review groups |
| `WhatIfSimulator.tsx` | What-If Simulator: baseline vs. proposed schedule over seeded Monte Carlo replications |

`api.ts` holds every call to the backend. Vite proxies `/api/*` and `/ws/*` to
`http://127.0.0.1:8000` (see `vite.config.ts`), so start the backend first.

```bash
npm ci          # exact versions from package-lock.json (Node 22, see .nvmrc)
npm run dev     # http://localhost:5173
npm run lint
npm run build   # type-check + production bundle
```

Setup for the whole project, the demo script and the limits are in the
[root README](../README.md).
