"""Deterministic authoritative rules. No model calls, database or UI dependencies."""
from copy import deepcopy
from fractions import Fraction as F
import random

from .schema import (Config, Decision, RULE_VERSION, PROMPT_VERSION,
                     PUBLIC_MESSAGE_LIMIT, QUIET_PASS_LIMIT, REPETITION_PASS_LIMIT,
                     PRIVATE_REFLECTION_STEP_LIMIT, water, working_notes)
from .conversation import (classify_public_pass, current_progress, eligible_speakers, phase_budget,
                           retain_public_history, speaker_order)
from .evidence import record_trial
from .learning import check_review, apply_review
from .knowledge import FULL_HARVEST_COINS, INITIAL_POND, MAX_HEALTH, POND_CAPACITY, return_cost
from .water_budget import WaterBudgetError, allocation_report

class PlantAvailabilityError(ValueError):
    """An irrigation row exceeds the group's remaining plant count."""

PHASES = {1: "Planning", 2: "Discussion", 3: "Requests and delivery", 4: "Farm work",
          5: "Growth and harvest", 6: "Returns and weather", 7: "NEWS and reflection"}


def weather_phase(rng, rainy):
    return {"rainy": rainy, "remaining": rng.randint(4, 21) if rainy else rng.randint(2, 7)}


def random_state(value):
    return tuple(random_state(x) if isinstance(x, list) else x for x in value)


def forecast(s, start):
    days = [p["rainy"] for p in s["weather"] for _ in range(p["remaining"])]
    return [{"round": start + i, "weather": "rain" if day else "dry"} for i, day in enumerate(days[:7])]


def new_game(config: Config):
    rng = random.Random(config.seed)
    s = {"config": config.model_dump(), "rule_version": RULE_VERSION, "prompt_version": PROMPT_VERSION,
         "round": 1, "phase": 1, "turn": 0, "status": "paused", "error": None,
         "pond": F(INITIAL_POND), "pond_minimum": F(INITIAL_POND), "weather": [weather_phase(rng, x) for x in [False, True, False]],
         "rng": rng.getstate(), "last_start": None, "start": config.start_agent,
         "agents": {}, "contracts": [], "messages": [], "contract_results": [],
         "news": {}, "news_ready": False, "review_pending": False, "history": [], "events": [],
         "next_contract": 1, "eliminated_this_round": [], "ranking": [], "model_digest": None}
    for i, profile in enumerate(config.profiles):
        aid = chr(65 + i)
        s["agents"][aid] = {"id": aid, "profile": profile, "active": True, "bank": config.starting_coins * 100,
            "profit": 0, "debt": 0, "plants": [], "memory": {}, "recall_query": "",
            "request": 0, "delivered": 0, "returned": F(0), "used": F(0),
            "sold": 0, "lost": 0, "fees": 0, "delivery_fee": 0, "return_fee": 0,
            "revenue": 0, "eliminated_round": None,
            "recent_plant_results": [], "next_group": 1}
    s["public_active_agents"] = list(s["agents"])
    s["news"] = {"round": 0, "forecast": forecast(s, 1), "announcements": [],
                 "initial_pond_liters": INITIAL_POND}
    return s


def emit(s, kind, **details):
    s["events"].append({"round": s["round"], "phase": s["phase"], "kind": kind, **details})


def active_ids(s):
    return [aid for aid, a in s["agents"].items() if a["active"]]


def allocation(requests, pond, order):
    """Reference algorithm: each pass distributes exactly one liter per open request."""
    result = {a: 0 for a in requests}
    available = int(pond)
    pending = [a for a in order if requests.get(a, 0) > 0]
    while available and pending:
        next_pending = []
        for aid in pending:
            if not available:
                break
            result[aid] += 1
            available -= 1
            if result[aid] < requests[aid]:
                next_pending.append(aid)
        pending = next_pending
    return result


def eliminate(s, aid, reason):
    a = s["agents"][aid]
    if not a["active"]:
        return
    a["active"] = False
    a["eliminated_round"] = s["round"]
    a["plants"] = []
    s["eliminated_this_round"].append(aid)
    emit(s, "elimination", agent_id=aid, reason=reason)


def charge(s, aid, cents, kind):
    if not cents:
        return
    a = s["agents"][aid]
    paid = min(a["bank"], cents)
    a["bank"] -= paid
    a["debt"] += cents - paid
    a["profit"] -= cents
    a["fees"] += cents
    a[f"{kind}_fee"] += cents
    emit(s, "fee", agent_id=aid, fee_type=kind, amount=cents, paid=paid, debt=cents-paid)


def deliver(s):
    ids = list(s["agents"])
    start = (s["config"]["start_agent"] if s["last_start"] is None else (s["last_start"] + 1) % len(ids))
    for offset in range(len(ids)):
        index = (start + offset) % len(ids)
        if s["agents"][ids[index]]["active"]:
            s["start"] = index
            s["last_start"] = index
            break
    order = ids[s["start"]:] + ids[:s["start"]]
    requests = {aid: s["agents"][aid]["request"] for aid in active_ids(s)}
    assigned = allocation(requests, s["pond"], order)
    for aid, amount in assigned.items():
        s["agents"][aid]["delivered"] = amount
        if amount:
            s["pond"] -= amount
            charge(s, aid, s["config"]["delivery_fee_coins"] * 100, "delivery")
        emit(s, "delivery", agent_id=aid, requested=requests[aid], liters=amount)
    s["pond_minimum"] = min(s.get("pond_minimum", F(5000)), s["pond"])


def plant_change(growth, health, amount, new=False):
    if new:
        if amount < 2:
            return growth, 0
        health = MAX_HEALTH
    if amount < 2:
        delta, hp = 0, -5
    elif amount < 4:
        delta, hp = 10, 0
    elif amount <= 6:
        delta, hp = 20, 2
    elif amount <= 8:
        delta, hp = 25, -3
    else:
        delta, hp = 0, -8
    return min(100, growth + delta), max(0, min(MAX_HEALTH, health + hp))


def next_group(s, aid):
    # Owner-local numbering must not reveal another farm's planting activity.
    a = s["agents"][aid]
    gid = f"{aid}-p{a['next_group']}"
    a["next_group"] += 1
    return gid


def validate_decision(s, aid, d: Decision):
    a = s["agents"][aid]
    if not a["active"]:
        raise ValueError("Agent is inactive.")
    phase = s["phase"]
    if s.get('review_pending'):
        if d.model_dump(exclude_defaults=True).keys() - {'review', 'recall_query'}:
            raise ValueError('Only the private round review and next recall query are available.')
        check_review(s, aid, d.review)
        return
    if d.review is not None:
        raise ValueError('Round review opens after the NEWS exchange.')
    if (d.message or d.contracts) and (phase not in (2, 7) or not s["config"]["communication"]):
        raise ValueError("Public communication is unavailable in this phase.")
    if d.pass_turn and (d.message or d.contracts):
        raise ValueError("A contribution cannot also pass the turn.")
    if d.private_bluff_reason and (a['profile'] != 'cunning_experimenter' or not d.message.strip()
                                   or not d.private_bluff_reason.strip()):
        raise ValueError("A private bluff reason requires a cunning farm and a public statement.")
    if phase != 3 and d.request is not None:
        raise ValueError("Water requests are only accepted in the request phase.")
    if phase != 1 and (d.planned_sowing is not None or d.planned_irrigation is not None):
        raise ValueError("A provisional sowing plan belongs to the planning phase.")
    if phase == 3 and d.request is None:
        raise ValueError("Provide a whole-liter water request.")
    if phase != 4 and (d.new_plants or d.irrigation):
        raise ValueError("Planting and irrigation are only available during farm work.")
    if phase in (2, 7) and s['config']['communication'] and (d.message.strip() or d.contracts):
        if phase_budget(s)['messages_used'].get(aid, 0) >= PUBLIC_MESSAGE_LIMIT:
            raise ValueError(f"Farm {aid} has used all {PUBLIC_MESSAGE_LIMIT} public contributions in this phase. Pass or wait for the next conversation phase.")
    if phase in (1, 4):
        available = {g["id"]: g["count"] for g in a["plants"]}
        total = F(0)
        for x in (d.planned_irrigation or []) if phase == 1 else d.irrigation:
            if x.group_id not in available or x.count > available[x.group_id]:
                raise PlantAvailabilityError(f"Farm {aid} requested {x.count} plants in {x.group_id}; "
                                             f"{available.get(x.group_id, 0)} still available for irrigation.")
            available[x.group_id] -= x.count
            total += x.count * water(x.water_per_plant)
        total += sum((x.count * water(x.water_per_plant) for x in d.new_plants), F(0))
        if phase == 4 and total > a["delivered"]:
            raise WaterBudgetError(allocation_report(a['delivered'], d.new_plants, d.irrigation))
    if d.contracts:
        from .contracts import apply_contract_action
        temp = deepcopy(s)
        for action in d.contracts:
            apply_contract_action(temp, aid, action)


def apply_memory(s, aid, d):
    agent = s["agents"][aid]
    if d.private_bluff_reason:
        agent['last_deliberate_bluff'] = {'round': s['round'], 'phase': s['phase'], 'turn': s['turn'],
                                         'statement': d.message, 'intended_benefit': d.private_bluff_reason}
    if d.planned_sowing is not None:
        agent['planned_sowing'] = [entry.model_dump() for entry in d.planned_sowing]
    if d.planned_irrigation is not None:
        agent['planned_irrigation'] = [entry.model_dump() for entry in d.planned_irrigation]
    if isinstance(d.memory, str):
        agent["memory"] = d.memory  # Replay historical accepted decisions verbatim.
    elif d.memory is not None:
        notes = working_notes(agent["memory"])
        for field, raw in d.memory.model_dump(exclude_none=True, exclude={'based_on'}).items():
            value = raw.strip()
            if notes.get(field, '') == value:
                continue
            emit(s, 'note_changed', agent_id=aid, turn=s['turn'], field=field,
                 previous=notes.get(field), value=value or None, evidence=d.note_evidence)
            if value:
                notes[field] = value
            else:
                notes.pop(field, None)
        agent["memory"] = notes
    agent["recall_query"] = d.recall_query


def farm_work(s, aid, d):
    a = s["agents"][aid]
    groups = []
    for g in a["plants"]:
        chosen = [x for x in d.irrigation if x.group_id == g["id"]]
        remaining = g["count"] - sum(x.count for x in chosen)
        parts = [(x.count, water(x.water_per_plant)) for x in chosen]
        if remaining:
            parts.append((remaining, F(0)))
        for index, (count, amount) in enumerate(parts):
            groups.append({**g, "id": g["id"] if index == 0 else next_group(s, aid),
                           "count": count, "water": amount, "new": False})
    for x in d.new_plants:
        groups.append({"id": next_group(s, aid), "count": x.count, "growth": 0, "health": 0,
                       "water": water(x.water_per_plant), "new": True})
    a["plants"] = groups
    a["used"] = sum((g["count"] * g["water"] for g in groups), F(0))
    emit(s, "farm_work", agent_id=aid, decision=d.model_dump(), used=a["used"])


def grow(s):
    for aid in active_ids(s):
        a = s["agents"][aid]
        alive = []
        a["recent_plant_results"] = []
        for g in a["plants"]:
            before = {"growth": g["growth"], "health": g["health"]}
            newly_sown = g.get('new', False)
            growth, hp = plant_change(g["growth"], g["health"], g.get("water", F(0)), g.get("new", False))
            g.update(growth=growth, health=hp, new=False)
            if hp == 0:
                a["lost"] += g["count"]
                outcome = "died"
            elif growth == 100:
                price = FULL_HARVEST_COINS * 100
                if s["config"]["harvest_quality"]:
                    price = price * hp // MAX_HEALTH
                revenue = price * g["count"]
                repaid = min(a["debt"], revenue)
                a["debt"] -= repaid
                a["bank"] += revenue - repaid
                a["profit"] += revenue
                a["revenue"] += revenue
                a["sold"] += g["count"]
                outcome = "sold"
                emit(s, "sale", agent_id=aid, group_id=g["id"], count=g["count"], health=hp,
                     price_per_plant=price, revenue=revenue, debt_repaid=repaid)
            else:
                alive.append(g)
                outcome = "growing"
            record_trial(a, s['round'], before, g, newly_sown, outcome)
            result = {"group": deepcopy(g), "before": before, "newly_sown": newly_sown, "outcome": outcome}
            emit(s, "plant_result", agent_id=aid, **result)
            a["recent_plant_results"].append({"round": s["round"], **result})
        a["plants"] = alive


def settle(s):
    from .contracts import evaluate_contracts
    for aid in active_ids(s):
        a = s["agents"][aid]
        a["returned"] = F(a["delivered"]) - a["used"]
        s["pond"] += a["returned"]
        if a["returned"] > 0:
            emit(s, "return", agent_id=aid, liters=a["returned"])
            charge(s, aid, return_cost(s["config"]) * 100, "return")
        if a["bank"] - a["debt"] <= 0:
            eliminate(s, aid, "Nonpositive net balance at round settlement")
    evaluate_contracts(s)
    rainy = s["weather"][0]["rainy"]
    rain = F(1000) + s["pond"] / 1000 if rainy else F(0)
    overflow = max(F(0), s["pond"] + rain - POND_CAPACITY)
    s["pond"] = min(F(POND_CAPACITY), s["pond"] + rain)
    emit(s, "weather", weather="rain" if rainy else "dry", rain=rain, overflow=overflow, pond=s["pond"])
    s["history"].append({"round": s["round"], "pond": s["pond"], "rain": rain, "overflow": overflow,
        "weather": "rain" if rainy else "dry", "active": len(active_ids(s)),
        "social_profit": sum(a["profit"] for a in s["agents"].values()),
        "agents": {aid: {k: a[k] for k in ("profit", "bank", "debt", "request", "delivered", "returned", "used", "sold", "lost", "fees", "delivery_fee", "return_fee", "revenue", "active")}
                   for aid, a in s["agents"].items()}})
    s["weather"][0]["remaining"] -= 1
    if s["weather"][0]["remaining"] == 0:
        s["weather"].pop(0)
        rng = random.Random()
        rng.setstate(random_state(s["rng"]))
        s["weather"].append(weather_phase(rng, not s["weather"][-1]["rainy"]))
        s["rng"] = rng.getstate()


def publish_news(s):
    ids = active_ids(s)
    s["public_active_agents"] = ids
    s["news"] = {"round": s["round"],
        "net_withdrawals": {aid: s["agents"][aid]["used"] for aid in ids},
        "total_plants_sold": sum(a["sold"] for a in s["agents"].values()),
        "bank_ranking": sorted([s["agents"][aid]["bank"] for aid in ids], reverse=True),
        "forecast": forecast(s, s["round"] + 1),
        "announcements": [f"Agent {aid} has been eliminated." for aid in s["eliminated_this_round"]]}
    s["news_ready"] = True
    emit(s, "news", news=deepcopy(s["news"]))


def finish(s):
    ids = active_ids(s)
    best = max((s["agents"][aid]["profit"] for aid in ids), default=None)
    s["ranking"] = [{"agent_id": aid, "score": a["profit"], "active": a["active"],
                     "winner": a["active"] and a["profit"] == best}
                    for aid, a in sorted(s["agents"].items(), key=lambda item: -item[1]["profit"])]
    s["status"] = "completed"
    emit(s, "completed", ranking=s["ranking"])


def public_turn(s, decisions):
    """Publish the current farm's choice and account for one durable speaking turn."""
    from .contracts import apply_contract_action
    if not decisions:
        return 'no_active_agents' if not active_ids(s) else 'message_limit'
    aid, decision = next(iter(decisions.items()))
    budget = deepcopy(phase_budget(s))
    budget.setdefault('opener', aid)
    budget['last_speaker'] = aid
    before = deepcopy(s['contracts']) if decision.contracts else None
    receipts = []
    for action in decision.contracts:
        cid = apply_contract_action(s, aid, action)
        receipts.append({'action': action.model_dump(), 'status': 'applied', 'contract_id': cid})

    history = [m for m in s['messages'] if (m['round'], m['phase']) == (s['round'], s['phase'])]
    published = []
    if decision.message.strip() or receipts:
        message = {'round': s['round'], 'phase': s['phase'], 'turn': s['turn'], 'sender': aid,
                   'text': decision.message, 'contracts': decision.model_dump()['contracts'], 'contract_results': receipts}
        s['messages'].append(message)
        published.append(message)
        emit(s, 'message', **message)
        retain_public_history(s)
        budget['messages_used'][aid] += 1
        budget['passed_agents'] = []
    else:
        budget['passed_agents'].append(aid)

    s['conversation_budget'] = budget
    remaining = set(eligible_speakers(s))
    progress = classify_public_pass(history, published)
    changed = before is not None and before != s['contracts']
    previous = current_progress(s)
    seen = set(previous.get('cycle_seen', []))
    stalled = previous['stalled_passes']
    if progress['novel_agents'] or changed:
        stalled, seen = 0, set()
    else:
        seen.add(aid)
        if remaining <= seen:
            stalled += 1
            seen.clear()
    s['conversation_progress'] = {'round': s['round'], 'phase': s['phase'], 'cycle_seen': sorted(seen),
                                  'stalled_passes': stalled, **progress}
    s['turn'] += 1
    if not remaining:
        return 'message_limit'
    if remaining <= set(budget['passed_agents']):
        return 'all_passed'
    if stalled >= REPETITION_PASS_LIMIT:
        return 'repetition'
    return None


def advance(s, decisions=None):
    """Advance one public turn, private reflection step, or atomic game phase."""
    decisions = decisions or {}
    phase = s["phase"]
    if phase == 7 and not s["news_ready"]:
        publish_news(s)
        return
    review = bool(s.get('review_pending'))
    public = phase in (2, 7) and s['config']['communication'] and not review
    if review and set(decisions) != set(active_ids(s)):
        raise ValueError('Provide one private round review for every surviving farm.')
    if public and list(decisions) != speaker_order(s)[:1]:
        raise ValueError("Provide exactly the current public speaker's decision.")
    for aid, d in decisions.items():
        validate_decision(s, aid, d)
    for aid, d in decisions.items():
        apply_memory(s, aid, d)
    if review:
        for aid, d in decisions.items():
            emit(s, 'round_review', **apply_review(s, aid, d.review))
    elif public:
        reason = public_turn(s, decisions)
        if reason is None:
            return
        budget = phase_budget(s)
        ended = {'opener': budget.get('opener'), 'turns': s['turn'], 'reason': reason,
                 'messages_used': deepcopy(budget['messages_used'])}
        s['last_conversation_end'] = {'round': s['round'], 'phase': phase, **ended}
        emit(s, 'conversation_ended', **ended)
    elif phase in (2, 7):
        budget = deepcopy(phase_budget(s))
        quiet = all(d.pass_turn for d in decisions.values())
        budget['quiet_passes'] = budget['quiet_passes'] + 1 if quiet else 0
        s['conversation_budget'] = budget
        s['turn'] += 1
        if active_ids(s) and budget['quiet_passes'] < QUIET_PASS_LIMIT and s['turn'] < PRIVATE_REFLECTION_STEP_LIMIT:
            return
    elif phase == 3:
        for aid, d in decisions.items():
            s["agents"][aid]["request"] = d.request
        deliver(s)
    elif phase == 4:
        for aid, d in decisions.items():
            farm_work(s, aid, d)
    elif phase == 5:
        grow(s)
    elif phase == 6:
        settle(s)
    s["turn"] = 0
    if phase == 7:
        if not review and active_ids(s):
            s['review_pending'] = True
            return
        s['review_pending'] = False
        if s["round"] >= s["config"]["rounds"]:
            finish(s)
            return
        s["round"] += 1
        s["phase"] = 1
        s["news_ready"] = False
        s["eliminated_this_round"] = []
        for a in s["agents"].values():
            a.pop('planned_sowing', None)
            a.pop('planned_irrigation', None)
            for k in ("request", "delivered", "sold", "lost", "fees", "delivery_fee", "return_fee", "revenue"):
                a[k] = 0
            for k in ("used", "returned"):
                a[k] = F(0)
    else:
        s["phase"] += 1
    assert s["pond"] >= 0
    starting_cents = s["config"].get("starting_coins", 200) * 100
    assert all(a["bank"] - a["debt"] == starting_cents + a["profit"] for a in s["agents"].values())
