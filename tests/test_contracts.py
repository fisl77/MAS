from fractions import Fraction
import pytest

from farm.contracts import apply_contract_action, evaluate_contracts
from farm.engine import new_game, advance
from farm.schema import Config, ContractAction, Decision
from farm.views import metrics, observation


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


def test_signed_limit_does_not_block_delivery_or_add_breach_fees():
    s=state();cid=propose(s);action(s,'B',kind='accept',contract_id=cid)
    s['phase']=3
    advance(s,{'A':Decision(request=250),'B':Decision(request=0),'C':Decision(request=0)})
    a=s['agents']['A']
    assert a['request']==250 and a['delivered']==250
    advance(s,{'A':Decision(new_plants=[{'count':50,'water_per_plant':'5'}]),
               'B':Decision(),'C':Decision()})
    advance(s)  # Growth
    advance(s)  # Returns and agreement evaluation
    assert a['fees']==2000 and a['bank']==48000 and a['profit']==-2000
    assert s['contract_results'][-1]['individual']['A']['status']=='breached'


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


def test_rejection_is_visible_before_next_speaker_decides():
    s=state();cid=propose(s)
    reject=Decision(pass_turn=False,contracts=[{'kind':'reject','contract_id':cid}])
    accept=Decision(pass_turn=False,contracts=[{'kind':'accept','contract_id':cid}])
    with pytest.raises(ValueError, match='current public speaker'):
        advance(s,{'A':reject,'B':accept})
    assert s['turn']==0 and s['contracts'][0]['status']=='proposed'
    advance(s,{'A':reject})
    assert not observation(s,'B')['agreements']
    with pytest.raises(ValueError, match='no longer open'):
        advance(s,{'B':accept})
    assert s['turn']==1 and len(s['messages'])==1


def test_sequential_signatures_activate_same_proposal():
    s=state();cid=propose(s,participants=('A','B','C'))
    advance(s,{'A':Decision()})
    for aid in ('B','C'):
        advance(s,{aid:Decision(pass_turn=False,contracts=[{'kind':'accept','contract_id':cid}])})
    assert s['contracts'][0]['status']=='active'
    assert set(s['contracts'][0]['signatures'])=={'A','B','C'}


def test_private_steps_and_public_turns_have_separate_budgets():
    for communication in (False,True):
        s=state();s['config']['communication']=communication
        for i in range(30 if communication else 10):
            assert s['phase']==2 and s['turn']==i
            actors = ['ABC'[i%3]] if communication else list(s['agents'])
            advance(s,{a:Decision(pass_turn=False,message=f'I propose a cap of {100+i} liters.' if communication else '',
                                  memory='Private note') for a in actors})
        assert s['phase']==3 and len(s['messages'])==(30 if communication else 0)
        assert all(x['text']!='Private note' for x in s['messages'])
        s=state();s['config']['communication']=communication
        actors = [['A'], ['B'], ['C']] if communication else [list(s['agents'])]*2
        for group in actors:
            assert s['phase']==2
            advance(s,{a:Decision() for a in group})
        assert s['phase']==3
