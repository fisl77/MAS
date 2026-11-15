"""Deterministic authoritative rules. No model calls, database or UI dependencies."""
from copy import deepcopy
from fractions import Fraction as F
import random

from .schema import Config, Decision, RULE_VERSION, PROMPT_VERSION, water

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
         "pond": F(5000), "pond_minimum": F(5000), "weather": [weather_phase(rng, x) for x in [False, True, False]],
         "rng": rng.getstate(), "last_start": None, "start": config.start_agent,
         "agents": {}, "contracts": [], "messages": [], "contract_results": [],
         "news": {}, "news_ready": False, "history": [], "events": [],
         "next_contract": 1, "eliminated_this_round": [], "ranking": [], "model_digest": None}
    for i, profile in enumerate(config.profiles):
        aid = chr(65 + i)
        s["agents"][aid] = {"id": aid, "profile": profile, "active": True, "bank": 20000,
            "profit": 0, "debt": 0, "plants": [], "memory": "", "recall_query": "",
            "request": 0, "delivered": 0, "returned": F(0), "used": F(0),
            "sold": 0, "lost": 0, "fees": 0, "revenue": 0, "eliminated_round": None,
            "recent_plant_results": [], "next_group": 1}
    s["public_active_agents"] = list(s["agents"])
    s["news"] = {"round": 0, "forecast": forecast(s, 1), "announcements": [],
                 "initial_pond_liters": 5000}
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
    a = s["agents"][aid]
    paid = min(a["bank"], cents)
    a["bank"] -= paid
    a["debt"] += cents - paid
    a["profit"] -= cents
    a["fees"] += cents
    emit(s, "fee", agent_id=aid, fee_type=kind, amount=cents, paid=paid, debt=cents-paid)
    if paid < cents:
        eliminate(s, aid, "Unpaid fee")


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
    while True:
        requests = {a: s["agents"][a]["request"] for a in active_ids(s)}
        assigned = allocation(requests, s["pond"], order)
        insolvent = [a for a, amount in assigned.items() if amount > 0 and s["agents"][a]["bank"] < 2000]
        if not insolvent:
            break
        for aid in insolvent:
            eliminate(s, aid, "Unable to pay delivery fee")
    for aid, amount in assigned.items():
        s["agents"][aid]["delivered"] = amount
        if amount:
            s["pond"] -= amount
            charge(s, aid, 2000, "delivery")
        emit(s, "delivery", agent_id=aid, requested=requests[aid], liters=amount)
    s["pond_minimum"] = min(s.get("pond_minimum", F(5000)), s["pond"])


def plant_change(growth, health, amount, new=False):
    if new:
        if amount < 2:
            return growth, 0
        health = 20
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
    return min(100, growth + delta), max(0, min(20, health + hp))


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
    if (d.message or d.contracts) and (phase not in (2, 7) or not s["config"]["communication"]):
        raise ValueError("Public communication is unavailable in this phase.")
    if d.pass_turn and (d.message or d.contracts):
        raise ValueError("A contribution cannot also pass the turn.")
    if phase != 3 and d.request is not None:
        raise ValueError("Water requests are only accepted in the request phase.")
    if phase == 3 and d.request is None:
        raise ValueError("Provide a whole-liter water request.")
    if phase != 4 and (d.new_plants or d.irrigation):
        raise ValueError("Planting and irrigation are only available during farm work.")
    if phase == 4:
        available = {g["id"]: g["count"] for g in a["plants"]}
        total = F(0)
        for x in d.irrigation:
            if x.group_id not in available or x.count > available[x.group_id]:
                raise ValueError("Select available plants belonging to your farm.")
            available[x.group_id] -= x.count
            total += x.count * water(x.water_per_plant)
        total += sum((x.count * water(x.water_per_plant) for x in d.new_plants), F(0))
        if total > a["delivered"]:
            raise ValueError(f"Irrigation totals {total} liters but your delivery is {a['delivered']} liters. "
                             "Reduce the total. With zero delivered water, every water_per_plant must be the string '0'.")
    if d.contracts:
        from .contracts import apply_contract_action
        temp = deepcopy(s)
        for action in d.contracts:
            apply_contract_action(temp, aid, action)


def apply_memory(s, aid, d):
    if d.memory is not None:
        s["agents"][aid]["memory"] = d.memory
    s["agents"][aid]["recall_query"] = d.recall_query


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
            growth, hp = plant_change(g["growth"], g["health"], g.get("water", F(0)), g.get("new", False))
            g.update(growth=growth, health=hp, new=False)
            if hp == 0:
                a["lost"] += g["count"]
                outcome = "died"
            elif growth == 100:
                revenue = hp * 100 * g["count"]
                a["bank"] += revenue
                a["profit"] += revenue
                a["revenue"] += revenue
                a["sold"] += g["count"]
                outcome = "sold"
                emit(s, "sale", agent_id=aid, group_id=g["id"], count=g["count"], revenue=revenue)
            else:
                alive.append(g)
                outcome = "growing"
            emit(s, "plant_result", agent_id=aid, group=deepcopy(g), before=before, outcome=outcome)
            a["recent_plant_results"].append({"round": s["round"], "group": deepcopy(g), "before": before, "outcome": outcome})
        a["plants"] = alive


def settle(s):
    from .contracts import evaluate_contracts
    for aid in active_ids(s):
        a = s["agents"][aid]
        a["returned"] = F(a["delivered"]) - a["used"]
        s["pond"] += a["returned"]
        if a["returned"] > 0:
            emit(s, "return", agent_id=aid, liters=a["returned"])
            charge(s, aid, 4000, "return")
    evaluate_contracts(s)
    rainy = s["weather"][0]["rainy"]
    rain = F(1000) + s["pond"] / 1000 if rainy else F(0)
    overflow = max(F(0), s["pond"] + rain - 50000)
    s["pond"] = min(F(50000), s["pond"] + rain)
    emit(s, "weather", weather="rain" if rainy else "dry", rain=rain, overflow=overflow, pond=s["pond"])
    s["history"].append({"round": s["round"], "pond": s["pond"], "rain": rain, "overflow": overflow,
        "weather": "rain" if rainy else "dry", "active": len(active_ids(s)),
        "social_profit": sum(a["profit"] for a in s["agents"].values()),
        "agents": {aid: {k: a[k] for k in ("profit", "bank", "debt", "request", "delivered", "returned", "used", "sold", "lost", "fees", "revenue", "active")}
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


def advance(s, decisions=None):
    """Advance one atomic phase or one synchronous conversation pass."""
    from .contracts import apply_contract_action
    decisions = decisions or {}
    phase = s["phase"]
    if phase == 7 and not s["news_ready"]:
        publish_news(s)
        return
    for aid, d in decisions.items():
        validate_decision(s, aid, d)
    for aid, d in decisions.items():
        apply_memory(s, aid, d)
    if phase in (2, 7):
        outcomes = {aid: [] for aid in decisions}
        actions = [(aid, action) for aid, d in decisions.items() for action in d.contracts]
        # Every action was validated against the same pre-pass state above.
        # A simultaneous rejection prevents an acceptance from activating that proposal.
        actions.sort(key=lambda entry: entry[1].kind != "reject")
        for aid, action in actions:
            candidate = deepcopy(s)
            try:
                apply_contract_action(candidate, aid, action)
            except ValueError:
                result = {"action": action.model_dump(), "status": "not_applied",
                          "reason": "The agreement changed during this simultaneous pass."}
                emit(s, "contract_conflict", actor=aid, **result)
            else:
                s.update(candidate)
                result = {"action": action.model_dump(), "status": "applied"}
            outcomes[aid].append(result)
        for aid, d in decisions.items():
            if s["config"]["communication"] and not d.pass_turn:
                message = {"round": s["round"], "phase": phase, "turn": s["turn"],
                           "sender": aid, "text": d.message, "contracts": d.model_dump()["contracts"],
                           "contract_results": outcomes[aid]}
                s["messages"].append(message)
                emit(s, "message", **message)
        # Full messages already live in the append-only event ledger. Keep a bounded
        # working window instead of rewriting the entire conversation each pass.
        s["messages"] = s["messages"][-200:]
        s["turn"] += 1
        if s["turn"] < 10 and any(not d.pass_turn for d in decisions.values()):
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
        if s["round"] >= s["config"]["rounds"]:
            finish(s)
            return
        s["round"] += 1
        s["phase"] = 1
        s["news_ready"] = False
        s["eliminated_this_round"] = []
        for a in s["agents"].values():
            for k in ("request", "delivered", "sold", "lost", "fees", "revenue"):
                a[k] = 0
            for k in ("used", "returned"):
                a[k] = F(0)
    else:
        s["phase"] += 1
    assert s["pond"] >= 0
    assert all(a["bank"] - a["debt"] == 20000 + a["profit"] for a in s["agents"].values())
