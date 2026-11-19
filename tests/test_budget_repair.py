import asyncio
from copy import deepcopy
from fractions import Fraction as F
import itertools
import json
import re

import pytest

from farm.agents import model_decision, TechnicalError
from farm.budget_repair import FarmBudgetDraft
from farm.context import input_budget, message_bytes
from farm.engine import new_game, validate_decision
from farm.schema import Config, Decision
from farm.store import Store
from farm.views import observation


def scenario():
    s = new_game(Config()); s['phase'] = 4
    a = s['agents']['A']; a['delivered'] = 5
    a['memory'] = 'Existing measured notes.'
    a['plants'] = [{'id': f'A-p{i}', 'count': 1, 'growth': 10, 'health': 20,
                    'water': F(2), 'new': False} for i in range(3)]
    proposal = Decision(memory={'insight': 'Unexecuted claim: I watered everything.'},
                        new_plants=[{'count':1,'water_per_plant':d} for d in ('2','3')],
                        irrigation=[{'group_id':f'A-p{i}','count':1,'water_per_plant':d}
                                    for i,d in enumerate(('2','2','3'))])
    return s, proposal


def test_every_affordable_keep_order_preserves_water_and_inventory():
    s, proposed = scenario(); before = deepcopy(s)
    for order in itertools.permutations(['n0','n1','i0','i1','i2']):
        draft = FarmBudgetDraft(s,'A',proposed)
        for key in order:
            if key in draft.keepable():
                assert draft.read_selection({'keep_id':key}) == {'keep_id':key}
                row=draft.pending[key]
                draft.commit(key,row['count'],row['water_per_plant'])
            else:
                with pytest.raises(ValueError):draft.read_selection({'keep_id':key})
            assert draft.remaining >= 0
        result = draft.decision(); validate_decision(s,'A',result)
        assert sum(x.count*F(x.water_per_plant) for x in result.new_plants+result.irrigation) <= 5
        assert result.memory is None
    assert s==before


def test_revised_count_and_dose_are_chosen_in_separate_bounded_steps():
    s,_=scenario();proposed=Decision(new_plants=[{'count':1000,'water_per_plant':'2'}])
    draft=FarmBudgetDraft(s,'A',proposed)
    assert not draft.keepable()
    assert draft.read_selection({'revise_id':'n0'})
    assert draft.read_count('n0',{'count':2})=={'count':2}
    pattern=draft.dose_schema(2)['oneOf'][0]['properties']['water_per_plant']['pattern']
    assert re.fullmatch(pattern,'2.5') and not re.fullmatch(pattern,'2.501')
    draft.read_dose(2,{'water_per_plant':'2.5'})
    draft.commit('n0',2,'2.5')
    assert draft.remaining==0 and not draft.pending
    validate_decision(s,'A',draft.decision())


def test_exact_fractional_remaining_budget_and_failed_commit_are_atomic():
    s,_=scenario();s['agents']['A']['delivered']=1
    proposed=Decision(new_plants=[{'count':3,'water_per_plant':'0.333'},
                                 {'count':1,'water_per_plant':'0.002'}])
    draft=FarmBudgetDraft(s,'A',proposed)
    draft.commit('n0',3,'0.333')
    assert draft.remaining==F(1,1000)
    before=deepcopy(draft.__dict__)
    with pytest.raises(ValueError):draft.commit('n1',1,'0.002')
    assert draft.__dict__==before
    assert draft.read_dose(1,{'water_per_plant':'0.001'})
    draft.commit('n1',1,'0.001')
    assert draft.remaining==0


def test_shared_group_counts_are_reduced_only_for_explicit_selected_allocations():
    s,_=scenario();s['agents']['A']['plants'][0]['count']=4
    proposed=Decision(irrigation=[{'group_id':'A-p0','count':2,'water_per_plant':d} for d in ('3','2')])
    draft=FarmBudgetDraft(s,'A',proposed)
    draft.commit('i0',2,'1')
    assert draft.group_counts['A-p0']==2 and draft.remaining==3
    assert 'i1' not in draft.keepable()
    draft.commit('i1',1,'3')
    assert draft.group_counts['A-p0']==1 and draft.remaining==0
    validate_decision(s,'A',draft.decision())


@pytest.mark.parametrize('kind',['keep_id','revise_id'])
def test_unknown_ids_and_non_string_ids_are_rejected(kind):
    s, proposed=scenario();draft=FarmBudgetDraft(s,'A',proposed)
    for bad in ('foreign', [], None, 1):
        with pytest.raises(ValueError):draft.read_selection({kind:bad})


def fake_client(monkeypatch, responses, requests):
    class Response:
        def __init__(self,body):self.body=body
        def raise_for_status(self):pass
        def json(self):return {'message':{'content':json.dumps(self.body)},'done_reason':'stop'}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,json):
            requests.append(json)
            return Response(responses[min(len(requests)-1,len(responses)-1)])
    monkeypatch.setattr('farm.agents.httpx.AsyncClient',Client)


@pytest.mark.parametrize('choices,expected',[([{'keep_id':'i0'},{'keep_id':'n1'},{'finish':True}],(1,1,5)),
                                         ([{'finish':True}],(0,0,0))])
def test_complete_plan_contains_only_explicit_model_choices(tmp_path,monkeypatch,choices,expected):
    s, proposed=scenario();before=deepcopy(s);requests=[]
    fake_client(monkeypatch,[proposed.model_dump(include={'new_plants','irrigation','memory'}),*choices],requests)
    async def run():
        store=Store(tmp_path/'choices.sqlite3');rid=store.create(s)
        result=await model_decision(s,'A',observation(s,'A'),store,rid,'1:4:0:A')
        validate_decision(s,'A',result)
        assert (len(result.new_plants),len(result.irrigation),
                sum(x.count*F(x.water_per_plant) for x in result.new_plants+result.irrigation))==expected
        assert result.memory is None and s==before
        assert store.decision(rid,'1:4:0:A') is None
        calls=store.calls(rid)
        assert len(calls)==1+len(choices)
        assert all(c['controller_stage']=='farm_budget_planning' for c in calls[1:])
        assert all(c['repair_of_action']=='1:4:0:A' for c in calls[1:])
        assert all(message_bytes(r['messages'])<=input_budget(s['config']) for r in requests)
    asyncio.run(run())


@pytest.mark.parametrize('cancel',[False,True])
def test_model_can_reduce_count_change_dose_or_cancel_without_automatic_scaling(tmp_path,monkeypatch,cancel):
    s,_=scenario();before=deepcopy(s);requests=[]
    proposed={'new_plants':[{'count':10,'water_per_plant':'3'}],'irrigation':[]}
    choices=[{'revise_id':'n0'},{'count':2},{'cancel':True} if cancel else {'water_per_plant':'2.5'}]
    fake_client(monkeypatch,[proposed,*choices],requests)
    async def run():
        store=Store(tmp_path/'revise.sqlite3');rid=store.create(s)
        result=await model_decision(s,'A',observation(s,'A'),store,rid,'1:4:0:A')
        if cancel:assert not result.new_plants
        else:assert result.new_plants[0].count==2 and result.new_plants[0].water_per_plant=='2.5'
        assert s==before
        validate_decision(s,'A',result)
        details=json.loads(requests[-1]['messages'][1]['content'])['budget_planning_tool']
        assert details['current_count']==2 and details['remaining_liters']=='5'
    asyncio.run(run())


def test_invalid_tool_choices_never_execute_earlier_draft_steps(tmp_path,monkeypatch):
    s, proposed=scenario();before=deepcopy(s);requests=[]
    fake_client(monkeypatch,[proposed.model_dump(include={'new_plants','irrigation'}),
                             {'keep_id':'n1'},{'keep_id':'i2'}],requests)
    async def run():
        store=Store(tmp_path/'invalid.sqlite3');rid=store.create(s)
        with pytest.raises(TechnicalError,match='Invalid budget-planning choice'):
            await model_decision(s,'A',observation(s,'A'),store,rid,'1:4:0:A')
        assert s==before and store.decision(rid,'1:4:0:A') is None
        assert len(store.calls(rid))==5
    asyncio.run(run())


def test_spending_budget_leaves_existing_plants_at_the_normal_implicit_zero(tmp_path,monkeypatch):
    s, proposed=scenario();before=deepcopy(s);requests=[]
    fake_client(monkeypatch,[proposed.model_dump(include={'new_plants','irrigation'}),
                             {'keep_id':'n0'},{'keep_id':'n1'}],requests)
    async def run():
        store=Store(tmp_path/'implicit-zero.sqlite3');rid=store.create(s)
        result=await model_decision(s,'A',observation(s,'A'),store,rid,'1:4:0:A')
        assert len(result.new_plants)==2 and not result.irrigation
        assert len(store.calls(rid))==3
        validate_decision(s,'A',result)
        assert s==before
    asyncio.run(run())
