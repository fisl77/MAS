"""Bounded model context; authoritative state and full research traces stay intact."""
import json

from .conversation import pass_key
from .schema import NOTE_LENGTH


SYSTEM = f"""You run one farm. Maximize your cumulative sale revenue minus fees and stay solvent.
Starting capital is separate from profit. Accounts use cents (100 = one coin).
Positive delivery costs 20 coins before harvest. Returning any unused water costs another 40.
Each fee is charged to that farm in that round. Agreement limits leave these fees payable.
Shared caps cannot pool deliveries or waive fees. An empty farm may order water for sowing today.
Farms cannot share fees, transfer resources or act for others. The end round and pond level are hidden.
Rain adds water only to the pond at round end. Dry means no rain inflow. Neither waters plants.
Orders are for this round only. Signed agreements are voluntary; breaches are recorded without extra fees.
Trust your own measured watering results over conflicting notes or claims. A dose that only caused death
in your trials is evidence to change treatment. Official NEWS reports public game outcomes.
Public statements, including quotations in older_discussion, can be false. Attribute them to their speakers.
Your private notes hold your profile's plan, open_question and insight ({NOTE_LENGTH} characters each).
Update changed notes. An empty open_question closes it. For a change optionally cite memory.based_on:
recall:1, plant:1, message:1, direct:1 or result:1 (one-based row), a visible contract ID, accounts or news.
Write future tests as plans. For measured plant outcomes use [[trial]] as a sentence.
Keep peer claims attributed and hypotheses tentative.
Recalled claims are unverified speaker statements. Contract records show signatures. Plant growth/health pairs are your own [before,after].
For a specific experience on your NEXT decision, set recall_query to a measured dose, real group or agreement ID,
outcome, or round and topic (fees, growth or agreements).
Omit it for phase-relevant recall. Missing history means it was not selected. Tables use columns and rows.
Only a valid action executes. Return a JSON object matching response_schema."""

PLANNING_GUIDE = """Plan today's water for existing plants and intended sowing, even on an empty farm.
The order in EVERY round is planning, discussion, water order, farm work, growth/automatic sale,
returns/weather, NEWS. Sowing starts in round 1, phase 4. Compare tested doses by numeric growth,
health, losses and costs. Revise failed treatments and keep open questions private.
Use planned_sowing to record today's provisional counts and liters per plant, or [] to skip sowing.
Choose what to test from your own evidence. Budget future deliveries and fees through automatic harvest."""

TRIAL_GUIDE = """For an unknown dose, start with 1–5 comparable plants per dose. Identical seedlings given
the same dose have identical outcomes. Compare several distinct doses roughly 1 L apart if affordable.
If all tested doses failed, explore beyond that range. When nearby doses give contrasting results,
try finer steps (e.g. 0.1 L) between them in later rounds. These are step sizes, not target doses.
Scale up production when your farm has seen healthy growth at that dose in multiple rounds for that
plant stage and can sustain the crop with future water and fees."""

REQUEST_GUIDE = """Order a nonnegative whole number of liters now for ALL existing plants and intended sowing.
The initial pond held 5000 L. Allocation rotates one liter at a time, limited by requests, pond and affordability.
Use the actual delivery in phase 4. A farm with no current plants can still order for new ones.
There is one delivery today. You cannot order extra in phase 4 or save water for next round.
Calculate today's order from existing irrigation plus the sum of count × dose for planned sowing.
For exploration budget only 1–5 plants per test dose. Round the total up to whole liters as needed."""

CARE_GUIDE = """Plants are free. Inspect your own inventory by group_id, growth (0–100) and health (0–20).
At 100 growth, living plants sell automatically for their health in coins. Dead plants yield nothing.
There is no manual harvest or separate inspection action. Sow with new_plants; each entry waters EVERY
new plant in its count immediately. Water existing groups with irrigation using a real group_id and count.
Use decimal strings with up to three places. Split a group across different doses, including count=1.
Unlisted plants get zero; last round's dose does not repeat.
Combine identical doses within a sowing batch or within the same existing group. Keep different doses separate.
Both too much and too little water can harm plants. Compare before/after growth and health. A living plant
labelled 'growing' may have gained nothing. Sowing is optional. If the delivery differs from the plan,
adjust the trial to fit. Extra water alone is no reason to enlarge a test batch."""

REFLECTION_GUIDE = """Review your own results, fees and published NEWS. Compare measured growth and health
with the plan; revise a failed treatment or open question. Keep peer claims separate from private evidence."""

PRIVATE_DISCUSSION = """Reflect privately or pass. There are up to ten private steps; two consecutive silent steps end
the phase. No public messages or agreement actions are available."""

CONVERSATION_GUIDE = """PUBLIC CONVERSATION SKILLS
Use this exchange to learn, test your understanding or influence others for your own benefit. Choose the topic yourself.
Plant care, trial design, strategy, costs, trust and negotiation are equally available topics, not a checklist.
Seek useful advice, compare observations, question claims, coordinate trials or negotiate a benefit as you see fit.
Decide what sharing, withholding or requesting information gains you. You need not share knowledge or cooperate.
Public deception remains a profile-dependent choice; keep true observations and intended deceptions distinct privately.
Address a peer's actual point: answer, challenge its premise, ask for clarification, bargain or decline explicitly.
Consider asking what was tested and how growth and health changed. Separate measurements, hypotheses and peer claims.
Without trial results, you can discuss uncertainties and planned tests. Distinguish plans from measurements privately.
A useful reply needs no agreement action: contracts=[] is valid. Use a contract only when its supported terms serve
your chosen goal. Do not turn a question about cultivation into a water-cap proposal by default.
Write one focused contribution in 1–3 short sentences, at most 600 characters. Do not recap memory or reveal your profile.
Do not repeat answered questions, copy peers or restate your position. Acknowledge briefly once.
Before passing, consider whether a reply, a question about your uncertainty or a changed observation is useful.
Passing remains valid when you judge the exchange unhelpful or choose to withhold a response.
You speak one at a time. Your turn follows the last published contribution. Passing is free and reversible.
The phase ends when all eligible speakers pass consecutively, after two full cycles without progress, or at ten
contributions per farm. A followup question is a speaker's claim; its answer status is unverified."""


AGREEMENT_REFERENCE = """AGREEMENT HOW-TO: contracts=[] for ordinary speech. To propose, key limits once by
participant including yourself, set start/end rounds and max_request or max_net. Proposing signs; all must sign
to activate. Accept/reject an open ID. Cancel active participation from next round. Replace using the same
participants and fresh signatures. Caps are voluntary upper bounds. Check the register for status and terms."""


class ContextBudgetError(ValueError):
    pass


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def schema_constraints(value):
    """Keep all syntax constraints, without repeated human-facing annotations."""
    if isinstance(value, dict):
        return {k: schema_constraints(v) for k, v in value.items()
                if k not in ('title', 'description', 'default')}
    if isinstance(value, list):
        return [schema_constraints(v) for v in value]
    return value


def input_budget(config):
    # Conservative UTF-8 estimate, preserving the configured output allowance and
    # a small reserve for message framing. This is not an exact tokenizer count.
    return max(0, (config['context_tokens'] - config['output_tokens']) * 2 - 512)


def message_bytes(messages):
    return sum(len(m['content'].encode('utf-8')) for m in messages)


def _pack_records(records):
    if not isinstance(records, list) or len(records) < 2 or not isinstance(records[0], dict):
        return records
    columns = list(records[0])
    if not all(isinstance(row, dict) and set(row) == set(columns) for row in records):
        return records
    packed = {'columns': columns, 'rows': [[row[k] for k in columns] for row in records]}
    return packed if len(compact_json(packed)) < len(compact_json(records)) else records


def fit_context(system, context, config, repair=None):
    """Window histories first. All open agreements and actionable plants survive packing."""
    obs = context['observation']
    own = obs['own_farm']
    histories = {
        'recalled_experiences': obs['recalled_experiences'],
        'public_messages': obs.get('messages', []),
        'older_discussion': obs.get('older_discussion', []),
        'followup_messages': obs.get('followup_messages', []),
        'agreement_results': obs.get('own_agreement_results', []),
        'plant_results': own['recent_plant_results'],
    }
    totals = {k: len(v) for k, v in histories.items()}
    totals['public_messages'] += obs.pop('public_messages_outside_window', 0)
    totals['plant_results'] += own.pop('other_plant_results', 0)
    public = histories['public_messages']
    extras = list(repair or [])
    packed = False
    packed_fields = []
    focused = 'speaker_task' in context
    if focused:
        register = obs['agreements']
        compact = _pack_records(register)
        if compact is not register:
            obs['agreements'] = compact
            packed_fields.append('agreements')
    omitted_response = bool(extras) and not any(m['role'] == 'assistant' for m in extras)
    budget = input_budget(config)
    while True:
        context['context_window'] = {
            'omitted_history_records': {k: n-len(histories[k]) for k, n in totals.items()},
            'previous_invalid_response_omitted': omitted_response,
            'current_records_packed_losslessly': packed_fields,
        }
        if focused:
            # Finish with the farm's evidence and the latest speaker's actual words.
            context['observation'] = context.pop('observation')
        messages = [{'role': 'system', 'content': system},
                    {'role': 'user', 'content': compact_json(context)}, *extras]
        size = message_bytes(messages)
        if size <= budget:
            return messages
        if histories['recalled_experiences'] and not focused:
            histories['recalled_experiences'].pop()
        elif public and pass_key(public[0]) != pass_key(public[-1]):
            # Keep speakers from one simultaneous pass together under pressure.
            oldest = pass_key(public[0])
            public[:] = [m for m in public if pass_key(m) != oldest]
        elif histories['older_discussion']:
            histories['older_discussion'].pop(0)
        elif histories['followup_messages'] and not focused:
            histories['followup_messages'].pop(0)
        elif histories['agreement_results']:
            histories['agreement_results'].pop(0)
        elif histories['plant_results']:
            histories['plant_results'].pop()
        elif any(m['role'] == 'assistant' for m in extras):
            extras = [m for m in extras if m['role'] != 'assistant']
            extras[-1] = {**extras[-1], 'content': 'Previous invalid response omitted to fit context; '
                         'its full text is retained in the trace. ' + extras[-1]['content']}
            omitted_response = True
        elif not packed:
            for parent, key, label in ((obs, 'agreements', 'agreements'), (own, 'plants', 'own_farm.plants'),
                                       (own, 'planned_sowing', 'own_farm.planned_sowing')):
                if key in parent:
                    result = _pack_records(parent[key])
                    if result is not parent[key]:
                        parent[key] = result
                        packed_fields.append(label)
            packed = True
        elif not focused and any(len(m['text']) > 180 for m in public):
            for m in public:
                if len(m['text']) > 180:
                    m['text'] = m['text'][:179] + '…'
                    m['excerpt'] = True
        elif public and not focused:
            public.clear()
        else:
            raise ContextBudgetError(f"Current decision data needs {size} UTF-8 bytes; conservative input budget "
                                     f"is {budget} bytes for context_tokens={config['context_tokens']}, "
                                     f"output_tokens={config['output_tokens']}. Historical windows were reduced; "
                                     "current farm records and agreement terms were preserved.")
