# Common Water Lab

A local research dashboard for autonomous farms sharing a water resource. The UI,
source code, prompts, tests, and exports are in English. Games start with two farms
and support up to five without changing the rules.

## Start on this Mac

```sh
cd /Users/fatlindaislami/Documents/ChatGPT/MAS_LOKAL
.venv/bin/python run.py
```

Open **http://127.0.0.1:8765**. Alternatively, run `start.command`. The server binds
to loopback only; closing a browser tab does not stop a running experiment. Stop
the server with Ctrl+C. Open games are checkpointed and become interrupted on the
next server launch. Use Resume to continue.

For a fresh installation (Python 3.11 or later):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python run.py
```

The lock file records the versions validated on this Mac. `pyproject.toml` lists
the supported dependency ranges. No frontend build step, cloud account, external
fonts, Docker, or hosted database is needed.

## First pilot

1. Choose **New game → Scripted test agents → Technical pilot**.
2. Select two farms, 20 rounds, and communication on or off.
3. Use **One round** to inspect a completed round, or **Start** to run to completion.
4. Inspect the agent laboratory, public conversation, agreements, and event ledger.
5. Download the complete JSON or round-data CSV; **Save to export directory** writes
   both to the configured local folder (relative paths are relative to this project).

The four scripted scenarios demonstrate balanced irrigation, resource scarcity,
unused-water return, and insolvency. These controllers intentionally know the
mechanics. Their results are **technical tests, never LLM research findings**.

Regular research runs require Ollama agents and exactly 1,000 rounds. Short LLM
pilots remain marked as technical tests. The playing agents do not receive the
configured horizon, seed, true pond volume, biological rule table, or rival accounts.

## Ollama

Start the Ollama application or `ollama serve`. Model downloads are explicit setup
operations; neither the dashboard nor the model adapter downloads models.

```sh
ollama pull llama3.2:3b
ollama pull llama3.1:8b
```

Select **Autonomous Ollama agents**, refresh the installed model list, and choose
one model for the entire game. Other installed models are selectable. Every game
stores its selected model digest; resuming with a changed digest is refused.
Resuming also checks the saved rule, prompt, and source version. Restore that
version or create a new game after an implementation change; do not mix versions
inside one research run.

The default endpoint is `http://127.0.0.1:11434`; `OLLAMA_URL` can select another
local Ollama endpoint. `PORT` changes the dashboard port and `FARM_DB` changes the
SQLite database path. No remote model fallback is used.

The adapter uses JSON-schema responses, a configurable context/output budget,
temperature, and timeout. Invalid responses receive at most two corrective
attempts. An unreachable service, missing model, or repeated invalid action pauses
the game visibly as a technical error. No substitute policy or invented successful
action is inserted. A pause request waits for the in-flight call to finish and saves
its validated decision before stopping.

Prompt version `farm-agent-1.3` requires an explicit boolean `pass_turn` in every
discussion or reflection response. Missing choices are rejected instead of silently
defaulting to passing. Repair feedback explicitly explains that messages and contract
actions require `pass_turn: false`; after two failed repairs the visible error includes
the validation reason. Restart the server to load this change and create a new game:
existing runs retain their recorded prompt/source versions for reproducibility.

## Rules and information boundaries

The authoritative rules are documented in [docs/RULES.md](docs/RULES.md). The
developer-only rule document is never read by the model adapter.

- The pure Python engine controls all water, money, plant, weather, and elimination
  transitions. Agent actions cannot assign balances, pond levels, or plant health.
- Money uses integer cents. Irrigation inputs are decimal strings with at most
  three fractional digits. Water and rain use exact rational arithmetic; display
  rounding never feeds back into the game.
- Plant cohorts retain count, growth, health, and per-plant watering. Allocations
  split groups without imposing a plant-count ceiling; unassigned plants get zero.
- `views.observation` constructs an explicit allowlist. Memory search is scoped by
  both run and agent. Research logs cannot become an agent's memory source.
- The researcher dashboard is privileged. It shows information the agents cannot
  see. Peer messages remain unverified assertions, not authoritative game facts.

## Communication and agreements

Only discussion (phase 2) and post-NEWS reflection (phase 7) permit public messages.
Each allows up to ten contributions per active agent. Contributions are collected
against the same snapshot and published together after each pass. If all agents
pass, the phase ends. A pass does not prevent later participation if peers continue.
Messages are bounded to 2,000 characters. A contribution may include up to ten
structured agreement actions; a contract-only contribution still uses one slot.
All contributions use the same pre-pass state. Simultaneous rejections are resolved
before acceptances. Actions made obsolete by another action in that pass are
recorded as not applied, with a public outcome, instead of blocking the game.

With communication off, agents can use the same maximum number of private thinking
steps in both phases. They can stop early. Equal opportunity budgets do not imply
identical inference counts or time; all actual model calls and tokens are recorded.

Agreements contain one request and/or net-withdrawal limit per participant and a
bounded round interval. The proposer signs the proposed version. Every participant
must explicitly accept that exact version. Single-agent commitments are permitted
and reported separately. A request above the limit is a breach even if water
scarcity prevents delivery. A net-withdrawal limit is evaluated against actual use.

Changes require a replacement proposal and new signatures. An accepted future
replacement shortens the old agreement's effective interval. Until accepted, the
old obligations remain. Unilateral cancellation is effective from the next round;
it cannot erase current or past breaches. Other parties retain their own limits.
Overlapping agreements are evaluated individually. Unsigned proposals expire when
their starting round reaches settlement. NEWS agreements start no earlier than
the next round. Withdrawn or eliminated participants are excluded from evaluable
compliance denominators; affected joint results are `not_applicable`. Any available
in-round limit checks are still retained as evidence. The remaining participants'
individual results continue to be evaluated. There are no extra penalties.

## Persistence and reproducibility

`data/lab.sqlite3` contains the authoritative checkpoint, append-only events,
accepted decisions, observations, model request/response traces, and experiment
queues. The directory is ignored by Git. Phases and conversation passes commit
state and events in the same transaction. Each decision has the stable key
`round:phase:turn:agent`, unique within its game. Restart reuses accepted decisions
instead of requesting or executing them twice. An interrupted, unaccepted model
request may be retried, but has no game effects before acceptance.

The complete JSON export includes rule/prompt versions, source SHA-256, runtime,
config, model digest, weather state, raw and corrected responses, actual decisions,
events, and final status. Exact fractions are encoded as
`{"$fraction": ["numerator", "denominator"]}`. CSV money columns are **cents**;
water columns use exact integer or numerator/denominator notation. CSV includes
test/research and controller labels. These are researcher exports containing
private data, not inputs for agents.

The dashboard conversation shows the most recent 200 contributions; the complete
conversation remains in the JSON event ledger. Agent context uses the latest 30
contributions plus bounded, owner-scoped recall. Plant identifiers use independent
per-farm counters, and elimination membership changes reach agent observations only
with official NEWS, avoiding incidental information leaks through implementation details.

## Paired experiments

Select a base game, then open **Experiments**. Choose seeds, model names, and whether
to balance all initial starting positions. Creating a queue does not execute it.
Run the queue explicitly; one game is processed at a time. A technical error pauses
the queue. Resume skips completed games. Each model/seed/start tuple produces one
communication-off and one communication-on game with fresh memories.

Compare completed pairs using social/individual profit, pond trajectories, and
survival. Report self-commitment and group compliance separately, along with the
number of evaluable agreements and rounds without agreements. No agreements means
not applicable, not zero cooperation. Five-farm compositions default to three
short-term and two reciprocal agents and can be changed in setup.

Read [docs/RESEARCH.md](docs/RESEARCH.md) before interpreting results. Long-run
experiment counts should be selected after timing real pilots. Same weather seeds
are reproducible; model decisions are not guaranteed bit-for-bit reproducible.

## Tests and project structure

See [docs/VALIDATION.md](docs/VALIDATION.md) for the completed checks, measured local
pilots, and remaining research-validation limits.

```sh
.venv/bin/python -m pytest -q
node --check static/app.js
```

| Component | Responsibility |
| --- | --- |
| `farm/engine.py` | Deterministic seven-phase state machine and exact accounting |
| `farm/contracts.py` | Signatures, cancellation, replacement, evaluation |
| `farm/views.py` | Agent allowlist and research metrics |
| `farm/agents.py` | Local Ollama adapter and labeled test controllers |
| `farm/runner.py` | Single worker, frozen observations, pause/resume |
| `farm/store.py` | SQLite transactions, action identities, private recall |
| `farm/app.py` | Local API, exports, paired experiment queues |
| `static/` | English dashboard, no external frontend dependencies |
| `tests/` | Mechanics, information boundaries, runtime and API acceptance |

The API is documented interactively at `/docs`. Key routes include
`POST /api/runs`, `GET /api/runs/{id}`, control actions `start`, `pause`, `resume`,
`step`, and `export`, agent observations, events, model traces, downloads, and
experiment creation/execution/results. Setup config and action schemas reject
unknown fields. This is a single-user local application, not a public hosting target.

## Operational limits

- Current observations are never silently cut in half to fit context. Optional
  historic records are dropped whole first. If current data still exceeds the
  selected context, the game pauses. Create a new game with a larger context;
  the saved experimental configuration is not silently changed.
- Only one server process should open a database for execution. Multiple workers
  or concurrently running server instances are not supported.
- Exact checkpoints and full model traces prioritize auditability over disk size.
  Very large experiments can require substantial local storage.
- Research games are not editable mid-run. Changing experimental conditions means
  creating a new game. Resume retries the unexecuted step under the saved config.
