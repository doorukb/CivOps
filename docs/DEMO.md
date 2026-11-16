# Demo script (about three minutes)

Everything below works with no API keys and no microphone, except the two
steps marked with a key. Start the backend with `make demo` (no auto-reload)
and the frontend with `make frontend`, then open http://localhost:5173.

Before you start: run through it once, and decide whether you have an
`ANTHROPIC_API_KEY` in `backend/.env`. Without one, "Extract with Claude"
fails with a 502 and you fill the answers in by hand (step 2b).

## 1. The problem (20 seconds)

> A dispatcher has seconds to decide whether a call is safe for unarmed
> community responders. CivOps writes the routing rules down as software. A
> language model reads the transcript; plain rules make the recommendation; a
> person decides.

Point at the footer: synthetic demonstration, not a 911 system.

## 2. A routine call (50 seconds) · *Live Call*

1. Click **▶ Routine wellbeing check**. The transcript streams in. The
   dispatcher asks four screening questions and the caller answers each.
2. a. *With a key:* when the call ends, the four answers fill in as "No", each
   with an evidence quote and an **AI-proposed: confirm** tag. The card says
   **PROVISIONAL RECOMMENDATION: CRESS**, and **Confirm recommendation** is
   disabled.
   b. *Without a key:* set Call Type to Wellbeing Check and the four answers
   to No by hand, then **Evaluate Incident**. Answers you enter yourself are
   not provisional, so skip to step 4.
3. Say: *the model proposed these "no" answers; the system can raise urgency
   by itself, but only a person can lower it.* Click **✓ Confirm screening
   answers**. The card becomes a normal recommendation: **CRESS**, rule
   `CRESS-001`, with its source.
4. Change **Simulated call time** to *Monday 7:30 PM* and evaluate again:
   `CRESS-002`, CRESS follow-up, because the shift ended at 4 PM. Set it back.
5. Click **✓ Confirm recommendation**. It appears in the saved review log.

## 3. A hidden emergency (40 seconds) · *Live Call*

1. Click **▶ Noise complaint, then a hidden emergency**.
2. It starts as a noise complaint. On the last line the caller hears a man
   say he has a knife. The red banner appears **while the call is still
   running**, and the card turns to **HUMAN REVIEW**, rule
   `TRANSCRIPT-TRIPWIRE`.
3. Say: *that was a keyword scan on the raw transcript, not the model. Nothing
   the model extracts can clear it, and it goes to a person, never straight to
   police.*
4. Choose **Override to: Police**, type a reason, click **Override**. The log
   records what was recommended, what was chosen and why.

Optional third script: **▶ Argument with unknown safety details** ends at
`SCREEN-INCOMPLETE`. Unknown is never treated as "no".

## 4. The monthly review (35 seconds) · *Monthly Audit*

1. Click **Run Synthetic Audit**: 250 synthetic calls replayed through the
   same rulebook.
2. Click the **Could have gone to CRESS** card. The table filters to those
   calls; open one to see the rule, its reason and its source.
3. Point at the chart of calls by hour, and at the **Eligible, off duty, 4 PM
   to 8 PM** card: these are the calls an extended shift would pick up first.

Say that the "actual dispatch" column is invented for the demonstration.

## 5. The staffing question (35 seconds) · *What-If Simulator*

1. The page opens on "extend to 8 PM". Click **Run Scenario**: a few more
   calls per week, with a range across 50 simulated runs.
2. Click **LEAP recommended: every day, 9 AM to 2 AM**. The line chart shows
   coverage climbing with each hour; the bars show handled calls rising and
   off-duty misses falling.
3. Click **Stress test: 1 team, 180 min** to show calls missed because every
   team is busy.

Say that this is a ceiling in a model fed with synthetic, fitted arrivals, not
a forecast.

## If something fails

| Problem | What to do |
|-|-|
| No microphone, no Deepgram, no Wi-Fi | Nothing: the walkthrough above uses scripted calls and needs none of them. |
| No Anthropic key, or extraction returns 502 | Fill the answers in by hand (step 2b). The tripwire and the rules need no key. |
| "Transcript Stream Disconnected" | The backend is not running or was restarted. Run `make demo` again; the page reconnects by itself. |
| A scripted call seems stuck | Click **End Call**. The page closes the call itself after 10 seconds if the backend does not answer. |
| The page will not start a script: "already running" | A call is still running (maybe from another tab). `curl -X POST http://127.0.0.1:8000/calls/end` |
| You want the browser out of the loop | `curl -X POST "http://127.0.0.1:8000/scenarios/hidden_knife/play?speed=2"`; the open page picks the call up. |

## Using the live microphone (optional)

Needs `DEEPGRAM_API_KEY`, and on Linux `libportaudio2`. Tick the consent box,
click **☎ Start Call**, speak a fictional call, click **■ End Call**. The
microphone has one channel, so the transcript is not split by speaker. Read
[Responsible use](RESPONSIBLE_USE.md) first, and do a full run before relying
on it in front of people.
