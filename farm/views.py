"""Allowlist-based agent observations; never remove secrets from a full state dump."""
from copy import deepcopy


def observation(s, aid, recalled=None):
    a = s["agents"][aid]
    own = {k: deepcopy(a[k]) for k in ("id", "profile", "bank", "profit", "debt", "plants",
           "request", "delivered", "returned", "used", "sold", "lost", "fees", "revenue", "memory", "recent_plant_results")}
    value = {"round": s["round"], "phase": s["phase"], "conversation_turn": s["turn"],
             "own_farm": own, "news": deepcopy(s["news"]),
             "known_initial_pond_liters": 5000, "active_agents": list(s.get("public_active_agents", s["agents"])),
             "recalled_observations": recalled or []}
    if s["config"]["communication"]:
        # Only completed passes enter this state. Current-round requests are never exposed.
        value["messages"] = deepcopy(s["messages"][-30:])
        value["agreements"] = [{k: deepcopy(c[k]) for k in ("id", "version", "participants", "limits",
            "start_round", "end_round", "status", "signatures", "cancelled_from", "effective_end")}
            for c in s["contracts"] if c["status"] in ("active", "proposed")]
        value["own_agreement_results"] = [{"round": x["round"], "contract_id": x["contract_id"],
            "own_result": deepcopy(x["individual"][aid])} for x in s["contract_results"][-30:] if aid in x["individual"]]
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
