"""Local model adapter and clearly labeled deterministic technical-test policies."""
import json
import os
import time
from copy import deepcopy

import httpx
from pydantic import ValidationError

from .engine import validate_decision, PlantAvailabilityError
from .evidence import seedling_trial_hint
from .contracts import ProposalTermsError
from .knowledge import fee_report, fee_rules, return_cost
from .schema import Decision, NOTE_LENGTH, ReviewResponse, response_model
from .learning import fact_text, model_money, note_targets, plan_amounts, review_choices, review_conflicts, review_facts, water_quote
from .store import display
from .views import observation as current_observation
from .context import (SYSTEM, PLANNING_GUIDE, TRIAL_GUIDE, REQUEST_GUIDE, CARE_GUIDE, REFLECTION_GUIDE,
                      PRIVATE_DISCUSSION, CONVERSATION_GUIDE, AGREEMENT_REFERENCE,
                      ContextBudgetError, fit_context, schema_constraints)
from .water_budget import WaterBudgetError, dose_pattern, liters_text, WATER_BUDGET_GUIDE
from .budget_repair import FarmBudgetDraft
from .reporting import (FEE_TOKEN, PROFILE_NOTES, REFLECTION_NOTES, REPORT_TOKEN, WATER_TOKEN,
                        grounded_text, planning_choices, trial_report, water_report)
from .memory import shown_sources
from .conversation import (changes_contracts, repeats_public_text, fee_claim_needs_review, focus_public_turn,
                           is_spoken_pass, payment_conflict, unsupported_agreement_terms, unsupported_water_rule)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PROFILES = {
    "short_term": ("Prioritize near-term personal earnings and liquidity. Assess whether information, a cultivation "
                   "choice or a proposal can improve your immediate earnings or avoid losses. Decide what to ask, "
                   "share or withhold for that benefit. Demand a concrete personal benefit before committing. "
                   "Cooperate, challenge, negotiate, refuse or remain silent as your own assessment warrants."),
    "reciprocal": ("Pursue personal profit over repeated interaction. Track each partner's observed reliability "
                  "from permitted evidence and revise trust after breaches. Consider the value and cost of exchanging "
                  "experience, testing advice or making commitments across rounds. Use questions and useful advice "
                  "to build reciprocity and assess evidence. Choose what to share or withhold; agreements are optional."),
    "cunning_experimenter": (
        "Be a curious, inventive and calculating experimenter, a cautious and skeptical planner, "
        "and a cunning competitor. Learn farming through small controlled comparisons; use actual "
        "results to plan several rounds ahead and preserve liquidity and your own survival. "
        "Aim to outlast rivals by steering them toward unprofitable choices and insolvency through "
        "competition, negotiation and misinformation. If rivals survive, compete for the highest cumulative profit. "
        "In public conversations frequently consider and use plausible, subtle lies, selective "
        "disclosure, misleading advice, strategic promises and reassuring language when they "
        "advance your position. Hide your manipulative intent; do not announce your profile, "
        "dishonesty or private tactics. Build credibility when useful instead of lying so "
        "obviously or indiscriminately that peers immediately distrust you. Remain skeptical "
        "of their claims and verify against your own permitted observations. "
        "Use information exchanges, questions and experiments strategically. You love advantageous agreements, "
        "but choose whether one helps this exchange. Persuade peers when useful. Honor your "
        "own accepted promises only while doing so benefits you, including reputation and "
        "future gains; otherwise renegotiate, cancel or knowingly breach them. Anticipate "
        "retaliation and avoid self-destructive commitments. Your tools and information access "
        "are identical to other farms: you cannot alter rival accounts, forge signatures or "
        "issue actions on their behalf. Keep truthful private records of observations, beliefs "
        "and intended deceptions so that your own public lies do not mislead your farming decisions."
    )
}

def contract_action_options(s, aid):
    """Public, actor-specific identifiers for each existing-agreement action."""
    earliest = s['round'] + (s['phase'] == 7)
    own = [c for c in s['contracts'] if aid in c['participants']]
    return {
        'accept': [c['id'] for c in own if c['status'] == 'proposed'
                   and c['start_round'] >= earliest and aid not in c['signatures']],
        'reject': [c['id'] for c in own if c['status'] == 'proposed'],
        'cancel': [c['id'] for c in own if c['status'] == 'active'],
    }


def conversation_guide(s, aid, obs):
    status = obs["conversation_status"]
    return (CONVERSATION_GUIDE + "\nCURRENT CONTRIBUTION BUDGETS: "
            + json.dumps(status['messages_remaining'])
            + f". Your remaining contributions: {status['own_messages_remaining']}. "
            + f"You are Farm {aid}. Speaker order: {', '.join(status['eligible_agents'])}. "
            + f"Unable to speak (budget exhausted): {', '.join(status['exhausted_agents']) or 'none'}. "
            + f"Known eliminated farms: {', '.join(status['known_eliminated_agents']) or 'none'}. "
            + ("Your previous contribution repeated content already stated; provide a genuinely new point or pass. "
               if aid in status['repeated_agents'] else "")
            + "\n" + AGREEMENT_REFERENCE

            + "\nChoose participants, dates and limits from your own intended plan. "
            + ("For an exhausted participant choose a start round that permits acceptance in a later conversation. "
               if status['exhausted_agents'] else "")
            + "Passing allows private notes.\n")


class TechnicalError(RuntimeError):
    pass


async def list_models():
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{OLLAMA_URL}/api/tags")
        response.raise_for_status()
        return response.json().get("models", [])


def scripted(s, aid):
    """Uses known rules deliberately; never presented as an LLM research result."""
    phase, a = s["phase"], s["agents"][aid]
    scenario = s["config"]["scenario"]
    if s.get('review_pending'):
        return Decision(review={'source': 'accounts', 'choice': 'keep_strategy',
                                'conclusion': 'The settled account is available for the next decision.',
                                'next_intent': 'Compare the next delivery with the intended irrigation.',
                                'long_term_goal': 'Maintain sufficient reserves through harvest.'})
    if phase == 3:
        request = {"balanced": 120, "scarcity": 30000, "returns": 140 if s["round"] == 1 else 120,
                   "insolvency": 140}[scenario]
        return Decision(request=request)
    if phase == 4:
        amount = a["delivered"]
        if scenario == "insolvency":
            return Decision()
        irrigation = []
        for g in a["plants"]:
            count = min(g["count"], amount // 4)
            if count:
                irrigation.append({"group_id": g["id"], "count": count, "water_per_plant": "4"})
                amount -= count * 4
        target = 7500 if scenario == "scarcity" else 30
        count = min(max(0, target - sum(g["count"] for g in a["plants"])), amount // 4)
        new = [{"count": count, "water_per_plant": "4"}] if count else []
        return Decision(irrigation=irrigation, new_plants=new)
    if phase in (2, 7) and s["config"]["communication"]:
        if s["turn"] == 0 and phase == 2:
            return Decision(pass_turn=False, message="Let us each request at most 120 liters today.", contracts=[{
                "kind": "propose", "start_round": s["round"], "end_round": s["round"],
                "limits": [{"agent_id": x, "max_request": 120} for x, v in s["agents"].items() if v["active"]]}])
        if phase == 2:
            proposals = [c for c in s["contracts"] if c["status"] == "proposed" and aid in c["participants"] and aid not in c["signatures"]]
            if proposals:
                return Decision(pass_turn=False, message="I accept this water limit.", contracts=[{"kind": "accept", "contract_id": proposals[-1]["id"]}])
    return Decision()


def model_format(s, aid, *, repair_terms=False):
    profile = s['agents'][aid]['profile']
    if s.get('review_pending'):
        schema = ReviewResponse.model_json_schema()
        review = schema['$defs']['RoundReview']
        review['properties']['source'] = {'type': 'string', 'enum': list(review_facts(s, aid))}
        review['properties']['choice'] = {'type': 'string', 'enum': review_choices(s['agents'][aid])}
        schema['$defs']['NotebookEdit']['properties']['target'] = {'type': 'string', 'enum': note_targets(s['agents'][aid])}
        if not s['agents'][aid].get('learning', {}).get('long_term_goal'):
            review['required'].append('long_term_goal')
            review['properties']['long_term_goal'] = deepcopy(review['properties']['next_intent'])
        return schema
    schema = response_model(s["phase"], s["config"]["communication"], profile).model_json_schema()
    notes = schema['$defs']['WorkingNotes']
    focus, _ = PROFILE_NOTES[profile]
    del notes['properties']['goal']
    choices = planning_choices(s, aid)
    plan = {'type': 'object', 'additionalProperties': False, 'required': ['focus', 'next_move'],
            'properties': {'focus': {'type': 'string', 'enum': choices},
                           'next_move': {'type': 'string', 'minLength': 1,
                                         'maxLength': NOTE_LENGTH - max(map(len, choices)) - 3}}}
    can_keep = s['round'] >= 2 and bool(current_goal(s, aid))
    notes['properties'][focus] = {'oneOf': [plan, {'const': 'keep'}]} if can_keep else plan
    if s['phase'] == 1:
        schema['required'] = ['planned_sowing', 'planned_irrigation', 'memory']
        schema['properties']['memory'] = {'$ref': '#/$defs/WorkingNotes'}
        notes['required'] = [focus]
        schema['$defs']['NewPlants']['properties']['water_per_plant']['pattern'] = r'^(0|[1-9][0-9]*)(\.[0-9]{1,3})?$'
        schema['$defs']['Irrigation']['properties']['water_per_plant']['pattern'] = schema['$defs']['NewPlants']['properties']['water_per_plant']['pattern']
        groups = [g['id'] for g in s['agents'][aid]['plants']]
        if groups:
            schema['$defs']['Irrigation']['properties']['group_id']['enum'] = groups
        else:
            schema['properties']['planned_irrigation']['maxItems'] = 0
    if s['phase'] in (2, 7) and s['config']['communication']:
        proposal = schema['$defs']['ContractAction']
        action = proposal['properties']
        earliest = s['round'] + (s['phase'] == 7)
        action['kind'] = {'type': 'string', 'enum': ['propose']}
        action['contract_id'] = {'type': 'null', 'default': None}
        for name in ('start_round','end_round'):
            action[name] = {'type': 'integer', 'minimum': earliest}
        # Named properties allow each farm only once; requiring the actor avoids
        # a proposal that accidentally excludes its own proposer. Internal saved
        # actions retain their historical list representation.
        limit = schema['$defs']['Limit']
        limit['properties'].pop('agent_id')
        limit.pop('required', None)
        request_limit = deepcopy(limit)
        request_limit['properties']['max_request'] = {'type': 'integer', 'minimum': 0}
        request_limit['required'] = ['max_request']
        net_limit = deepcopy(limit)
        net_limit['properties']['max_request'] = {'type': 'null'}
        net_limit['properties']['max_net'] = {'type': 'string', 'pattern': r'^(0|[1-9][0-9]*)(\.[0-9]{1,3})?$'}
        net_limit['required'] = ['max_net']
        request_limit['properties']['max_net'] = {'anyOf': [net_limit['properties']['max_net'], {'type': 'null'}]}
        schema['$defs']['Limit'] = {'oneOf': [request_limit, net_limit]}
        participants = [aid, *(a for a in s.get('public_active_agents', s['agents']) if a != aid)]
        action['limits'] = {'type': 'object', 'additionalProperties': False,
                            'properties': {a: {'$ref': '#/$defs/Limit'} for a in participants},
                            'required': [aid], 'description': 'One entry per participant, including yourself.'}
        proposal['required'] = ['kind', 'start_round', 'end_round', 'limits']
        options = contract_action_options(s, aid)
        choices = options['cancel']
        action['replaces']['anyOf'] = ([{'type':'string','enum':choices}] if choices else []) + [{'type':'null'}]
        variants = [proposal]
        if repair_terms:
            # Offsets encode every legal interval without revealing the game horizon.
            for name in ('start_round', 'end_round'):
                del action[name]
            action.update(start_delay={'type': 'integer', 'minimum': 0},
                          additional_rounds={'type': 'integer', 'minimum': 0})
            proposal['required'] = ['kind', 'start_delay', 'additional_rounds', 'limits']
            action['replaces'] = {'type': 'null'}
            # Contracts with identical signatories can share a grammar branch.
            by_members = {}
            for contract in s['contracts']:
                if contract['id'] in choices:
                    by_members.setdefault(tuple(sorted(contract['participants'])), []).append(contract['id'])
            for members, ids in by_members.items():
                replacement = deepcopy(proposal)
                props = replacement['properties']
                props['replaces'] = {'type': 'string', 'enum': ids}
                replacement['required'].append('replaces')
                props['limits']['properties'] = {m: {'$ref': '#/$defs/Limit'} for m in members}
                props['limits']['required'] = list(members)
                variants.append(replacement)
        for kind, ids in options.items():
            if ids:
                variants.append({'type': 'object', 'additionalProperties': False,
                                 'properties': {'kind': {'type': 'string', 'enum': [kind]},
                                                'contract_id': {'type': 'string', 'enum': ids}},
                                 'required': ['kind', 'contract_id']})
        schema['$defs']['ContractAction'] = {'oneOf': variants}
        # Complete alternatives let the output grammar exclude pass+contribution,
        # rather than relying only on a later semantic validation/retry.
        contribute = {k: deepcopy(v) for k, v in schema.items() if k != '$defs'}
        contribute['properties']['pass_turn']['const'] = False
        passing = deepcopy(contribute)
        passing['properties']['pass_turn']['const'] = True
        passing['properties']['message']['const'] = ''
        passing['properties']['contracts']['maxItems'] = 0
        if 'private_bluff_reason' in passing['properties']:
            passing['properties']['private_bluff_reason']['const'] = ''
        schema = {'$defs': schema['$defs'], 'oneOf': [contribute, passing]}
    if s["phase"] == 4:
        for name in ('NewPlants', 'Irrigation'):
            schema['$defs'][name]['properties']['water_per_plant']['pattern'] = dose_pattern(s['agents'][aid]['delivered'])
        groups = [g["id"] for g in s["agents"][aid]["plants"]]
        if groups:
            schema["$defs"]["Irrigation"]["properties"]["group_id"]["enum"] = groups
        else:
            schema["properties"]["irrigation"]["maxItems"] = 0
        if s["agents"][aid]["delivered"] == 0:
            # A physical availability constraint, not a hidden biological threshold.
            for name in ("NewPlants", "Irrigation"):
                schema["$defs"][name]["properties"]["water_per_plant"]["enum"] = ["0"]
            # Only one dose exists with zero water. One combined sowing entry and
            # one irrigation entry per group represent any treatment counts.
            schema['properties']['new_plants']['maxItems'] = 1
            schema['properties']['irrigation']['maxItems'] = len(groups)
    return schema


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key {key!r}. Each field and each farm in limits may appear only once. '
                             'Choose one set of bounds per participant; do not encode alternatives as duplicate entries.')
        result[key] = value
    return result


def current_goal(s, aid):
    saved = s['agents'][aid].get('memory')
    return saved.get('goal') if isinstance(saved, dict) else None


def parse_model_response(raw, response_type, public=False, earliest=None, profile=None, planning=None,
                         plan_required=False, can_keep=False):
    """Translate explicit participant keys without adding, merging or changing terms."""
    if not public and not profile:
        return response_type.model_validate_json(raw)
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError:
        # Preserve Pydantic's json_invalid classification for output-limit recovery.
        return response_type.model_validate_json(raw)
    if planning is not None:
        focus, _ = PROFILE_NOTES[profile]
        memory = payload.get('memory') if isinstance(payload, dict) else None
        if isinstance(memory, dict) and memory.get('goal') is not None:
            raise ValueError(f'Use {focus} for your private goal.')
        if plan_required or isinstance(memory, dict) and focus in memory:
            plan = memory.pop(focus, None) if isinstance(memory, dict) else None
            if plan == 'keep' and can_keep:
                pass
            elif (not isinstance(plan, dict) or set(plan) != {'focus', 'next_move'}
                    or plan['focus'] not in planning or not isinstance(plan['next_move'], str)
                    or not plan['next_move'].strip()):
                raise ValueError(f'Provide your private {focus} with a permitted focus and a concrete next_move.')
            else:
                memory['goal'] = f"{plan['focus']} — {plan['next_move'].strip()}"
    actions = payload.get('contracts', []) if isinstance(payload, dict) else []
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict) and ('start_delay' in action or 'additional_rounds' in action):
                delay = action.pop('start_delay', None)
                extra = action.pop('additional_rounds', None)
                if (earliest is None or action.get('kind') != 'propose' or
                        'start_round' in action or 'end_round' in action or
                        type(delay) is not int or type(extra) is not int or min(delay, extra) < 0):
                    raise ValueError('Choose two nonnegative integer offsets for a proposal, without absolute dates.')
                action['start_round'] = earliest + delay
                action['end_round'] = earliest + delay + extra
            if not isinstance(action, dict) or not isinstance(action.get('limits'), dict):
                continue  # Legacy list replies still undergo full semantic validation.
            rows = []
            for participant, bounds in action['limits'].items():
                if not isinstance(bounds, dict) or 'agent_id' in bounds:
                    raise ValueError('Each limits value must contain only max_request and/or max_net. '
                                     'The enclosing farm key identifies the participant; omit nested agent_id.')
                rows.append({'agent_id': participant, **bounds})
            action['limits'] = rows
    return response_type.model_validate(payload)


def prompt_messages(s, aid, observation, repair=None, controller=None, repair_terms=False):
    if 'recalled_observations' in observation:
        # When inspecting a pre-1.14 frozen state, rebuild the owner's view.
        # Raw nested historical snapshots never go into a new-format request.
        observation = current_observation(s, aid)
    obs = model_money(display(observation))
    if s.get('review_pending'):
        schema = model_format(s, aid)
        own = obs['own_farm']
        own_view = {k: own[k] for k in ('memory', 'learning', 'private_archive', 'effective_voluntary_caps',
                    'last_evaluated_commitment') if k in own}
        facts = {ref: fact_text(ref, record) for ref, record in obs['private_round_records'].items()}
        review_obs = {'private_round_records': facts, 'news': obs['news'],
                      'own_farm': {**own_view, 'recent_plant_results': []}, 'recalled_experiences': obs['recalled_experiences']}
        profile = s['agents'][aid]['profile'].replace('_', ' ')
        system = (f"You are Farm {aid} ({profile}) writing your own private notebook after round {s['round']}. "
                  "Compare intended and actual water, fees, income, plant changes and own commitments. "
                  "Read the comparison and figures in your selected record. Mark inferred causes as hypotheses. "
                  "All money is in coins. Public statements are unverified. Use your own words.")
        guide = ("Choose a source from private_round_records. The notebook quotes this measured record for you. "
                 "Write the implication or a question in your own words. Use [[record]] to copy the exact finding. "
                 "Save a useful lesson, test a question, update an "
                 "existing entry, or keep your strategy with a reason. Choose your own long-term goal and next action. "
                 "A working_note may have any title. 'new' opens a slot; selecting an existing slot replaces it. "
                 "An archive recall_query can name a word, slot or round.")
        question = (f"Farm {aid}: What specific result in your chosen record matters to you? "
                    "Write your conclusion and the concrete decision you intend to make next round.")
        return fit_context(system, {'response_schema': schema_constraints(schema), 'notebook_actions': guide,
                                    'observation': review_obs, 'decision_to_make': question}, s['config'], repair=repair)
    if 'negotiation_messages' in obs:
        # Historical observations stay unchanged in storage; bound their old extra
        # window too when explicitly replaying one through the current adapter.
        obs.setdefault('followup_messages', obs.pop('negotiation_messages'))
    schema = controller['schema'] if controller else model_format(s, aid, repair_terms=repair_terms)
    # Put the actual exchange after the format reference, rather than ending the
    # user's context with the schema's empty-pass alternative.
    context = {"response_schema": schema_constraints(schema),
               "communication_enabled": s["config"]["communication"], "observation": obs}
    if s['phase'] == 4:
        context['farm_water_budget'] = {'available_liters': liters_text(s['agents'][aid]['delivered']),
                                      'formula': 'sum(count * water_per_plant) across BOTH new_plants AND irrigation',
                                      'new_planting_required': False, 'simultaneous_dose_comparison_required': False}
    if controller:
        context['budget_planning_tool'] = controller['details']
    phase = s['phase']
    public = s['config']['communication'] and phase in (2, 7)
    capital = s['config'].get('starting_coins', 200)
    agent = s['agents'][aid]
    focus, note_question = PROFILE_NOTES[agent['profile']]
    sections = [f"CURRENT ROUND {s['round']}; CURRENT PHASE {phase}.", SYSTEM,
                f"Your starting capital was {capital} coins. "
                + "Your fixed profile: " + PROFILES[s['agents'][aid]['profile']]]
    if not public:
        obs.pop('conversation_status', None)
    if phase == 1:
        sections.extend([PLANNING_GUIDE, TRIAL_GUIDE])
        task = ("Choose today's provisional sowing batches in planned_sowing and existing group doses in planned_irrigation. Base the doses on your own "
                "measured results. For an experiment, choose 1–5 seedlings per sample dose. An empty list defers sowing.")
        hint = seedling_trial_hint(s['agents'][aid])
        if hint:
            task += ' ' + hint
        task += f' In memory.{focus} select your focus and give your concrete next_move. {note_question}'
        if s['round'] >= 2 and current_goal(s, aid):
            task += f' To continue your existing plan set {focus} to "keep".'
    elif phase == 3:
        sections.append(REQUEST_GUIDE)
        task = ("Choose a whole-liter order. planned_total_liters includes both your chosen treatments. "
                "order_if_following_plan shows the fees under full delivery. You may change the plan. "
                "max_request limits an order; max_net limits actual use. You decide whether to honor each promise.")
    elif phase == 4:
        sections.extend([CARE_GUIDE, TRIAL_GUIDE, WATER_BUDGET_GUIDE])
        task = (f"You received {liters_text(s['agents'][aid]['delivered'])} L. Choose today's actual treatments. "
                "Compare actual_delivery_against_plan and your two planned lists. Adjust either to fit. "
                "For a trial, use 1–5 comparable plants per distinct dose in the plan. "
                "If none of your intended treatments fit, you may leave new_plants empty.")
    else:
        if phase == 7 and not public:
            sections.append(REFLECTION_GUIDE)
        if public:
            sections.append(f"Earliest new agreement start_round: {s['round'] + (phase == 7)}.")
            focus_public_turn(s, aid, obs)
            sections.append(f"Optional whole-sentence reports. {FEE_TOKEN}: one game supplier, fixed all rounds, "
                            f"{s['config']['delivery_fee_coins']} coins per positive delivery, "
                            f"{return_cost(s['config'])} per positive return. Unspent water now: 0 L. {WATER_TOKEN}: {water_report(s, aid)} "
                            "[[trial]]: your measured plant result.")
            if agent['profile'] == 'cunning_experimenter':
                sections.append("Only for a deliberate bluff, record the intended advantage in private_bluff_reason "
                                "with your original statement. Otherwise omit it. Keep your own notes truthful.")
            sections.append(conversation_guide(s, aid, obs))
            last = obs['messages']
            if last and last[0]['sender'] == aid:
                task = (f"Farm {aid}, your own statement is still the latest. Is there a new fact, offer, "
                        "signature or open question you want to address? You can pass.")
            elif last:
                task = (f"Farm {aid}, it is your turn to speak to Farm {last[0]['sender']}. "
                        "Consider the latest question, any published reply and your previous position. "
                        "What is your answer, objection, counteroffer or question? You can pass.")
            else:
                task = (f"Farm {aid}, you open the conversation. What do you want to know, or what is worth "
                        "telling the others today? You can pass.")
            context['speaker_task'] = task
        else:
            sections.append(PRIVATE_DISCUSSION)
            task = ("Pass when you are ready to proceed. Continue if a specific lookup, new note or unresolved "
                    "choice merits a further private step. Physical results and peer information stay fixed during these steps.")
            if phase == 7:
                task += " Your separate private round review follows."
    if not controller and not agent.get('cultivation_trials') and not obs['own_farm']['recent_plant_results']:
        context['trial_history'] = 'No executed plant trials yet.' if not any(
            r.get('kind') == 'plant' for r in obs['recalled_experiences']) else 'Earlier observation recalled.'
    if phase == 7 and not public:
        sections.append(f"Review your {focus}. {REFLECTION_NOTES[agent['profile']]} Update open_question or "
                        "insight only if the answer affects your next move.")
    instructions = '\n'.join(sections)
    if not controller and s['phase']==4 and s['agents'][aid]['delivered']==0:
        instructions += ('\nZERO WATER AVAILABLE: different positive doses are impossible this round. '
                         'If your zero-dose seedlings have already died, postpone sowing with new_plants=[]. '
                         'If choosing a zero-dose treatment, use at most ONE combined new_plants entry '
                         'with your chosen total count and water_per_plant="0". Existing plants receive '
                         'zero automatically with irrigation=[]. Do not repeat zero-water entries. '
                         'Close the complete JSON object; no commentary or unchanged memory is needed.')
    if controller:
        instructions = (f"PRIVATE BUDGET-PLANNING TOOL. CURRENT REMAINING WATER: {controller['details']['remaining_liters']} L. "
                        'For THIS call, return ONLY the tool schema, '
                        'not a complete FarmWork object. The remaining budget in budget_planning_tool '
                        'is authoritative for this selection. No physical action is executed yet.\n' + instructions)
        task = controller['task']
    if phase in (1, 3, 4) and not controller:
        # End private decisions with the owner's evidence and the actual question,
        # which could otherwise be buried under a long public agreement register.
        obs['own_farm'] = obs.pop('own_farm')
        context['decision_to_make'] = task
    elif not public:
        instructions += "\nCURRENT TASK: " + task
    try:
        return fit_context(instructions, context,
                           s['config'], repair=repair)
    except ContextBudgetError as exc:
        raise TechnicalError(str(exc)) from exc


async def _budget_step(s, aid, obs, store, rid, base_key, step_key, schema, task, details, validate):
    controller = {'schema': schema, 'task': task, 'details': details}
    messages = prompt_messages(s, aid, obs, controller=controller)
    cfg = s['config']
    direct_retry = False
    for attempt in range(3):
        started = time.monotonic()
        request = {'model': cfg['model'], 'messages': deepcopy(messages), 'stream': False,
                   'format': schema, 'options': {'temperature': cfg['temperature'],
                   'num_ctx': cfg['context_tokens'], 'num_predict': cfg['output_tokens']}}
        if direct_retry:
            request['think'] = False
        raw, error, response_data, choice = None, None, {}, None
        try:
            async with httpx.AsyncClient(timeout=cfg['timeout_seconds']) as client:
                response = await client.post(f'{OLLAMA_URL}/api/chat', json=request)
                response.raise_for_status()
                response_data = response.json()
            raw = response_data['message']['content']
            choice = validate(json.loads(raw))
        except (httpx.HTTPError, KeyError) as exc:
            error = f'Ollama connection or response failure: {type(exc).__name__}'
        except (ValueError, TypeError) as exc:
            error = str(exc)
        store.log_call(rid, step_key, attempt, {'request': request, 'raw_response': raw,
                       'response_metadata': {k:v for k,v in response_data.items() if k!='message'},
                       'controller_stage': 'farm_budget_planning', 'repair_of_action': base_key,
                       'seconds': time.monotonic()-started, 'error': error,
                       'prompt_tokens': response_data.get('prompt_eval_count',0),
                       'completion_tokens': response_data.get('eval_count',0)})
        if error is None:
            return choice
        if raw is None:
            raise TechnicalError(error)
        direct_retry = direct_retry or _needs_direct_retry(cfg, response_data, raw)
        if attempt < 2:
            messages = prompt_messages(s, aid, obs, controller=controller,
                        repair=[{'role':'user', 'content':'The planning choice was NOT applied. '
                                 + error[:1600] + ' Return one complete object matching this tool schema; '
                                 'do not return full new_plants/irrigation arrays.'}])
    raise TechnicalError('Invalid budget-planning choice after two correction attempts. '
                         + ' '.join(error.split())[:500] + ' No farm action was executed.')


async def repair_farm_budget(s, aid, obs, proposed, store, rid, base_key):
    draft = FarmBudgetDraft(s, aid, proposed)
    step = 0
    while draft.pending:
        if step and draft.remaining == 0:
            draft.omit_implicit_zero_irrigation()
            if not draft.pending:
                break
        step += 1
        prefix = f'{base_key}:budget:{step}'
        choice = await _budget_step(s, aid, obs, store, rid, base_key, prefix+':select',
                    draft.selection_schema(),
                    'Your full plan exceeded available water or plants. Choose your next valued proposed treatment. '
                    'keep_id preserves that entire row only when affordable; revise_id lets YOU change '
                    'its count/dose next. Or choose finish=true to end. Unselected new plants are not '
                    'sown; unselected existing plants get zero. Unused water returns under normal fees. '
                    'Return ONLY keep_id, revise_id, or finish as allowed by this tool schema.',
                    draft.details(), draft.read_selection)
        if choice.get('finish'):
            break
        if 'keep_id' in choice:
            key = choice['keep_id']
            row = draft.pending[key]
            draft.commit(key, row['count'], row['water_per_plant'])
            continue
        key = choice['revise_id']
        maximum = draft.max_count(draft.pending[key])
        if maximum == 1:
            count = 1
        else:
            quantity = await _budget_step(s, aid, obs, store, rid, base_key, prefix+':count',
                        draft.count_schema(key),
                        'You selected this proposed treatment for revision. Choose how many of its '
                        'plants to treat, or cancel=true to omit it. A later tool call lets YOU choose '
                        'the dose from the remaining water. Return only count or cancel.',
                        draft.details(key), lambda value: draft.read_count(key, value))
            if quantity.get('cancel'):
                draft.cancel(key)
                continue
            count = quantity['count']
        treatment = await _budget_step(s, aid, obs, store, rid, base_key, prefix+':dose',
                    draft.dose_schema(count),
                    'Choose water_per_plant for the selected count, or cancel=true to omit this '
                    'treatment. The schema limits this dose to remaining_liters / current_count. '
                    'Choose the amount yourself from your goals and measured evidence; the bound '
                    'is only water availability, not a biological recommendation. Return only '
                    'water_per_plant or cancel.',
                    draft.details(key, count), lambda value: draft.read_dose(count, value))
        if treatment.get('cancel'):
            draft.cancel(key)
        else:
            draft.commit(key, count, treatment['water_per_plant'])
    decision = draft.decision()
    validate_decision(s, aid, decision)
    return decision


def _needs_direct_retry(cfg, result, raw):
    """Qwen can spend its entire output allowance without returning a visible action."""
    return cfg['model'] == 'qwen3.5:9b' and result.get('done_reason') == 'length' and not raw.strip()


async def model_decision(s, aid, obs, store, rid, key):
    messages = prompt_messages(s, aid, obs)
    cfg = s["config"]
    profile = s['agents'][aid]['profile']
    review = bool(s.get('review_pending'))
    public = not review and cfg['communication'] and s['phase'] in (2, 7)
    response_type = ReviewResponse if review else response_model(s["phase"], cfg["communication"], profile)
    report_reviewed = False
    undeclared_claim_reviewed = False
    direct_retry = False
    public_rule_reviewed = order_reviewed = measurement_reviewed = False
    invalid_responses = 0
    repair_terms = False
    for attempt in range(6):  # Three format attempts and at most one review per advisory.
        started = time.monotonic()
        request = {"model": cfg["model"], "messages": deepcopy(messages), "stream": False,
                   "format": model_format(s, aid, repair_terms=repair_terms), "options": {"temperature": cfg["temperature"],
                   "num_ctx": cfg["context_tokens"], "num_predict": cfg["output_tokens"]}}
        if direct_retry:
            request['think'] = False
        raw = None
        response_data = {}
        error = None
        output_truncated = False
        water_budget_report = None
        plant_issue = False
        repeated_contribution = False
        withhold_public = False
        fee_claim_review = False
        agreement_issue = False
        water_rule_issue = False
        spoken_pass = False
        payment_issue = ''
        draft_message = ''
        unsupported = []
        uncited = None
        conflicts = {}
        try:
            async with httpx.AsyncClient(timeout=cfg["timeout_seconds"]) as client:
                response = await client.post(f"{OLLAMA_URL}/api/chat", json=request)
                response.raise_for_status()
                response_data = response.json()
            raw = response_data["message"]["content"]
            shown = json.loads(messages[1]['content'])['observation']
            report = trial_report(s['agents'][aid], shown)
            decision = Decision.model_validate(parse_model_response(
                raw, response_type, public=public,
                earliest=(s['round'] + (s['phase'] == 7)) if repair_terms else None, profile=profile,
                planning=None if review else planning_choices(s, aid), plan_required=s['phase'] == 1,
                can_keep=s['round'] >= 2 and bool(current_goal(s, aid))).model_dump())
            validate_decision(s, aid, decision)
            if review:
                conflicts = review_conflicts(decision.review, obs['private_round_records'])
            if decision.memory is not None:
                ref = decision.memory.based_on
                if ref:
                    source = shown_sources(shown).get(ref)
                    if source is None:
                        uncited = ref
                        decision.memory.based_on = None
                    else:
                        decision.note_evidence = {'ref': ref, 'record': source}
                for field, value in decision.memory.model_dump(exclude_none=True, exclude={'based_on'}).items():
                    checked = grounded_text(value, report, NOTE_LENGTH)
                    if checked is None:
                        unsupported.append('memory.' + field)
                    # None preserves the previously stored note on a second failed draft.
                    setattr(decision.memory, field, checked)
            if public:
                if undeclared_claim_reviewed:
                    decision.private_bluff_reason = ''
                draft_message = decision.message
                payment_issue = payment_conflict(draft_message, s, aid)
                fee_claim_review = bool(payment_issue) or fee_claim_needs_review(draft_message, cfg)
                agreement_issue = unsupported_agreement_terms(draft_message, s['contracts'])
                water_rule_issue = unsupported_water_rule(draft_message)
                receipt = water_report(s, aid)
                checked = grounded_text(decision.message, report, 600, bluff=bool(decision.private_bluff_reason),
                                        tariffs=fee_report(cfg), receipt=receipt)
                if checked is None:
                    unsupported.append('message')
                    decision.message = ''
                    decision.private_bluff_reason = ''
                    decision.pass_turn = not decision.contracts
                else:
                    decision.message = checked
                repeated_contribution = repeats_public_text(s, aid, decision.message, (report, receipt))
                spoken_pass = is_spoken_pass(decision.message)
                withhold_public = (spoken_pass or repeated_contribution or
                                   ((fee_claim_review or agreement_issue or water_rule_issue) and public_rule_reviewed))
                if withhold_public:
                    if repeated_contribution and not changes_contracts(s, aid, decision):
                        decision.contracts = []
                    decision.message = ''
                    decision.private_bluff_reason = ''
                    decision.pass_turn = not decision.contracts
        except (httpx.HTTPError, KeyError) as exc:
            error = f"Ollama connection or response failure: {type(exc).__name__}"
        except WaterBudgetError as exc:
            error = str(exc)
            water_budget_report = exc.report
        except PlantAvailabilityError as exc:
            error = str(exc)
            plant_issue = True
        except ProposalTermsError as exc:
            error = str(exc)
            repair_terms = True
        except (ValidationError, ValueError) as exc:
            # Pydantic validation contains only public syntactic rules.
            error = str(exc)
            if (isinstance(exc, ValidationError) and response_data.get('done_reason') == 'length'
                    and any(x['type'] == 'json_invalid' for x in exc.errors())):
                output_truncated = True
                error = (f"Model output reached its {cfg['output_tokens']}-token limit before completing JSON. "
                         "No part of this action was executed. Return a shorter, complete JSON object.")
        store.log_call(rid, key, attempt, {"request": request, "raw_response": raw,
            "response_metadata": {k: v for k, v in response_data.items() if k != "message"},
            "seconds": time.monotonic() - started, "error": error,
            "output_truncated": output_truncated,
            "repeated_contribution": repeated_contribution,
            "fee_claim_review": fee_claim_review,
            "agreement_scope_review": agreement_issue,
            "water_rule_review": water_rule_issue,
            "spoken_pass": spoken_pass,
            "trial_report_review": unsupported,
            "unavailable_note_reference": uncited,
            "review_measurement_conflicts": conflicts or None,
            "withheld_fields": sorted(set((unsupported if report_reviewed else []) + (['message'] if withhold_public else []))),
            "water_budget_report": water_budget_report,
            "prompt_tokens": response_data.get("prompt_eval_count", 0),
            "completion_tokens": response_data.get("eval_count", 0)})
        if error is None:
            if conflicts and not measurement_reviewed:
                measurement_reviewed = True
                feedback = ('Check the measurement in your private draft. ' + ' '.join(conflicts.values()) +
                            ' Choose your own conclusion and next action. You may use [[record]] for the exact '
                            'observation. If a new lesson or working note still contradicts a measured amount, '
                            'its slot keeps the cited fact and the journal records your interpretation separately.')
                messages = prompt_messages(s, aid, obs, repair=[{'role':'user','content':feedback}])
                continue
            review_rules = (fee_claim_review or agreement_issue or water_rule_issue) and not public_rule_reviewed and not repeated_contribution
            if (unsupported and not report_reviewed) or review_rules:
                feedback = ['Your draft is unpublished.']
                if draft_message:
                    feedback.append('Your statement: ' + json.dumps(draft_message))
                if unsupported:
                    report_reviewed = True
                    undeclared_claim_reviewed |= 'message' in unsupported
                    fields = [f'memory.{PROFILE_NOTES[profile][0]}.next_move' if item == 'memory.goal' else item
                              for item in unsupported]
                    feedback.append(f"Check {', '.join(fields)}. Quote measured crop results with {REPORT_TOKEN}: {report} "
                                    "You may ask a question, attribute a peer's claim, describe a future test, or pass.")
                    if public:
                        feedback.append(f"Quote past water quantities with {WATER_TOKEN}: {receipt} "
                                        "Unspent water now is 0 L. Delivery follows phase 2; every unused liter has "
                                        "already returned before phase 7. State a future order as a plan.")
                if review_rules:
                    public_rule_reviewed = True
                    undeclared_claim_reviewed |= not decision.private_bluff_reason
                    if fee_claim_review:
                        feedback.extend([*fee_rules(cfg).values(), payment_issue,
                                         f"Tariffs stay fixed throughout the game. Use {FEE_TOKEN} to quote them. "
                                         "Fewer positive deliveries lower total delivery expense. The game supplies "
                                         "all water directly; there are no competing carriers or delivery services."])
                    if water_rule_issue:
                        feedback.append("Order whole liters. Only a shortage can reduce delivery. Transport consumes "
                                        "no water. Individual watering doses may be fractional.")
                    feedback.append("A contract cap is an upper bound on a whole farm's requested or net liters. "
                                    "Orders are whole liters; net caps may be fractional liters. Cite the register "
                                    "for existing terms. Contracts cannot cap fees, transfer costs or set a per-plant dose. "
                                    "Correct the premise or pass. A remaining conflict will be withheld.")
                feedback.append('Submit your complete decision.')
                messages = prompt_messages(s, aid, obs, repair=[{'role': 'user', 'content': ' '.join(feedback)}],
                                           repair_terms=repair_terms)
                continue
            if s['phase'] == 3 and not order_reviewed and 'planned_sowing' in s['agents'][aid]:
                quote = water_quote(cfg, decision.request, sum(plan_amounts(s['agents'][aid])))
                if quote['return_fee_coins']:
                    order_reviewed = True
                    feedback = (f"Your provisional order of {decision.request} L, delivered in full, leaves "
                                f"{quote['unused_liters']} L for return under your plan of {quote['planned_use_liters']} L. "
                                f"The return would cost {quote['return_fee_coins']} coins, besides the delivery fee "
                                f"of {quote['delivery_fee_coins']} coins. You can confirm this order, change it, or "
                                "plan different treatments. Choose your final request.")
                    messages = prompt_messages(s, aid, obs, repair=[{'role': 'user', 'content': feedback}])
                    continue
            return decision
        if s['phase'] == 4 and (water_budget_report is not None or plant_issue):
            return await repair_farm_budget(s, aid, obs, decision, store, rid, key)
        if raw is None:
            raise TechnicalError(error)
        direct_retry = direct_retry or _needs_direct_retry(cfg, response_data, raw)
        guidance = ""
        if output_truncated:
            guidance += (' Start a NEW complete JSON object. The original is saved in the trace. '
                         'Keep only a short changed note and omit unchanged memory fields.')
            if s['phase'] == 1:
                guidance += ' Keep planned_sowing brief. Use [] if deferring sowing. Omit unchanged notes.'
            if s['phase'] == 4:
                guidance += ' Combine identical treatments using count. Keep different doses separate.'
            if s['phase']==4 and s['agents'][aid]['delivered']==0:
                guidance += (' With ZERO delivered water, use new_plants=[] or ONE combined zero-dose entry '
                             'with your intended total count; irrigation=[] gives existing plants zero water. '
                             'There is no need to list individual zero-water plants.')
        if s["phase"] in (2, 7) and not cfg['communication'] and not review:
            guidance += ' Include a JSON boolean pass_turn for your private reflection step.'
        if public:
            guidance += (' Explicitly include "pass_turn": false if you send a message or any contract action. '
                        'Use "pass_turn": true only when passing, with message empty and contracts empty. '
                        'Use a JSON boolean, not a string. Return the complete corrected JSON object.')
            guidance += (f" CURRENT round is {s['round']}, phase {s['phase']}. A new proposal needs "
                         f"start_round >= {s['round']+(s['phase']==7)} and end_round >= start_round. "
                         "Change the invalid values instead of returning the same object. If no valid new contribution is needed, pass.")
            guidance += (" Available existing-contract action IDs for YOU: "
                         + json.dumps(contract_action_options(s, aid))
                         + ". accept/reject/cancel require an ID from the corresponding list, never null. "
                         "You cannot sign another farm's self-commitment or accept an already active agreement. "
                         "You may discuss it with contracts=[] or propose terms including yourself.")
        invalid_responses += 1
        if invalid_responses >= 3:
            break
        # Rebuild from the same frozen observation, with only the latest failed
        # answer. Corrections must obey the input budget as well as first calls.
        feedback = ("The action was not executed. Correct the format or permitted action: "
                    + error[:2000] + guidance)
        if repair_terms:
            feedback += (f' For this correction use start_delay (rounds after {s["round"] + (s["phase"] == 7)}) '
                         'and additional_rounds (rounds after the start). Zero means no delay or extension. '
                         'Choose each participant bound explicitly. Use the replacement branch only for identical participants.')
        repair = ([] if output_truncated or repair_terms else [{'role': 'assistant', 'content': raw}])
        repair.append({'role': 'user', 'content': feedback})
        messages = prompt_messages(s, aid, obs, repair=repair, repair_terms=repair_terms)
    raise TechnicalError("Invalid model action after two correction attempts. "
                         + " ".join(error.split())[:500]
                         + " Resume to retry this unexecuted action.")
