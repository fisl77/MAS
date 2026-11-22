import asyncio
from fractions import Fraction as F
import json

import pytest

from farm.agents import model_format, prompt_messages, model_decision, contract_action_options, scripted
from farm.contracts import apply_contract_action
from farm.engine import new_game, advance, farm_work, grow, validate_decision
from farm.evidence import seedling_trial_hint
from farm.schema import Config, Decision, ContractAction
from farm.store import Store, dumps, loads
from farm.runner import Runner
from farm.views import observation
from farm.conversation import classify_public_pass, speaker_order


def state(phase=2):
    s=new_game(Config(communication=True));s['phase']=phase;s['news_ready']=phase==7
    return s


@pytest.mark.parametrize('phase',[2,7])
def test_passing_can_be_followed_by_a_reply_before_consecutive_passes_end_phase(phase):
    s=state(phase)
    first,second=speaker_order(s)
    advance(s,{first:Decision()})
    s=loads(dumps(s))
    assert s['phase']==phase and observation(s,first)['conversation_status']['consecutive_passes']==1
    advance(s,{second:Decision(pass_turn=False,message='Can you confirm the amount?')})
    assert observation(s,first)['conversation_status']['consecutive_passes']==0
    advance(s,{first:Decision()})
    assert s['phase']==phase
    advance(s,{second:Decision()})
    assert s['last_conversation_end']['reason']=='all_passed'
    assert s['last_conversation_end']['messages_used']=={first:0,second:1}


def test_ten_messages_are_individual_budgets_not_ten_shared_passes():
    s=state()
    for i in range(10):
        advance(s,{'A':Decision(pass_turn=False,message=f'A point {i}.')})
        if i<9:
            advance(s,{'B':Decision()})
    status=observation(s,'B')['conversation_status']
    assert s['phase']==2 and status['pass_number']==20
    assert status['messages_remaining']=={'A':0,'B':10}
    assert status['eligible_agents']==['B'] and status['exhausted_agents']==['A']
    with pytest.raises(ValueError,match='used all 10'):
        validate_decision(s,'A',Decision(pass_turn=False,message='An eleventh message.'))
    for i in range(10):
        advance(s,{'B':Decision(pass_turn=False,message=f'B point {i}.')})
    assert s['phase']==3 and s['last_conversation_end']['turns']==29
    assert s['last_conversation_end']['reason']=='message_limit'
    assert s['last_conversation_end']['messages_used']=={'A':10,'B':10}


def test_contract_only_contribution_uses_one_message_but_private_notes_use_none():
    s=state()
    advance(s,{'A':Decision(memory='Private note')})
    advance(s,{'B':Decision(pass_turn=False,contracts=[
        {'kind':'propose','start_round':1,'end_round':2,'limits':[{'agent_id':'B','max_request':10}]}])})
    assert s['conversation_budget']['messages_used']=={'A':0,'B':1}
    assert s['messages'][0]['text']=='' and s['messages'][0]['sender']=='B'


def test_worker_skips_exhausted_agents_but_they_return_in_news(tmp_path,monkeypatch):
    seen=[]
    async def models():return [{'name':'test-model','digest':'fixed'}]
    async def choose(s,aid,obs,*args):
        if s['review_pending']:
            return scripted(s, aid)
        seen.append((s['phase'],s['turn'],aid))
        if s['phase']==2 and (aid=='A' or s['turn']==19):
            return Decision(pass_turn=False,message=f'I propose a limit of {s["turn"]+1} liters.')
        return Decision(request=0) if s['phase']==3 else Decision()
    monkeypatch.setattr('farm.runner.list_models',models)
    monkeypatch.setattr('farm.runner.model_decision',choose)
    async def run():
        store=Store(tmp_path/'budgets.sqlite3')
        rid=store.create(new_game(Config(controller='ollama',model='test-model',communication=True,rounds=1)))
        runner=Runner(store);runner.start(rid);await runner.task
        assert store.load(rid)['status']=='completed'
        assert len([x for x in seen if x[0]==2 and x[2]=='A'])==10
        assert len([x for x in seen if x[0]==2 and x[2]=='B'])==11
        assert {(x[1],x[2]) for x in seen if x[0]==7}=={(0,'B'),(1,'A')}
    asyncio.run(run())


def test_echo_of_a_different_speaker_is_detected_but_fresh_consent_is_allowed():
    prior=[{'sender':'A','text':'The proposed water allocation limits are too high for these farms.'}]
    result=classify_public_pass(prior,[{'sender':'B','text':prior[0]['text']}])
    assert result['repeated_agents']==['B'] and not result['novel_agents']
    result=classify_public_pass([{'sender':'A','text':'I accept c1.'}],[{'sender':'B','text':'I accept c1.'}])
    assert result['novel_agents']==['B']


def test_identical_proposals_reuse_id_and_only_add_real_signatures():
    s=state()
    terms={'kind':'propose','start_round':1,'end_round':2,'limits':[
        {'agent_id':'A','max_request':100,'max_net':'0.5'},
        {'agent_id':'B','max_request':100,'max_net':'0.50'}]}
    cid=apply_contract_action(s,'A',ContractAction(**terms))
    same={**terms,'limits':list(reversed(terms['limits']))}
    assert apply_contract_action(s,'B',ContractAction(**same))==cid
    assert len(s['contracts'])==1 and s['next_contract']==2
    assert s['contracts'][0]['status']=='active' and set(s['contracts'][0]['signatures'])=={'A','B'}
    assert apply_contract_action(s,'A',ContractAction(**terms))==cid
    assert len(s['contracts'])==1
    changed={**terms,'end_round':3}
    assert apply_contract_action(s,'A',ContractAction(**changed))!=cid


@pytest.mark.parametrize('phase,earliest',[(2,4),(7,5)])
def test_past_dates_get_current_bounds_in_schema_and_feedback(phase,earliest):
    s=state(phase);s['round']=4
    schema=model_format(s,'A')
    proposal=schema['$defs']['ContractAction']['oneOf'][0]
    assert proposal['properties']['start_round']['minimum']==earliest
    action=ContractAction(kind='propose',start_round=3,end_round=4,limits=[{'agent_id':'A','max_request':40}])
    with pytest.raises(ValueError,match=f'start_round >= {earliest}') as err:
        apply_contract_action(s,'A',action)
    assert 'Current round is 4' in str(err.value) and 'start_round=3' in str(err.value)


@pytest.mark.parametrize('kind',['accept','reject','cancel'])
def test_existing_contract_actions_require_a_real_id(kind):
    with pytest.raises(ValueError,match='requires a nonempty contract_id'):
        ContractAction(kind=kind,contract_id=None,start_round=3,end_round=3,
                       limits=[{'agent_id':'B','max_request':100}])


def test_other_farms_active_self_commitment_is_not_an_acceptance_option():
    s=state();s['round']=3
    cid=apply_contract_action(s,'B',ContractAction(kind='propose',start_round=3,end_round=4,
                             limits=[{'agent_id':'B','max_request':100}]))
    assert contract_action_options(s,'A')=={'accept':[],'reject':[],'cancel':[]}
    schema=model_format(s,'A')
    variants=schema['$defs']['ContractAction']['oneOf']
    assert [v['properties']['kind']['enum'] for v in variants]==[['propose']]
    assert set(variants[0]['required'])=={'kind','start_round','end_round','limits'}
    assert contract_action_options(s,'B')=={'accept':[],'reject':[],'cancel':[cid]}
    with pytest.raises(ValueError,match='Farm A is not a participant'):
        apply_contract_action(s,'A',ContractAction(kind='accept',contract_id=cid))


def test_acceptance_options_only_include_current_open_unsigned_own_proposals():
    s=state();s['round']=3
    cid=apply_contract_action(s,'B',ContractAction(kind='propose',start_round=3,end_round=4,
                             limits=[{'agent_id':a,'max_request':100} for a in ('A','B')]))
    assert contract_action_options(s,'A')['accept']==[cid]
    assert contract_action_options(s,'B')['accept']==[]  # proposer already signed
    variants=model_format(s,'A')['$defs']['ContractAction']['oneOf']
    accept=next(v for v in variants if v['properties']['kind']['enum']==['accept'])
    assert accept['required']==['kind','contract_id']
    assert accept['properties']['contract_id']=={'type':'string','enum':[cid]}
    assert set(accept['properties'])=={'kind','contract_id'}
    s['phase']=7
    assert contract_action_options(s,'A')['accept']==[]  # start already too early
    s['phase']=2
    apply_contract_action(s,'A',ContractAction(kind='accept',contract_id=cid))
    assert contract_action_options(s,'A')=={'accept':[],'reject':[],'cancel':[cid]}


def test_null_contract_correction_explains_unavailable_actions_without_replacing_decision(tmp_path,monkeypatch):
    requests=[]
    responses=[{'pass_turn':False,'message':'I agree with B.','contracts':[
                   {'kind':'accept','contract_id':None,'start_round':3,'end_round':3,
                    'limits':[{'agent_id':'B','max_request':100}]}]},
               {'pass_turn':True,'message':'','contracts':[]}]
    class Response:
        def __init__(self,value):self.value=value
        def raise_for_status(self):pass
        def json(self):return {'message':{'content':json.dumps(self.value)}}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,json):
            requests.append(json)
            return Response(responses[len(requests)-1])
    monkeypatch.setattr('farm.agents.httpx.AsyncClient',Client)
    async def run():
        s=state();s['round']=3
        apply_contract_action(s,'B',ContractAction(kind='propose',start_round=3,end_round=4,
                              limits=[{'agent_id':'B','max_request':100}]))
        store=Store(tmp_path/'null-contract.sqlite3');rid=store.create(s)
        result=await model_decision(s,'A',observation(s,'A'),store,rid,'3:2:0:A')
        assert result.pass_turn and not result.contracts
        assert len(store.calls(rid))==2 and store.calls(rid)[0]['error']
        assert store.decision(rid,'3:2:0:A') is None
    asyncio.run(run())
    feedback=requests[1]['messages'][-1]['content']
    assert 'requires a nonempty contract_id' in feedback
    assert '"accept": []' in feedback and 'never null' in feedback
    assert "another farm's self-commitment" in feedback


def test_failed_dose_remains_measured_evidence_despite_wrong_notes_and_empty_round():
    s=state(4);a=s['agents']['A'];a['delivered']=10
    farm_work(s,'A',Decision(new_plants=[{'count':10,'water_per_plant':'0.5'}]))
    grow(s)
    a['memory']='Every new plant requires 0.5 liters.'
    s['round']=2;grow(s)  # Recent results clear, lifetime evidence must survive.
    obs=observation(s,'A')
    evidence=obs['own_farm']['cultivation_evidence']
    assert evidence['new_plant_doses_with_only_deaths']==['0.5']
    assert a['cultivation_trials'][0]['plants_died']==10
    assert observation(s,'B')['own_farm']['cultivation_evidence']['new_plant_doses_with_only_deaths']==[]
    s['phase']=1
    system=prompt_messages(s,'A',obs)[0]['content']
    assert 'only caused death' in system
    assert 'CURRENT ROUND 2' in system
    assert '0.5' in dumps(loads(dumps(s)))


def test_multiple_individual_test_doses_are_executed_and_evidence_is_not_averaged():
    s=state(4);a=s['agents']['A'];a['delivered']=11
    d=Decision(new_plants=[{'count':1,'water_per_plant':x} for x in ('1','3','7')])
    validate_decision(s,'A',d);farm_work(s,'A',d);grow(s)
    e=observation(s,'A')['own_farm']['cultivation_evidence']
    assert e['new_plant_doses_with_only_deaths']==['1']
    assert e['observed_healthy_productive_doses']==['3']
    assert len(observation(s,'A')['own_farm']['recent_plant_results'])==3
    assert len(a['plants'])==2


def test_production_counts_and_repeat_groups_count_as_one_healthy_round_per_stage():
    s = state(4)
    a = s['agents']['A']
    dose = '3'
    sow = Decision(new_plants=[{'count': n, 'water_per_plant': dose} for n in (100, 2)])
    a['delivered'] = 306
    validate_decision(s, 'A', sow)
    farm_work(s, 'A', sow)
    grow(s)
    s['round'] += 1
    d = Decision(new_plants=[{'count': 1, 'water_per_plant': dose}],
                 irrigation=[{'group_id': g['id'], 'count': g['count'], 'water_per_plant': dose} for g in a['plants']])
    a['delivered'] = 309
    validate_decision(s, 'A', d)
    farm_work(s, 'A', d)
    grow(s)
    ledger = {row['kind']: row for row in a['cultivation_trials']}
    assert ledger['new_plants']['plants_observed'] == 103
    assert ledger['new_plants']['healthy_rounds_min'] == 2
    assert ledger['existing_plants']['plants_observed'] == 102
    assert ledger['existing_plants']['healthy_rounds_min'] == 1
    for phase in (1, 3, 4):
        s['phase'] = phase
        measured = observation(s, 'A')['own_farm']['cultivation_evidence']
        assert measured['new_plants']['rows'] == [['3', [10, 10], [20, 20], 2]]
        assert measured['existing_plants']['rows'] == [['3', [10, 10], [20, 20], 1]]
        assert 'new_plants' not in observation(s, 'B')['own_farm']['cultivation_evidence']
    s['phase'] = 2
    assert 'new_plants' not in observation(s, 'A')['own_farm']['cultivation_evidence']


def test_legacy_batch_size_does_not_inflate_healthy_rounds():
    s = state(4)
    a = s['agents']['A']
    sow = Decision(new_plants=[{'count': 100, 'water_per_plant': '3'}])
    farm_work(s, 'A', sow)
    grow(s)
    row = a['cultivation_trials'][0]
    del row['last_healthy_round'], row['healthy_rounds_min']
    row['first_round'], row['last_round'] = 1, 4
    s['round'] = 4
    assert observation(s, 'A')['own_farm']['cultivation_evidence']['new_plants']['rows'][0][-1] == 1
    for current_round, expected in ((4, 1), (5, 2)):
        s['round'] = current_round
        farm_work(s, 'A', sow)
        grow(s)
        assert row['healthy_rounds_min'] == expected


def test_private_trial_plan_carries_exact_water_forward_and_expires_after_one_round():
    s = state(1)
    batches = [{'count': 3, 'water_per_plant': '1.1'}, {'count': 1, 'water_per_plant': '2.25'}]
    advance(s, {'A': Decision(planned_sowing=batches)})
    assert s['agents']['A']['plants'] == []
    assert 'planned_sowing' not in observation(s, 'A')['own_farm']
    advance(s, {'A': Decision()})
    advance(s, {'B': Decision()})
    for phase in (3, 4):
        assert s['phase'] == phase
        own = observation(s, 'A')['own_farm']
        assert own['planned_sowing'] == batches and own['planned_sowing_liters'] == '5.55'
        if phase == 3:
            assert own['whole_liters_for_planned_sowing_alone'] == 6
        assert 'planned_sowing' not in observation(s, 'B')['own_farm']
        advance(s, {'A': Decision(request=6) if phase == 3 else Decision()})
    assert s['agents']['A']['plants'] == []
    while s['round'] == 1:
        if s['review_pending']:
            decisions = {aid: scripted(s, aid) for aid in s['agents']}
        else:
            decisions = {speaker_order(s)[0]: Decision()} if s['phase']==7 and s['news_ready'] else {}
        advance(s, decisions)
    assert 'planned_sowing' not in s['agents']['A']


def test_measured_seedling_outcomes_drive_coarse_then_fine_suggestions():
    s = state(4)
    def measure(round_number, doses):
        s['round'] = round_number
        farm_work(s, 'A', Decision(new_plants=[{'count': 1, 'water_per_plant': d} for d in doses]))
        grow(s)
    measure(1, ['0', '0.2', '0.3', '0.5'])
    assert '1, 2, 3 L per plant (6 L total)' in seedling_trial_hint(s['agents']['A'])
    measure(2, ['1', '2', '3'])
    assert '1.4, 1.5, 1.6 L per plant (4.5 L total)' in seedling_trial_hint(s['agents']['A'])
    assert seedling_trial_hint(s['agents']['B']) is None


def test_order_estimate_adds_existing_irrigation_before_rounding():
    s = state(3)
    a = s['agents']['A']
    a['planned_sowing'] = [{'count': 3, 'water_per_plant': '1.5'}]
    a['plants'] = [{'id': 'A-p1', 'count': 1, 'water': F(3, 2), 'health': 20, 'growth': 10}]
    own = observation(s, 'A')['own_farm']
    assert own['planned_sowing_liters'] == '4.5'
    assert own['whole_liters_for_planned_sowing_alone'] == 5
    assert own['whole_liters_if_also_repeating_last_irrigation'] == 6


def test_claims_in_public_context_are_labelled_and_do_not_enter_evidence():
    s=state();s['messages']=[{'round':1,'phase':2,'turn':0,'sender':'B','text':'Each plant requires 0.5 liters.','contracts':[]}]
    context=json.loads(prompt_messages(s,'A',observation(s,'A'))[1]['content'])
    assert context['observation']['messages'][0]['source_type']=='unverified_peer_claim'
    assert context['observation']['own_farm']['recent_plant_results']==[]
    assert 'cultivation_evidence' not in context['observation']['own_farm']
    assert not context['observation']['recalled_experiences']
    assert 'source_type' not in s['messages'][0]  # Authoritative ledger remains unchanged.


def test_invalid_old_date_is_corrected_with_explicit_current_round_feedback(tmp_path,monkeypatch):
    bad={'pass_turn':False,'contracts':[{'kind':'propose','start_round':3,'end_round':4,
                                      'limits':[{'agent_id':'A','max_request':40}]}]}
    good=json.loads(json.dumps(bad))
    action=good['contracts'][0]
    del action['start_round'], action['end_round']
    action.update(start_delay=0,additional_rounds=1)
    bodies=iter([bad,good]);requests=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'message':{'content':json.dumps(next(bodies))}}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):requests.append(kwargs['json']);return Response()
    monkeypatch.setattr('farm.agents.httpx.AsyncClient',Client)
    async def run():
        s=state();s['round']=4;store=Store(tmp_path/'dates.sqlite3');rid=store.create(s)
        decision=await model_decision(s,'A',observation(s,'A'),store,rid,'4:2:0:A')
        assert (decision.contracts[0].start_round, decision.contracts[0].end_round)==(4,5)
        assert len(store.calls(rid))==2
        feedback=requests[1]['messages'][-1]['content']
        assert 'start_round >= 4' in feedback and 'start_round=3' in feedback
        assert 'CURRENT round is 4' in feedback
    asyncio.run(run())
