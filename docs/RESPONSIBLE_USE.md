# Responsible use

## What this is

A student prototype that demonstrates one idea: a language model can help a
dispatcher by pulling facts out of a transcript, while plain, inspectable rules
make the recommendation and a person makes the decision.

## What this is not

- **Not a 911 system.** It must not be used to handle, triage or route a real
  call. If someone is in danger, call 911.
- **Not an official tool.** It is not affiliated with, endorsed by or reviewed
  by the Town of Amherst, CRESS, any dispatch centre, or the Law Enforcement
  Action Partnership. Names of public services appear only to describe the
  problem the project is about.
- **Not a description of real policy.** The rulebook is an illustration
  written for this project. Its schedule, eligible call types and screening
  questions are assumptions, and every rule's `source` says so.
- **Not validated.** The evaluations use small, hand-written, synthetic sets.
  Nothing here supports a claim about performance on real calls, and the
  simulator's outputs are not forecasts.

## Do not put real people into it

- Use the scripted calls, or speak fictional scenarios.
- Do not paste or upload real call recordings, transcripts, names, addresses
  or case details.
- The "audit your own file" upload is for synthetic or properly de-identified
  data. The file is replayed in memory and not stored.

## Recording and consent

**Start Call** records the microphone of the computer that runs the backend.
The console shows a notice and will not start until you tick a consent box.

- Only record people who know they are being recorded and have agreed.
  Massachusetts is among the states whose wiretap law generally requires the
  consent of everyone in a conversation (M.G.L. c. 272, § 99). This is not
  legal advice; the rule where you are may differ.
- The scripted calls open with a spoken recording notice for the same reason.

## Where data goes

| Data | Where it goes | When |
|-|-|-|
| Microphone audio | Deepgram, for speech-to-text | Only while a live call is running, and only if `DEEPGRAM_API_KEY` is set |
| Transcript text | Anthropic (Claude), for fact extraction | Only when extraction runs, and only if `ANTHROPIC_API_KEY` is set |
| Transcript text | Your browser, over a localhost WebSocket | While a call is running |
| Decisions and reviews | A local SQLite file, `backend/data/civops.db` | When a dispatcher confirms or overrides |
| Transcript text and evidence quotes | The same SQLite file | **Scripted calls only**, unless `CIVOPS_STORE_LIVE_TRANSCRIPTS=1` |

Nothing else leaves the machine. The server logs counts and error types, never
what was said. Both providers process what they receive under their own terms;
read them before sending anything you care about.

The call log is a plain file. Delete `backend/data/` (or run `make clean`) to
remove it.

## Keep it on localhost

The backend has no login. It refuses browser requests from other sites and
requests addressed to other host names, which stops a web page you happen to
visit from turning on your microphone or reading the transcript. It does not
stop another program on the same machine. Do not bind it to `0.0.0.0`, and do
not expose it through a tunnel or a reverse proxy.

## Words to avoid when describing it

This project supports a dispatcher's decision. It does not dispatch. Please do
not describe it as automated or AI dispatch, as a fix for any real service, or
as something a town uses.
