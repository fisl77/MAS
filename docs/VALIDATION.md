# Validation record

Validated locally on 15 November 2026. All games described below are technical
tests. They do not establish a communication effect, an equilibrium, or an optimum.

## Automated acceptance

`python -m pytest -q`: **72 passed**. `node --check static/app.js`: passed.

Coverage includes biological thresholds and harvest ordering, delivery and return
insolvency, exact rational water accounting, round-robin examples A–C, rotation,
weather and forecasts, privacy boundaries, voluntary discussion, signatures and
replacement, overlapping agreements, unilateral cancellation, elimination,
simultaneous rejection/acceptance, private reflection budgets, accepted-action
replay, queue pause/resume, legacy trace-counter recovery, API controls and exports. The only test warning concerns
Starlette's deprecated httpx TestClient integration; no test failed.

The deterministic engine also completed 1,000 rounds with both two and five
scripted farms, communication enabled, seed 42. Account identities were checked at
each transition. Measured engine-only times were 85.3 and 395.1 seconds respectively;
these exclude SQLite checkpoint and model inference overhead. The local report is
`data/qa/full-horizon.json`.

## Browser verification

Verified setup, two- and five-farm games, one-round stepping, start/completion,
agent observations and private notes, official NEWS versus peer contributions,
agreements, exports, and paired experiment creation. A ten-game five-farm queue
was paused, resumed, and completed with communication pairs and all five starting
positions. The verification database is `data/qa/final.sqlite3`; the five-farm
20-round reference game is `d5dacd67d6b1`, and queue `7329cae2784f` completed.

## Real local model pilots

Both explicitly approved models were installed through Ollama. Each pilot used
two autonomous farms, two rounds, seed 42, communication off, prompt version
`farm-agent-1.2`, fresh private memories, and the same model for both farms.

| Model | Run | Final status | Calls | Corrections / errors | Recorded call time | Tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| llama3.2:3b | `61b02194be49` | Completed | 56 | 0 / 0 | 518.5 s | 138,694 |
| llama3.1:8b | `51c590fa1aba` | Completed after interruption/resumption | 92 | 0 / 0 | 3,409.5 s | 198,944 |

Call time is the sum of recorded request durations, not total elapsed experiment
time. Token counts sum prompt and completion tokens across actual calls, including
repeated context. The 8B pilot used every available private reflection opportunity.
Its earlier pilot-script report captured an interruption; its final SQLite
checkpoint and refreshed export supersede that intermediate status.

Formal validity is distinct from strategic success. The 3B agents requested zero
water and lost unwatered new plants. The 8B agents requested 1,000 liters in the
final round and returned unused water; each finished with a loss of 120 coins.
Neither pilot harvested plants in this short horizon. Biological mistakes were
accepted and were not replaced with a scripted strategy.

Earlier failed pilots remain preserved: the initial response schema allowed
irrelevant phase actions; a later pilot tried irrigation without delivered water.
Both stopped visibly after the allowed corrections. The adapter now supplies
phase-specific schemas and explicit physical availability constraints. No hidden
plant-growth thresholds were supplied to either model.

These pilots predate final fixes to owner-local plant identifiers, the public
active-agent roster, concurrent contract conflict handling, and queue controls.
Their recorded source hash is retained. The final implementation passed the full
automated suite and browser checks; it has not undergone a new full Ollama research
run. No 1,000-round LLM study or five-agent LLM study was completed. Before choosing
a large experiment size, run communication-enabled pilots on a frozen version and
measure useful exploration, context growth, inference time, and contract use.

## Local evidence

- `data/lab.sqlite3`: original model pilots, accepted decisions and full traces.
- `data/exports/`: JSON and CSV exports, including refreshed completed pilots.
- `data/pilot-reports/`: intermediate and final technical summaries.
- `data/qa/`: isolated browser checks and full-horizon engine report.

Data and screenshots remain local and are ignored by Git. No cloud publication or
external data transmission is required to use the dashboard.
