from fractions import Fraction
import pytest

from farm.contracts import apply_contract_action, evaluate_contracts
from farm.engine import new_game, advance
from farm.schema import Config, ContractAction, Decision
from farm.views import metrics


def state():
    s=new_game(Config(communication=True,agent_count=3));s["phase"]=2
    return s


def action(s,actor,**kwargs):
    apply_contract_action(s,actor,ContractAction(**kwargs))


def propose(s,limit=100,participants=("A","B"),start=1,end=3,replaces=None):
    action(s,"A",kind="propose",start_round=start,end_round=end,replaces=replaces,
           limits=[{"agent_id":a,"max_request":limit} for a in participants])
    return s["contracts"][-1]["id"]


def test_all_sign_same_version_no_invented_signature():
    s=state();cid=propose(s)
    assert s["contracts"][0]["status"]=="proposed"
    with pytest.raises(ValueError):action(s,"C",kind="accept",contract_id=cid)
    action(s,"B",kind="accept",contract_id=cid)
    assert s["contracts"][0]["status"]=="active"
    new=propose(s,150,replaces=cid)
    assert s["contracts"][-1]["signatures"]==["A"]
    assert s["contracts"][0]["effective_end"]==3
    action(s,"B",kind="accept",contract_id=new)
    assert s["contracts"][0]["effective_end"]==0
    assert s["contracts"][-1]["version"]==2


def test_overlapping_limits_and_unfulfilled_large_request():
    s=state()
    for limit in (100,80):
        cid=propose(s,limit);action(s,"B",kind="accept",contract_id=cid)
    s["agents"]["A"].update(request=90,delivered=10,used=Fraction(10))
    evaluate_contracts(s)
    assert [x["individual"]["A"]["status"] for x in s["contract_results"]]==["met","breached"]
    assert s["agents"]["A"]["request"]==90


def test_net_limit_is_not_request_limit():
    s=state()
    action(s,"A",kind="propose",start_round=1,end_round=1,limits=[{"agent_id":"A","max_net":"10"}])
    s["agents"]["A"].update(request=500,used=Fraction(5))
    evaluate_contracts(s)
    assert s["contract_results"][0]["joint"]=="met"
    assert s["contract_results"][0]["type"]=="self"


def test_cancellation_next_round_remaining_obligations_survive():
    s=state();cid=propose(s);action(s,"B",kind="accept",contract_id=cid)
    action(s,"A",kind="cancel",contract_id=cid)
    s["agents"]["A"]["request"]=101
    evaluate_contracts(s)
    assert s["contract_results"][-1]["individual"]["A"]["status"]=="breached"
    s["round"]=2;s["agents"]["B"]["request"]=101
    evaluate_contracts(s)
    result=s["contract_results"][-1]
    assert result["individual"]["A"]["status"]=="cancelled"
    assert result["individual"]["B"]["status"]=="breached"
    assert result["joint"]=="not_applicable"


def test_elimination_does_not_imply_cooperation():
    s=state();cid=propose(s);action(s,"B",kind="accept",contract_id=cid)
    s["agents"]["A"].update(active=False,eliminated_round=1,request=500)
    evaluate_contracts(s)
    result=s["contract_results"][-1]
    assert result["joint"]=="not_applicable"
    assert result["individual"]["A"]["status"]=="eliminated"
    assert result["individual"]["A"]["request_met"] is False
    assert result["individual"]["B"]["status"]=="met"


def test_news_contracts_only_future_and_no_communication_no_actions():
    s=state();s["phase"]=7
    with pytest.raises(ValueError):propose(s)
    propose(s,start=2)
    evaluate_contracts(s)
    assert not s["contract_results"]
    s["config"]["communication"]=False
    with pytest.raises(ValueError):propose(s,start=2)


def test_missing_agreement_is_not_zero_compliance():
    s=state();evaluate_contracts(s)
    assert metrics(s)["agreement_rates"]["group"]["rate"] is None


@pytest.mark.parametrize('order', [('A','B'), ('B','A')])
def test_simultaneous_rejection_prevents_acceptance_without_blocking(order):
    s=state();cid=propose(s)
    decisions={
        'A':Decision(pass_turn=False,contracts=[{'kind':'reject','contract_id':cid}]),
        'B':Decision(pass_turn=False,contracts=[{'kind':'accept','contract_id':cid}])}
    advance(s,{aid:decisions[aid] for aid in order})
    assert s['turn']==1 and s['contracts'][0]['status']=='rejected'
    assert len(s['messages'])==2
    message=next(x for x in s['messages'] if x['sender']=='B')
    assert message['contract_results'][0]['status']=='not_applied'
    assert any(e['kind']=='contract_conflict' for e in s['events'])


def test_simultaneous_final_signatures_activate_same_proposal():
    s=state();cid=propose(s,participants=('A','B','C'))
    advance(s,{aid:Decision(pass_turn=False,contracts=[{'kind':'accept','contract_id':cid}]) for aid in ('B','C')})
    assert s['contracts'][0]['status']=='active'
    assert set(s['contracts'][0]['signatures'])=={'A','B','C'}


def test_ten_passes_and_early_silence_for_both_conditions():
    for communication in (False,True):
        s=state();s["config"]["communication"]=communication
        for i in range(10):
            assert s["phase"]==2 and s["turn"]==i
            advance(s,{a:Decision(pass_turn=False,message="Still discussing" if communication else "",memory="Private note") for a in s["agents"]})
        assert s["phase"]==3 and len(s["messages"])==(30 if communication else 0)
        assert all(x["text"]!="Private note" for x in s["messages"])
        s=state();advance(s,{a:Decision() for a in s["agents"]})
        assert s["phase"]==3
