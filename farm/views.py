"""Allowlist-based agent observations; never remove secrets from a full state dump."""
from copy import deepcopy
from itertools import takewhile
from math import ceil
import re
from .schema import PUBLIC_MESSAGE_LIMIT, REPETITION_PASS_LIMIT, working_notes
from .water_budget import liters_text
from .conversation import current_progress, phase_budget, public_discussion, speaker_order, turn_messages
from .evidence import cultivation_evidence
from .experience import recent_changes
from .knowledge import INITIAL_POND, agent_knowledge, return_cost
from .learning import learning_context, order_choices, own_caps, plan_amounts, review_facts, water_quote
from .memory import note_provenance


def conversation_status(s, aid=None):
    public_active = list(s.get("public_active_agents", s["agents"]))
    phase_open = s.get("status") != "completed" and s["config"]["communication"] and not s.get('review_pending') and (s["phase"] == 2 or (s["phase"] == 7 and s["news_ready"]))
    budget = phase_budget(s)
    used = {a: budget['messages_used'].get(a, 0) for a in public_active}
    remaining = {a: max(0, PUBLIC_MESSAGE_LIMIT-used[a]) for a in public_active}
    eligible = speaker_order(s) if phase_open else []
    return {"phase_open": phase_open, "pass_number": s["turn"]+1 if phase_open else None,
            "message_limit_per_agent": PUBLIC_MESSAGE_LIMIT,
            "messages_used": used, "messages_remaining": remaining,
            "own_messages_remaining": remaining.get(aid),
            "can_receive_reply_before_phase_end": phase_open and any(a != aid for a in eligible),
            "next_speaker": eligible[0] if eligible else None, "eligible_agents": eligible,
            "exhausted_agents": [a for a in public_active if not remaining[a]],
            "known_eliminated_agents": [a for a in s["agents"] if a not in public_active],
            "consecutive_passes": len(budget['passed_agents']),
            "passed_since_last_contribution": list(budget['passed_agents']),
            "stalled_passes": current_progress(s)["stalled_passes"],
            "stalled_pass_limit": REPETITION_PASS_LIMIT,
            "repeated_agents": list(current_progress(s)["repeated_agents"]),
            "passing_is_permanent": False, "passes_cost_messages": False}


def observation(s, aid, *, store=None, rid=None):
    a = s["agents"][aid]
    own = {k: deepcopy(a[k]) for k in ("id", "profile", "bank", "profit", "debt", "plants",
           "request", "delivered", "returned", "used", "sold", "lost", "fees", "revenue")}
    own["memory"] = working_notes(a["memory"])
    if own['memory']:
        saved = a.get('memory_provenance', {})
        own['memory_provenance'] = {field: deepcopy(saved.get(field) or note_provenance(field)) for field in own['memory']}
    review = bool(s.get('review_pending'))
    if a.get('learning'):
        own['learning'] = learning_context(a, s['phase'], review)
    if 'last_deliberate_bluff' in a:
        own['last_deliberate_bluff'] = deepcopy(a['last_deliberate_bluff'])
    own["recent_plant_results"] = recent_changes(a["recent_plant_results"])
    own["other_plant_results"] = len(a["recent_plant_results"]) - len(own["recent_plant_results"])
    value = {"round": s["round"], "phase": s["phase"], "conversation_turn": s["turn"],
             "own_farm": own, "news": deepcopy(s["news"]),
             "known_initial_pond_liters": INITIAL_POND, "active_agents": list(s.get("public_active_agents", s["agents"])),
             "recalled_experiences": []}
    if "harvest_quality" in s["config"]:
        value["game_rules"] = agent_knowledge(s["config"])
        own.update(net_balance=a["bank"] - a["debt"], delivery_fee=a["delivery_fee"], return_fee=a["return_fee"])
    own['cultivation_evidence'] = cultivation_evidence(a, compare_doses=s["phase"] in (1, 3, 4))
    if s["phase"] in (3, 4) and ('planned_sowing' in a or 'planned_irrigation' in a):
        plan = a.get('planned_sowing', [])
        own['planned_sowing'] = deepcopy(plan)
        sowing_liters, existing = plan_amounts(a)
        total = sowing_liters + existing
        own['planned_irrigation'] = deepcopy(a.get('planned_irrigation', []))
        own['planned_irrigation_liters'] = liters_text(existing)
        own['planned_total_liters'] = liters_text(total)
        if s['phase'] == 3:
            own['order_if_following_plan'] = water_quote(s['config'], ceil(total), total)
            if total.denominator != 1 and return_cost(s['config']):
                own['whole_order_choices'] = order_choices(s['config'], total)
            if s['history']:
                old = s['history'][-1]['agents'][aid]['request']
                if old != ceil(total):
                    own['if_repeating_last_order_in_full'] = water_quote(s['config'], old, total)
        else:
            own['actual_delivery_against_plan'] = water_quote(s['config'], a['delivered'], total)
        own['planned_sowing_liters'] = liters_text(sowing_liters)
        if s['phase'] == 3:
            own['whole_liters_for_planned_sowing_alone'] = ceil(sowing_liters)
            if a['plants'] and 'planned_irrigation' not in a:
                repeat_liters = sum(g['count'] * g['water'] for g in a['plants'])
                own['whole_liters_if_also_repeating_last_irrigation'] = ceil(sowing_liters + repeat_liters)
    if s["config"]["communication"]:
        value["conversation_status"] = conversation_status(s, aid)
        if s["phase"] != 4:
            value.update(public_discussion(s, aid))
        value["agreements"] = [{k: deepcopy(c[k]) for k in ("id", "version", "participants", "limits",
            "start_round", "end_round", "status", "signatures", "cancelled_from", "effective_end", "replaces")}
            for c in s["contracts"] if c["status"] in ("active", "proposed")]
        published_round = s["news"]["round"]
        recent = takewhile(lambda x: x["round"] >= published_round, reversed(s["contract_results"]))
        value["own_agreement_results"] = [{"round": x["round"], "contract_id": x["contract_id"],
            "own_result": deepcopy(x["individual"][aid])} for x in recent
            if x["round"] == published_round and aid in x["individual"]][::-1]
        if s['phase'] in (1, 3, 4) or review:
            caps = own_caps(s, aid)
            if caps:
                own['effective_voluntary_caps'] = caps
            for result in reversed(s['contract_results']):
                if aid in result['individual']:
                    own['last_evaluated_commitment'] = {'round': result['round'], 'contract_id': result['contract_id'],
                                                        **deepcopy(result['individual'][aid])}
                    break
    if review:
        value['private_round_records'] = review_facts(s, aid)
    if store is not None:
        public = s["config"]["communication"] and s["phase"] in (2, 7) and not review
        lookup = value
        turn_text = ''
        if s['phase'] in (1, 3, 4):
            lookup = {**value, 'messages': [], 'followup_messages': [], 'older_discussion': []}
        if public:
            latest, direct = turn_messages(s, aid)
            lookup = {**value, 'messages': latest, 'followup_messages': direct, 'older_discussion': []}
            if direct or latest:
                msg = (direct or latest)[0]
                turn_text = msg['text']
                if re.search(r'\b(?:agree\w*|promis\w*|commit\w*|deal|sign\w*|offer\w*)\b', turn_text, re.I):
                    turn_text += ' Farm ' + msg['sender']
            value['focused_recall'] = True
        value["recalled_experiences"] = store.decision_recall(rid, aid, lookup, a["recall_query"], turn_text, public)
        if a['recall_query'] and hasattr(store, 'recall_reviews'):
            archive = store.recall_reviews(rid, aid, a['recall_query'])
            if archive:
                own['private_archive'] = archive
    return value


def metrics(s):
    def rate(rows):
        evaluable = [v for v in rows if v in ("met", "breached")]
        return {"evaluated": len(evaluable), "met": evaluable.count("met"),
                "rate": evaluable.count("met") / len(evaluable) if evaluable else None}
    joint = {kind: rate([x["joint"] for x in s["contract_results"] if x["type"] == kind]) for kind in ("self", "group")}
    for kind in joint:
        joint[kind]["not_applicable"] = sum(x["type"] == kind and x["joint"] == "not_applicable" for x in s["contract_results"])
    individual = {aid: {kind: rate([x["individual"][aid]["status"] for x in s["contract_results"]
                                if x["type"] == kind and aid in x["individual"]]) for kind in ("self", "group")}
                  for aid in s["agents"]}
    covered = {x["round"] for x in s["contract_results"]}
    return {"social_profit": sum(a["profit"] for a in s["agents"].values()),
        "minimum_pond": min([s.get("pond_minimum", 5000), s["pond"]] + [x["pond"] for x in s["history"]]), "end_pond": s["pond"],
        "active_agents": sum(a["active"] for a in s["agents"].values()),
        "agreement_rates": joint, "individual_agreement_rates": individual,
        "accepted_agreements": sum("accepted_round" in c for c in s["contracts"]),
        "rounds_without_agreement": len(s["history"]) - len(covered)}
