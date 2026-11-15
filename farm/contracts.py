"""Voluntary agreements. Evaluation never restricts physical actions."""
from copy import deepcopy
from .schema import water


def apply_contract_action(s, actor, action):
    from .engine import emit, active_ids
    if s["phase"] not in (2, 7) or not s["config"]["communication"]:
        raise ValueError("Contracts are unavailable in this phase.")
    earliest = s["round"] + (s["phase"] == 7)
    by_id = {c["id"]: c for c in s["contracts"]}
    if action.kind == "propose":
        participants = [x.agent_id for x in action.limits]
        if not participants or len(set(participants)) != len(participants) or actor not in participants:
            raise ValueError("List unique participants including yourself.")
        if any(a not in active_ids(s) for a in participants):
            raise ValueError("Participants must be active agents.")
        if action.start_round is None or action.end_round is None or action.start_round < earliest or action.end_round < action.start_round:
            raise ValueError("Choose a valid current or future agreement period.")
        previous = by_id.get(action.replaces) if action.replaces else None
        if action.replaces and (previous is None or previous["status"] != "active" or set(participants) != set(previous["participants"])):
            raise ValueError("A replacement must reference an active agreement with the same participants.")
        contract = {"id": f"c{s['next_contract']}", "version": previous["version"] + 1 if previous else 1,
            "participants": participants, "limits": [x.model_dump() for x in action.limits],
            "start_round": action.start_round, "end_round": action.end_round,
            "signatures": [actor], "status": "proposed", "replaces": action.replaces,
            "cancelled_from": {}, "effective_end": action.end_round, "created_round": s["round"]}
        s["next_contract"] += 1
        s["contracts"].append(contract)
    else:
        contract = by_id.get(action.contract_id)
        if contract is None or actor not in contract["participants"]:
            raise ValueError("Select an agreement in which you participate.")
        if action.kind == "accept":
            if contract["status"] != "proposed" or contract["start_round"] < earliest:
                raise ValueError("This proposal is no longer open for acceptance.")
            if actor not in contract["signatures"]:
                contract["signatures"].append(actor)
        elif action.kind == "reject":
            if contract["status"] != "proposed":
                raise ValueError("Only an open proposal can be rejected.")
            contract["status"] = "rejected"
        elif action.kind == "cancel":
            if contract["status"] != "active":
                raise ValueError("Only an active agreement can be cancelled.")
            contract["cancelled_from"][actor] = min(contract["cancelled_from"].get(actor, s["round"] + 1), s["round"] + 1)
    if contract["status"] == "proposed" and set(contract["signatures"]) == set(contract["participants"]):
        if contract["replaces"]:
            previous = by_id[contract["replaces"]]
            if previous["status"] != "active":
                raise ValueError("The agreement to replace is no longer active.")
            previous["effective_end"] = min(previous["effective_end"], contract["start_round"] - 1)
            previous["replaced_by"] = contract["id"]
        contract["status"] = "active"
        contract["accepted_round"] = s["round"]
    emit(s, "contract_action", actor=actor, action=action.model_dump(), contract=deepcopy(contract))


def evaluate_contracts(s):
    from .engine import emit
    r = s["round"]
    for c in s["contracts"]:
        if c["status"] == "proposed" and c["start_round"] <= r:
            c["status"] = "expired"
        if c["status"] != "active":
            continue
        if r > c["effective_end"]:
            c["status"] = "replaced" if c.get("replaced_by") else "expired"
            continue
        if r < c["start_round"]:
            continue
        results = {}
        for limit in c["limits"]:
            aid = limit["agent_id"]
            a = s["agents"][aid]
            if c["cancelled_from"].get(aid, r+1) <= r:
                results[aid] = {"status": "cancelled", "request_met": None, "net_met": None}
                continue
            request_met = (a["request"] <= limit["max_request"]) if limit["max_request"] is not None else None
            net_met = a["used"] <= water(limit["max_net"]) if limit["max_net"] is not None else None
            # In-round elimination is explicitly not counted as cooperation.
            status = "eliminated" if not a["active"] else ("breached" if False in (request_met, net_met) else "met")
            results[aid] = {"status": status, "request_met": request_met if a["eliminated_round"] in (None, r) else None,
                            "net_met": net_met if a["eliminated_round"] in (None, r) else None}
        statuses = [x["status"] for x in results.values()]
        group = "not_applicable" if any(x in ("cancelled", "eliminated") for x in statuses) else ("breached" if "breached" in statuses else "met")
        row = {"round": r, "contract_id": c["id"], "type": "self" if len(results) == 1 else "group",
               "individual": results, "joint": group}
        s["contract_results"].append(row)
        emit(s, "contract_evaluation", result=row)
