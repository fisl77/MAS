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

New games default to **500 starting coins per farm**. Set any positive whole-coin
amount in **New game → Starting coins per farm**. The amount is recorded in the
game configuration, agent instructions, JSON/CSV exports and paired experiment queues.
Recorded games without this setting retain their historical 200-coin starting capital.

In **New game → Harvest and water fees**, choose health-based pricing, a whole-coin
transport fee per positive delivery (default 20), and an optional fee per positive
return (default 40). With quality on, selling at 15/20 health earns 15 coins per plant.
With quality off, a living ripe plant earns 20. Water returns automatically in either case.
Delivery can put a farm into debt. Sales repay debt, then returns are settled. Farms
with a net balance of zero or less at that point are eliminated, even in rounds without sales.
The setup preview and Agent laboratory show the same public rules the agents receive.
New games use rules `farm-1.7` and prompt `farm-agent-1.27`. Model-facing accounts,
archived account observations and official NEWS balances use coins. The engine and round-data CSV use cents.
The Windows pilots use `data/lab-learning-1-25.sqlite3` on port 8772.

From PowerShell in this project, resume access to those pilots with

```powershell
$env:FARM_DB = (Join-Path $PWD 'data\lab-learning-1-25.sqlite3')
$env:PORT = '8772'
.\.venv-windows\Scripts\python.exe run.py
```

For the earlier Windows game `a5e41c403a34`, the verified 1.6 snapshot and its
`Start-Previous.ps1` launcher are under `data/versions/farm-1.6-a022ebb390cb/`.
The launcher opens the earlier database on port 8770. Choose Resume in that
dashboard to continue the saved NEWS turn with `llama3.1:8b`. The same folder
contains a separate checkpoint backup.

Farm-work responses combine identical treatments using `count`; different doses
remain separate. With zero delivery, only one sowing dose is possible, so the model
format permits one combined new-plant entry and one irrigation entry per existing
group. This does not cap plant counts. A length-terminated, incomplete JSON response
is recorded as truncated and never executed; correction asks for fresh, compact JSON
without replaying the repetitive fragment. Complete valid JSON at the output boundary
is still accepted. Configured context/output limits remain unchanged.

Prompt version `farm-agent-1.13` teaches active public conversation: respond to peers,
ask specific questions, challenge claims and negotiate concrete offers rather than
copying private memories. Passing is encouraged when there is nothing new to contribute.
Conversation phases include a structured agreement guide and a proposal format example.
Agents also receive the current pass, remaining reply opportunities, eligible farms,
and publicly known eliminations. They are warned when no reply can arrive within the
current phase, and that passing once does not permanently remove a farm. New multiparty
proposal examples in the last pass start no earlier than the next round, allowing
later signatures before expiry. No in-flight decisions or unpublished eliminations
are disclosed by these availability indicators.
Agreements remain voluntary even after signing; breaches are measured without blocking
actions or imposing extra fines. Cancellation takes effect from the next round.

The demonstration default is **llama3.1:8b**; refreshing installed models preserves
an existing selection. No model is downloaded automatically. Date bounds in agreement
schemas and correction feedback use the actual current round and phase.

Each farm also receives a separate **measured cultivation evidence** record. It is
built only from its executed actions and plant results, not from private guesses or
peer claims. It persists when short-term plant results clear, and compactly distinguishes
failed doses, surviving treatments and healthy growth. Public claims are labelled as
unverified in model context. For exploration, farms are advised to try 1–5 comparable
plants per dose, initially around 1 L apart. After contrasting outcomes they can refine
that interval in later rounds (e.g. 0.1 L steps). After uniform failures they are advised
to widen the search. The farm receives optional comparisons derived from its own
measured seedling outcomes. Its private sowing plan carries counts, doses and the
exact water total through ordering and farm work for the current round. The agent
chooses the actual order and treatments after considering existing plants and delivery.
Production can scale after healthy growth across rounds at the same stage when the farm
expects to afford future irrigation. The simulation allows any physically feasible batch size.
The dashboard sums plant observations per stage and dose across rounds.

The new **Cunning experimenter** profile combines cautious planning and small farming
experiments with strategic deception in public messages, opportunistic agreements,
and an aim to outlast rivals. Its private observations and accounting remain factual;
it has no extra tools, information or power over other farms. This is an instruction
for autonomous Ollama agents, not a guarantee of behavior or a different scripted policy.

The prompt retains basic farming knowledge: rain/dry days affect
pond inflow only, water must be requested for both existing and intended new plants,
and farm work supports per-plant or subgroup watering of multiple plants per round.
It explains sowing, automatic harvest, observations, and adapting treatments from
measured growth, health and costs. Exact biological thresholds remain hidden.
Prompt `farm-agent-1.21` selects separate instructions for planning, ordering,
farm work, private reflection and public discussion. Farm work includes current
delivery, all plant groups and the shared allocation budget. The conversation
and signature instructions appear during public discussion and post-NEWS dialogue.
Create a new game after restarting the server; old games keep their recorded versions
and cannot be resumed under the changed prompt/source.

During planning each farm chooses a private focus and writes its own next move.
The near-term profile selects a cost or income consideration. The reciprocal
profile chooses a known active peer or an independent check. The experimenter
chooses a trial outcome, disclosure decision or reason to defer. Later turns
can revise the plan or update only an open question or insight.

For a measured crop result, a farm can insert `[[trial]]` as a standalone
sentence. The server fills it from an executed observation on that farm, or
states that a result is unavailable. A check for unsupported accounts of crop
trials gives the speaker one revision. If the problem persists, the affected
message or note is withheld and the raw attempts remain in the research trace.
Peer statements retain their source. The cunning profile can explicitly choose
a bluff with a private intended benefit on the original draft. The researcher
can inspect its most recent declaration under **Agent laboratory → Private working memory**.
Intent is self-reported and free-text checks cannot establish a speaker's beliefs.

Rule version `farm-1.5` gives each farm ten public contributions per phase. Public turns rotate
between farms. The discussion starter rotates each round and its successor opens after NEWS.
The prompt requires an explicit boolean `pass_turn` in every
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
Each farm has **ten actual public contributions** in each phase. A message and/or
contract actions in one response count as one contribution. Passing, silence and
private memory updates count as zero. There is no fixed ten-pass deadline. A farm
that passes may return later; one that used all ten contributions is not called again
until the next conversation phase. Observations show every farm's remaining budget.

The phase ends when all remaining eligible farms pass consecutively, everyone has used the
budget, or two full cycles pass without new content or changed agreement state. Every speaker
sees new contributions since its last turn. A pass marks the conversation as seen.
Checkpoints preserve the speaker order and counters.
Original messages are retained and ending reasons/budgets are shown in Conversation.

Repetition checks compare all speakers, while protecting fresh concise personal
consent and actual new signatures. A model draft that echoes the current discussion
counts as a free pass. If the farm also signs or changes an agreement, the action
is published with its receipt. Equivalent questions and repeated invitations to discuss
the same topic count as passes. Questions about a new round, dose or recipient can be asked again.
Original drafts remain in the model call log. Identical agreement
terms reuse the same contract ID; an explicit identical proposal adds the proposer's
signature to those exact terms if it is new. Repeating one's own signature changes
nothing. Changed participants, limits, dates or replacement references remain distinct.

Conversation instructions describe proposing and responding in words, with the schema
providing the action syntax. Each farm chooses its own amounts, participants and dates.
Agents also choose their own conversation topic: cultivation, observations, trial
design, strategy, costs, trust and negotiations are equally available. There are no
topic quotas, compulsory stages or obligations to disclose knowledge. Information
may be shared, withheld, questioned or strategically misrepresented according to
the profile; private observations remain distinct from public claims. Without trial
results, agents can discuss hypotheses and proposed experiments. Contract operation
is a separate compact reference, not the expected outcome of every exchange.
Profiles prompt an individual assessment of costs, immediate gains, reciprocity or
strategic advantage. Delivery and return charges remain payable by the receiving
farm, including when it signs an agreement. Experiments use the configured temperature
and record every retry.

Before publication the adapter checks common claims about fee amounts, changes,
sharing and dated personal charges against the game's tariffs and the farm's accounts.
During both public phases the farm has zero unspent water. Orders use whole liters.
Formal agreements can limit the farm's request or net withdrawal. Existing named
bounds are checked against the public register.
The farm can quote the configured tariffs with `[[fees]]`, an executed treatment
with `[[trial]]`, or its own latest settled delivery, use, return and charges with `[[water]]`.
The farm gets a correction opportunity. A remaining conflict withholds the message
while preserving independent valid actions and private note changes. The cunning
profile can still mark a deliberate bluff about its private crop results on the first draft.
Public tariffs apply to every profile. Agreement
limits are upper bounds, not water orders or required quantities. Separate output
schema alternatives prevent a pass from also containing text or agreement actions.

New model proposals use a `limits` object keyed by participating farm ID. The
proposer's key is required; the output schema allows each visible farm once and
requires a request bound, a net-use bound, or both. The adapter translates the
explicit keys into the existing stored list format without inventing participants,
merging conflicting bounds or changing amounts. Duplicate JSON keys are rejected
before parsing can overwrite them. Legacy list replies still receive full validation;
participant errors identify the duplicated or missing farm. Formal agreements only
represent fixed bounds and dates, not additional conditional clauses in public prose.

Temperature controls variation in model output. Zero makes comparable inputs more
repeatable; higher values allow more variation and may increase errors. It does not
give agents additional knowledge or guarantee distinct strategies. The selected
value is stored with each game and used unchanged for its model calls.

Each public decision and its contract actions publish before the next farm speaks. Private orders
still share a frozen state. Newly generated public model messages are
limited to 600 characters, with instructions for one focused contribution in one
to three short sentences. Oversized unconstrained replies receive model-selected
correction within the existing attempt budget; published text is never automatically
truncated. Internal decisions retain the historical 2,000-character capacity, and
stored records are unchanged. Up to ten agreement actions remain available per
contribution. No private notes are automatically published.

With communication off, private reflection has up to ten thinking steps and ends after
two consecutive silent steps. Public contribution counts and private step counts are
different budgets; actual calls and timing are recorded separately.

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

Farm-water validation reports the exact combined spending of new and existing
plants, each subtotal and any excess. The model receives an explicit shared
budget; sowing and simultaneous comparisons remain optional. Individual doses
in the response format cannot exceed the delivered water, while combined totals
are still validated exactly. These are physical availability bounds, not plant
growth thresholds. Rejected allocations are never automatically scaled or
executed. Corrections receive a precise accounting ledger and fresh response
instructions. A recovered run error also clears from the dashboard on refresh.

When a validly formatted farm plan overspends, a private budget-planning tool
replaces repeated whole-plan arithmetic corrections. The model chooses which
of its proposed treatments to keep, revise, cancel or omit. Keeping a treatment
is offered only when its complete cost fits the remaining supply. For revisions,
the model selects a count and then a dose constrained by remaining water/count.
Each selection updates an exact unexecuted draft. Exhausted water implies zero
for unselected existing plants under normal rules; new zero-water planting still
requires an explicit model choice. Only the final validated plan is accepted
and executed once. Rejected private notes are not written. Tool calls are
separate traces linked to the base action, not extra public messages or recalled
observations. Valid initial plans retain the usual single-call path. Recovery
can require additional model calls; invalid tool choices still stop visibly
after their allowed corrections. No amounts are automatically scaled and no
substitute farming strategy is inserted.

## Persistence and reproducibility

`data/lab.sqlite3` contains the authoritative checkpoint, append-only events,
accepted decisions, observations, model request/response traces, and experiment
queues. The directory is ignored by Git. Phases and public speaking turns commit
state and events in the same transaction. Each decision has the stable key
`round:phase:turn:agent`, with an additional `:review` suffix for the final private review. Restart reuses accepted decisions
instead of requesting or executing them twice. An interrupted, unaccepted model
request may be retried, but has no game effects before acceptance.

The complete JSON export includes rule/prompt versions, source SHA-256, runtime,
config, model digest, weather state, raw and corrected responses, actual decisions,
events, and final status. Exact fractions are encoded as
`{"$fraction": ["numerator", "denominator"]}`. CSV balances, profit, fees and revenue
are **cents**; `starting_coins` is the configured amount in whole **coins**.
Water columns use exact integer or numerator/denominator notation. CSV includes
test/research and controller labels, starting coins, and each farm's profile. These are researcher exports containing
private data, not inputs for agents.

The dashboard conversation shows the latest 200 contributions. Every original
message is retained in the event ledger. In phases that use conversation history,
public turns emphasize the last contribution, a direct question since the speaker's previous
contribution, and at most one relevant owner observation. Peer claims retain their attribution.
The compact agreement register puts mentioned IDs and proposals awaiting this farm's signature
first and preserves every open or active agreement's exact terms.

Phase 1 covers provisional sowing and irrigation of existing groups. Phase 3 compares
whole-liter orders against that combined plan. A farm can submit both revised treatment lists
with its order. Phase 4 checks the accepted delivery against the proposed combined use.
Each draft that would incur a return fee gets one reconsideration. The farm sees the
exact remainder and charge and can try a different treatment, choose an exact fit where
useful, or keep its draft and accept the charge. Suggested doses show the arithmetic
and identify any healthy growth seen by this farm at that dose. The farm chooses the treatment.
Effective voluntary request and net-use caps and their latest evaluated outcome are private decision inputs.

The immediate plan, open question and insight can change during ordinary decisions.
After each NEWS exchange every surviving farm privately cites one of its own round records,
records a conclusion and chooses an intention for its next decision. Each farm can keep
a long-term goal, three open questions or tests, six named working notes and twelve lessons.
The farm selects which entry to replace or retire. Regular decisions retrieve up to three
relevant active entries. The review shows the active notebook. A query such as
`archive lesson:2` or `archive round 4` retrieves previous private versions.
The agent laboratory displays the latest review, cited record and changes. Its history
includes confirmations and decisions to retain a strategy. The model sees the actual cited
measurement alongside each selected lesson. An unambiguous contradiction with a current amount
or plan comparison prompts one correction. If it persists, the journal records the discrepancy
and the active lesson or named note uses the cited measurement. The farm still chooses its own next action.
Working notes keep the source, speaker and record location for a cited claim. Labels
distinguish official records, measured observations, hypotheses, plans and unverified claims.
A citation or confirmation preserves the status of the farm's interpretation.
Routine planting, ordering and irrigation context prioritizes records. Unverified
statements can be requested by explicitly recalling what another farm said or promised.
The farm sees up to four distinct recent watering outcomes with before and after growth and health.
Its separate SQLite experience archive records every
executed group treatment, rounds of account activity and its own agreement evaluations.
Archive writes commit with the corresponding game events. Each decision retrieves
up to three compact records scoped to that game and farm. A recall query can select
a dose, group, round, fees or agreement. Default retrieval uses the phase and skips
measurements already shown. Original decisions, notes, observations, dialogue and
model traces remain available in the full JSON export, including for earlier runs.
Further history reductions are disclosed in `context_window`.
Current inventories, balances and agreement terms remain complete; repeated record keys
can be packed into lossless columns/rows tables. Compact JSON and schema constraints
avoid repeated annotations. Every request, including corrective attempts, obeys the
same conservative input budget, reserving the configured output allowance. Only the
latest failed answer is included for correction; oversized failed text stays in the
trace and its omission is disclosed. If `qwen3.5:9b` exhausts its output allowance
with an empty visible answer, its remaining attempts for that decision request a
direct answer using `think: false`. They keep the same observation, output allowance
and validation. An inherently oversized current state still stops
explicitly rather than discarding actionable records. Plant identifiers use independent
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
