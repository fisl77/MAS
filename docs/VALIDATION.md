# Validation record

## Individual public turns in rules 1.5 and prompt 1.20

Four independent comparisons used the recorded start of discussion and post-NEWS in rounds 1 and 8 of run
`8e41c40a4c88`. The historical engine replayed accepted decisions up to each checkpoint into an isolated
database, including each farm's experience archive at that time. The baseline is the original published
transcript from prompt 1.18. Each comparison started from that same farm and agreement state with the new
conversation rules, the same profiles, the same installed `llama3.1:8b` digest and temperature zero.

| Checkpoint | Historical exact repeats / spoken messages | New exact repeats / spoken messages |
| --- | ---: | ---: |
| Round 1 discussion | 2 / 6 | 0 / 20 |
| Round 1 post-NEWS | 1 / 2 | 0 / 20 |
| Round 8 discussion | 8 / 10 | 0 / 20 |
| Round 8 post-NEWS | 4 / 8 | 2 / 20 |
| Total | 15 / 26 (57.7%) | 2 / 80 (2.5%) |

The measure counts every occurrence of an already published text after its first occurrence within the same
phase, across both speakers. It ignores surrounding whitespace, empty messages, passes and unpublished drafts.
The relative reduction was 95.7%. All four new conversations reached the contribution limit. Related paraphrases
still occurred. In round 1 both farms described prior crop trials before planting had taken place.

In two additional controlled turns at the round 8 discussion checkpoint, Farm A asked Farm B about 0.5 L per
seedling or proposed a zero-liter cap for the following round. B correctly reported all 100 seedlings died,
matching its own round 4 record, although it also misstated cents as coins. In the second case B suggested
300 liters in its text and gave an irrigation reason. It submitted no formal counterproposal. An engine test
separately verifies that a changed offer can be proposed and signed on the immediate next turn.

The read-only source run, archived inputs and comparison outputs are identified in
`data/qa/round-robin-20261118-112544/`. Final transcripts and call logs are under `release/`.
The automated suite passed all 224 tests.

## Recovery of three rejected actions in prompt 1.18

Replayed the final rejected raw output from each checkpoint, then called the installed Llama 3.1 8B model for the correction. The recorded account, crop and agreement states were the inputs. Validation left each source state intact.

| Failed checkpoint | Rejected action | Validated model correction |
| --- | --- | --- |
| `31ec377732c6`, round 2 NEWS, B | Start 2573, end 5 | Replacement of c4 covering round 3 with both participants |
| `435e5edb97de`, round 3 NEWS, C | Only C supplied bounds for replacement of c26 | Bounds for A, B and C covering round 4 |
| `594277e7e06e`, round 4 farm work, B | Requested 20 plants in a group with 10 available | Chose 10 in that group and kept the other affordable treatments |

The terms retry encodes dates as a delay from the earliest legal round and an additional number of rounds. A replacement ID selects the exact participant set. The farm planning tool tracks remaining plants across split treatments together with remaining water. Historical accepted actions still use absolute dates and the original irrigation representation. The complete automated suite passed (211 tests).

## Free dialogue in prompt 1.17

All 210 automated tests passed. The tests exercise the two shared follow-up slots for older questions and offers, attribution and privacy, the existing context and correction budgets, the new 600-character model reply limit, historical decisions, contract actions and early closure.

Four frozen situations were run with `llama3.1:8b` at temperature zero, context 16,384 and output allowance 2,048. The same reciprocal farm received the same world state in both versions. An intermediate draft generated four passes and prompted revision. The final requests for these cases were checked against the recorded revised requests. The small controlled comparison yielded the following outcomes.

| Situation | Prompt 1.16 | Prompt 1.17 |
| --- | --- | --- |
| First conversation before planting | Proposed a water cap | Asked for advice about the first order and sowing |
| Direct question about a plant trial | Proposed a contract and discussed fees | Cited the growing treatment, questioned how reliable the difference was and sought other observations. Omitted the requested health change. |
| Peer claimed the lower dose always helped | Proposed limits on fees | Compared its measured outcomes, including the dead plant and the surviving plant’s actual growth and health |
| Open proposal with a request for a decision | Verbally accepted and countered without a formal action | Referred to the proposal and asked about a treatment. Left the decision open. |

The old and new prompts took six and four model calls respectively. Across the four initial requests, prompt 1.17 added 78 UTF-8 bytes and used five fewer measured input tokens per case. Fixtures, replies, call counts and lengths are in `data/qa/free-dialogue-1-17-fixtures.json`, `data/qa/free-dialogue-1-17-before-50fdd849.json` and `data/qa/free-dialogue-1-17-revised-92a3362f.json`.

The autonomous pilot completed three rounds with one farm of each profile, seed 42, 400 starting coins and the same model settings. Run `c15c7c2e0ac7` made 297 model calls, including 99 subsequent attempts and three validation errors that recovered. Its 255 public-phase calls used a median of 4,314 input tokens and a maximum of 5,774. The longest accepted message contained 600 characters. Each pre-order discussion exhausted its contribution budget and each post-NEWS conversation ended through repetition.

Of 154 published messages, 60 had distinct text across the pilot. A case-insensitive whole-word search for contract(s), agreement(s), `max_request` or `max_net` matched 148 messages. This measures mentions and allows multiple topics in a message. Round one included a request for sowing advice and a claim about a previous growing round before the farm had any results. Several farms later described `max_net` as a revenue percentage and echoed the same wording. Directed questions elicited more relevant answers in the controlled comparison, while sustained autonomous exchange still exhibited repetition and unsupported claims. Full decisions, model calls and events are in `data/qa/free-dialogue-1-17-pilot-901d5663.sqlite3`, with the pilot summary in the matching JSON.

## Authorized Llama continuation, 18 November 2026

The user clarified the project-specific model policy: Common Water Lab currently
tests `llama3.1:8b` (with `llama3.2:3b` also relevant), while Agentenwerkstatt uses
`qwen3.5:9b` as its base model. The workspace instructions now record this distinction.

Continuation `c8312009e4fe` preserves the failed run `31a6a41513a1` unchanged and
starts from its round-12 discussion checkpoint with prompt 1.16. The model and
digest, game configuration, finances, plants, working memories, agreements and
random state are unchanged. All 978 events, 855 accepted decisions, 1,030 calls,
855 observations and 176 measured experiences were copied and checked for exact
equality before resuming. The continuation metadata and a ledger event identify
the old/new implementations and the inherited trace boundary. Four already
accepted decisions from the interrupted pass were retained; only E was retried.

The actual Llama 3.1 retry produced a valid proposal with one E entry, and the
runner advanced beyond the failed pass. The application showed the continuation
running without a technical error. This verifies recovery of the participant
failure; it does not certify the farming or negotiation claims in public text.
Backup: `data/qa/before-llama-continuation-20261118-073917/lab.sqlite3`.
Provenance: `data/qa/llama-continuation-20261118.json`.

## Unique proposal participants, 18 November 2026

Prompt `farm-agent-1.16`, unchanged rules `farm-1.4`: **201 automated tests passed**.
Run `31a6a41513a1` stopped at round 12, discussion pass 5, Farm E. Its three
Llama responses listed E twice with different bounds. All three were rejected;
accepted decisions from A through D remained checkpointed, and the invalid
proposal was never applied.

The model-facing proposal now represents `limits` as a farm-keyed object with the
actor required. Each participant receives one request bound, one net-use bound,
or both. The adapter preserves all chosen values in the existing internal list
format. Duplicate raw JSON keys are rejected before overwriting, and legacy list
duplicates receive actor-specific feedback. Tests cover missing/foreign actors,
duplicate keys, conflicting bounds, malformed/truncated JSON, exact translation,
original traces and no state mutation during repair. The large-inventory and
large-agreement context-budget regression remains within its original allowance.

Only the permitted `qwen3.5:9b` was called for live validation. A synthetic format
probe produced a valid proposal with distinct E and B entries. A separate replay
of the frozen failed observation produced a valid rejection of c58; applying it
together with the four already accepted source decisions advanced the test copy
to discussion pass 6. The replay needed one output-limit correction (43.91 seconds
for the initial attempt, 2.70 seconds for the valid retry). This is a cross-model
technical replay, not a continuation or validation of the original Llama policy.
The original run was verified unchanged. Full records are in
`data/qa/participants-1-16-39c7087c.json` and the matching SQLite file,
source SHA-256 `91795a7dd418b72bf48f344587f605abf656914e10a4bd8b26c403c013e7a2a3`.

## Dialogue review and unanchored instructions, 18 November 2026

Rules `farm-1.4`, prompt `farm-agent-1.15`: **189 automated tests passed**.
JavaScript syntax and whitespace checks passed. Coverage includes early closure
after two passes without new content or changed agreement state, fresh questions
and signatures, bounded draft reconsideration, fee review with intentional public
deception preserved, mutually exclusive passing/contribution output shapes, and
removal of numerical proposal examples. Full accepted messages and original model
attempts remain in the research trace. Temperature is unchanged by these fixes.

An initial five-farm Qwen `qwen3.5:9b` pilot at temperature zero exposed two remaining
problems: public claims about shared delivery costs, and a pass containing a message.
The fresh discussion stopped at the latter invalid action after its correction budget.
That failed action was not executed. Both prompted the targeted review and output
schema changes. The separate continuation of a recorded echo-heavy discussion produced
20 messages with 19 distinct texts and reached the contribution limit; wording diversity
does not establish reasoning quality. Its 45 calls included 24 corrected/failed attempts.
Original pilot records: `data/qa/dialogue-1.json` and `data/qa/dialogue-1.sqlite3`.

The final five-farm continuation used an isolated copy of the failed checkpoint,
Qwen `qwen3.5:9b`, temperature zero, a 16,384-token context and 2,048-token output
budget. It completed both remaining speaking passes and ended normally after two
silent passes, with each farm having used only three public contributions. All ten
repeated drafts were reconsidered and the model chose valid passes; no new public
messages were published and no pass/message conflict recurred. This tests recovery
and early closure, not the quality of a fresh negotiation or a complete game.

The continuation required 30 model calls and 472.4 seconds: each first attempt
exhausted its output budget without complete JSON, each direct retry repeated a
position, and each review produced a valid pass. Output-budget retries therefore
remain a material latency limitation. No fee-review trigger occurred in this final
continuation; the fee-review path and preserved deceptive choice were covered by
automated adapter tests. Results and full traces are in
`data/qa/dialogue-1-15-followup-8e97c7fa.json` and the corresponding SQLite file,
run `10cf6ed7305d`, source SHA-256
`e0ffbe714b84e497e0e691cf01ab2b46b50fb80b696a1bbfd2444e57e9705441`.
The original dashboard game remains paused and retains its recorded versions.

## Phase instructions and private experience recall, 17 November 2026

Prompt `farm-agent-1.14` uses rules `farm-1.3`. All 172 tests passed.
Coverage includes partial note updates, raw historical exports, owner/run
isolation, dose and round queries, attributed summaries after eviction from
the dashboard window, and exact pending terms and available irrigation groups.

An offline replay compared the first request for 96 accepted decisions in rounds
6–8 of game `ebbc8e6007d3` with its recorded 1.13 request. The replay checked
inventories, balances, deliveries, original notes, NEWS and terms for equality.
Median system plus user text fell from 21,976 to 7,788 UTF-8 bytes during farm
work and from 23,333 to 10,868 during discussion. Historical free-text notes used
the bounded legacy projection. The comparison measured input size. See
`data/qa/agent-memory-1.14-comparison.json`.

In a separate three-decision Qwen 3.5 9B check, the first attempt in each phase
exhausted 2,048 output tokens with no visible JSON. A direct retry produced a
valid planning note, rejection of an existing proposal and a six-liter irrigation
plan across two groups. The public assertion that one dose was optimal remained a
speaker claim. The measured archive contained only executed results. The selected
actions, per-attempt token counts and fixture are in `data/qa/agent-memory-1.14-qwen.json`.

## Model-selected budget planning on 17 November 2026

Prompt `farm-agent-1.13`, unchanged rules `farm-1.3`: **166 automated tests passed**.
JavaScript syntax and whitespace checks passed. Run `ebbc8e6007d3` reached
round 5 farm work; Farm C repeatedly proposed 12 liters against a 5-liter
delivery despite exact accounting feedback. Whole-plan arithmetic feedback
therefore did not reliably recover every Llama action.

An overspent plan now enters a private model-selected draft. The model keeps,
revises, cancels or finishes its proposed treatments. Every keep and revised
dose is bounded by exact remaining water; counts also respect inventory.
Draft choices have no game effect until the final plan validates and is
accepted. Failed choices do not execute earlier draft steps. Public message
budgets are unchanged. Each real tool call is traced under the base action
key; only the final game decision enters accepted decisions and recall.

Tests cover 120 keep-order permutations, inventory limits, exact fractional
balances, count/dose revisions, cancellation, explicit finish, invalid IDs,
invalid tool replies, unchanged authoritative state and private notes, and
normal implicit zero irrigation after the model spends the full budget.

An isolated `llama3.1:8b` replay chose its two new-plant treatments at 2 and
3 liters, totaling exactly 5 liters. The initial full plan overspent; every
tool choice then succeeded on its first attempt. The initial implementation
used nine calls/28.4 seconds including redundant explicit zero-irrigation
choices; the final implementation omits those no-op steps once water is
exhausted, as verified by regression tests. Report/trace:
`data/qa/selector-replay-7351770b.json` and the adjacent SQLite file. The
pre-change source/checkpoint is `data/qa/before-budget-selector-20261117-173101`.

The resumed technical game passed all farm-work decisions and reached round 6.
Farm C used 2 private selection calls after its initial rejected plan; its
accepted plan used exactly 5 liters for two new plants at 2 and 3 liters.
The recorded revision retained 212 prior accepted decisions/observations and
232 prior calls, reusing the A/B decisions already accepted in that pass.
Old/new versions and source hashes remain recorded; this is a mixed-version
technical continuation, not a uniform research run.

## Shared farm-water budget repair on 17 November 2026

Prompt `farm-agent-1.12`, unchanged rules `farm-1.3`: **154 automated tests passed**.
JavaScript syntax and targeted renderer checks passed; the renderer clears a
recovered run error while preserving unrelated notices.

Run `ebbc8e6007d3` stopped at round 3, farm work, Farm C. It requested new-plant
doses of 2 and 3 liters while allocating zero to existing plants, against a
2-liter delivery. The old generic error called the combined total irrigation
and mentioned zero delivery even though delivery was positive.

Exact public feedback now separates new/existing spending, multiplies counts,
and identifies excess and offending entries. Corrections receive a fresh
response request with this ledger. Per-dose native-format bounds use only
the known delivery and decimal precision; biological choices remain unknown.
Combined resource validation remains authoritative; no proposed action is
automatically scaled or replaced. Tests cover fractional bounds/accounting,
mixed treatments and repeated invalid responses with no partial execution.

The isolated Llama replay first proposed 4 liters, then corrected its plan
to one new plant at 2 liters after the exact ledger (one correction, two
calls, 10.7 seconds). It retained the configured 16,384-token context and
2,048-token output limit. Report/trace: `data/qa/water-replay-bb4e2a88.json`
and the adjacent SQLite file. Pre-change checkpoint/source/UI backup:
`data/qa/before-water-budget-20261117-170903`.

The same technical game resumed past all farm-work decisions and reached round 4.
Farm C chose one new plant at 2 liters, with zero irrigation for existing plants.
The implementation revision preserves all 142 prior accepted decisions/observations
and 154 prior calls, reusing A/B decisions already accepted in that pass. Old/new
source hashes and prompt versions are recorded; this remains a mixed-version
technical continuation.

## Repetitive output repair on 17 November 2026

Prompt `farm-agent-1.11`, unchanged rules `farm-1.3`: **141 automated tests passed**.
Run `ebbc8e6007d3` stopped in round 2, farm work, at Farm A. All three attempts
ended with `done_reason=length` at 2,048 tokens. Each contained 185 identical
one-plant, zero-water entries followed by unfinished JSON. No partial response
was accepted or executed.

At zero delivery, the model schema now uses one combined sowing entry and at most
one irrigation entry per existing group. Plant counts have no new ceiling;
different positive doses remain separate when water is delivered. Truncation
feedback requests fresh compact JSON without replaying the repetitive fragment;
raw outputs remain in the trace. Tests cover large grouped counts, different
doses, fresh retries, repeated truncation without partial execution, and valid
complete JSON even when termination metadata says length.

An isolated `llama3.1:8b` replay returned a valid complete action on its first
call (7.4 seconds), with no corrections/errors and termination reason `stop`.
Context remained 16,384 tokens and output limit 2,048. Report/trace:
`data/qa/output-replay-12f048a7.json` and the adjacent SQLite file. Prior source
and checkpoint: `data/qa/before-output-loop-20261117-165354`.

The same technical game resumed past farm work for all five agents and reached
round 3. Its revision event records old/new prompt and source hashes; the
105 prior accepted decisions/observations and 114 prior calls were retained.
This is an explicitly mixed-implementation technical continuation.

## Context-budget repair on 17 November 2026

Prompt `farm-agent-1.10`, unchanged rules `farm-1.3`: **136 automated tests passed**.
JavaScript syntax and whitespace checks passed. The stopped technical run reached
round 6, phase 2, pass 6: Farm C's input exceeded the conservative byte budget even
after the old builder dropped recalled snapshots and all but one public message.

The revised builder shortens repeated instructions, uses compact JSON/schema
constraints, windows whole speaking passes, and selects owner-only historical outcome
summaries. It explicitly records historical omissions. Current plant inventories,
balances, memory and agreement terms are retained; large record collections can be
encoded losslessly as columns/rows. Corrective requests use the same budget and only
the latest failed answer, with its full original text retained in the trace.
Regression checks cover five-speaker pass integrity, 65 current agreements, large
inventories, ownership/privacy, oversized failed responses, and explicit failure
when genuinely oversized current data cannot fit without losing actionable records.

An isolated replay of Farm C's failed checkpoint with `llama3.1:8b` succeeded on its
first call, with no corrections/errors (12.3 seconds). Context remained 16,384 tokens,
output allowance 2,048; message content used 27,144 UTF-8 bytes against the conservative
28,160-byte input estimate. This is not an exact tokenizer count. Report/trace:
`data/qa/context-replay-966a1f0f.json` and the adjacent SQLite file. Prior source and
checkpoint are saved under `data/qa/before-context-budget-20261117-154346`.

The same technical game resumed beyond the failed pass. Its implementation-revision
event records the prompt/source change; 346 accepted decisions/observations and 351
prior calls were retained unchanged. The two already accepted decisions in that pass
were reused, and only Farm C's missing decision was requested again. This remains an
explicitly mixed-implementation technical continuation, not a uniform research run.

## Contract-action repair on 17 November 2026

Prompt `farm-agent-1.9`, unchanged rules `farm-1.3`: **130 automated tests passed**.
The failed action in `0b81124528c1` attempted to accept another farm's already
active self-commitment with `contract_id=null`. Existing-agreement actions now
require a nonempty ID. The model schema separates proposals from accept/reject/
cancel actions and offers only actor-appropriate IDs for each action; acceptance
excludes already active, already signed, and too-late proposals. The prompt and
corrective feedback list the actor's available choices explicitly.

An isolated replay of the exact failed Llama observation produced a valid silent
pass on the first call, with no corrections or errors (37.7 seconds). Trace/report:
`data/qa/contract-replay-6799f319.sqlite3` and the adjacent JSON file. This checks the
reported failure, not the reliability of every possible future model action.

The technical game was continued at round 3, discussion pass 1, after an explicitly
recorded implementation revision. Its prior checkpoint and failed calls are saved
under `data/qa/before-contract-selection-20261117-150405`. All 123 accepted decisions,
123 observations, and 127 prior calls were retained unchanged. The checkpoint and
event ledger record both old/new prompt versions and source hashes. This mixed-
implementation continuation is a technical test, not a uniform-version research
run; normal resume checks still reject unrecorded source/version changes.

## Demo and conversation revision on 17 November 2026

Rules `farm-1.3`, prompt `farm-agent-1.8`: **124 automated tests passed**.
`node --check static/app.js` and whitespace checks passed. Coverage includes free
silent passes, independent ten-contribution budgets, two consecutive silent passes,
resuming after a pass, skipping exhausted speakers, checkpoint recovery, separate
NEWS budgets, cross-speaker repetition feedback, canonical duplicate proposals,
current-round date bounds and corrective feedback, and owner-only cultivation
evidence derived from executed actions. Repetitive speech alone no longer closes
a phase: closure follows the requested silence or exhausted-budget rules.

An isolated `llama3.1:8b` test began with observed deaths at 0.5 liters and an
incorrect private note claiming that dose was sufficient. The revised agent sowed
one plant at 1 liter and one at 2 liters. After observing the former die and the
latter grow healthily, its next farm-work decision used 2 liters for the surviving
plant and one new plant. Both decisions succeeded on the first call, with no
corrections or errors. The report is `data/qa/llama-learning-be47c41f.json`.
An earlier pilot still chose one zero-water planting; the final prompt therefore
includes a concrete comparison-format example, without supplying hidden biology.
These are short technical checks, not a full demonstration run or a guarantee of
successful strategy. Invalid actions still stop visibly after allowed corrections.

An isolated API/UI fixture verified the remaining-message display (including an
exhausted speaker), silent-pass counter, and rendered cultivation-evidence table.
No browser surface was connected, so there was no visual browser verification of
this revision. Original runs were preserved. The pre-change source backup is
`data/qa/before-demo-fixes-20261117-140911`; older runs require their recorded rules
and source, while the revised behavior applies to newly created games.

## Early conversation closure on 16 November 2026

Rules `farm-1.2`, prompt `farm-agent-1.7`: 111 automated tests cover early closure,
checkpointed stall counters, retained original messages, agreement-state changes,
new numeric terms/actions/timing/questions, separate NEWS counters, unchanged private
reflection budgets, and reduced worker call counts. JavaScript syntax checks passed.
In a deterministic repetition scenario, a public phase ended after three complete
passes instead of ten; the UI displayed the ending reason.

In an isolated synthetic scenario reusing the already discussed round-5 positions
from `4d7f6133af8e`, all three Qwen agents chose to pass with the revised instructions.
The phase ended at pass 8 and advanced to water requests. Three calls completed
without corrections/errors (76 seconds). This is a technical smoke test, not a
measured improvement across research runs. Report: `data/qa/discussion-stopping-023aa308.json`.
Text similarity is conservative and may miss semantic repetitions; it does not claim
to determine truth or understand all novel content. The prompt also clarifies fixed
per-farm fees and the round/phase order to avoid fictitious timing/cost negotiations.

The old run was paused; its pre-change source is saved under
`data/qa/before-conversation-stopping-20261116-154159` for restoration.

## Conversation availability revision on 16 November 2026

Prompt `farm-agent-1.6`: **94 automated tests passed**; JavaScript syntax checks
passed. New tests cover the shared reply clock, passing without permanent removal,
early phase closure, no leakage of eliminations before NEWS, identical availability
across simultaneous decisions, and accepting last-pass proposals in a later window.
Dashboard assets also use versioned URLs so updated profile options are loaded.

Conversation availability adds public information only; it does not change the
ten-pass limit or reveal in-flight model decisions. The ongoing `3989ac8c62d0` run
was paused and its pre-change source saved under
`data/qa/before-conversation-availability-20261116-133919` before this revision.

## Revision validated on 16 November 2026

Rules `farm-1.1` and prompt `farm-agent-1.5`: **90 automated tests passed**;
`node --check static/app.js` passed. Coverage now also includes configurable
starting capital (200/500/725 coins across complete games), strict input validation,
the Cunning experimenter profile, executable discussion-phase proposal examples,
signed-limit breaches without action blocking or extra fees, and capital/profile
preservation in exports and paired queues.

The New game form was verified in a separate local test database: the default is
500 coins, a 725-coin game was created with the new profile, and its 705-coin balance
after one delivery matched the account reconciliation. The application database's
existing runs were not modified by this UI test. Prompt guidance is not proof that
an LLM will always converse, deceive, cooperate or learn successfully.

A short, separate Qwen `qwen3.5:9b` discussion scenario elicited a direct answer to
a peer's proposed water cap, a formal proposal, and the peer's explicit acceptance
of the actual contract ID. The agreement became active. Both agents initially
reached the 2,048-output-token limit with an empty JSON response, then succeeded
after one corrective attempt each (four calls total). This confirms that the
conversation/contract path works with recovery, not reliable first-attempt output
or successful deception. Traces are in `data/qa/conversation-1.5-37e99394.sqlite3`.

## Earlier validation

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
