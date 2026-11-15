import asyncio
from copy import deepcopy
from fractions import Fraction
import json
import pytest
from pydantic import ValidationError

from fastapi.testclient import TestClient

from farm.app import create_app
from farm.agents import model_decision, TechnicalError, prompt_messages, model_format
from farm.engine import new_game
from farm.runner import Runner
from farm.schema import Config, Decision, response_model
from farm.store import Store, dumps, loads
from farm.views import observation


def test_saved_action_reused_after_interruption(tmp_path):
    async def run():
        store=Store(tmp_path/'test.sqlite3')
        s=new_game(Config(rounds=1));s['phase']=3
        rid=store.create(s)
        store.accept(rid,'1:3:0:A','A',Decision(request=0).model_dump(),observation(s,'A'))
        runner=Runner(store);runner.start(rid)
        await runner.task
        final=store.load(rid)
        assert final['status']=='completed'
        assert final['agents']['A']['delivered']==0  # not scripted policy's 120 L
        assert len([e for e in store.events(rid) if e['kind']=='delivery' and e['agent_id']=='A'])==1
        assert len([e for e in store.events(rid) if e['kind']=='fee' and e['agent_id']=='B'])==1
        store2=Store(tmp_path/'test.sqlite3')
        assert store2.load(rid)['pond']==final['pond']
    asyncio.run(run())


def test_pause_step_resume_and_owned_recall(tmp_path):
    async def run():
        store=Store(tmp_path/'test.sqlite3');rid=store.create(new_game(Config(rounds=3)))
        runner=Runner(store);runner.start(rid,one_round=True);await runner.task
        s=store.load(rid)
        assert s['round']==2 and s['phase']==1 and s['status']=='paused'
        recalled=store.recall(rid,'A')
        assert recalled and all(x['own_farm']['id']=='A' for x in recalled)
        assert store.recall('another-game','A')==[]
        runner.start(rid);await runner.task
        assert store.load(rid)['status']=='completed'
        assert len([x for x in store.events(rid) if x['kind']=='delivery'])==6
    asyncio.run(run())


def test_restart_changes_running_to_interrupted(tmp_path):
    path=tmp_path/'test.sqlite3';store=Store(path);s=new_game(Config());s['status']='running'
    rid=store.create(s)
    assert Store(path).load(rid)['status']=='interrupted'


def test_restart_reconciles_calls_written_by_older_worker(tmp_path):
    path=tmp_path/'legacy.sqlite3';store=Store(path)
    rid=store.create(new_game(Config()))
    body={'error':None,'seconds':2.5,'prompt_tokens':10,'completion_tokens':5}
    store.log_call(rid,'first',0,body)
    with store.connection() as db:
        db.execute('INSERT INTO calls(run_id,action_id,attempt,body) VALUES(?,?,?,?)',
                   (rid,'second',1,dumps(body)))
    resumed=Store(path)
    assert resumed.call_stats(rid)=={'calls':2,'corrections':1,'errors':0,'seconds':5,'tokens':30}


def test_simultaneous_decisions_and_no_request_leak(tmp_path,monkeypatch):
    seen=[]
    async def models():return [{'name':'test-model','digest':'fixed'}]
    async def decide(s,aid,obs,*args):
        seen.append((aid,deepcopy(obs)))
        if s['phase']==3:return Decision(request=19 if aid=='A' else 0)
        if s['phase']==2 and s['turn']==0:return Decision(pass_turn=False,message=f'Hello from {aid}')
        return Decision()
    monkeypatch.setattr('farm.runner.list_models',models)
    monkeypatch.setattr('farm.runner.model_decision',decide)
    async def run():
        store=Store(tmp_path/'test.sqlite3')
        rid=store.create(new_game(Config(controller='ollama',model='test-model',communication=True,rounds=1)))
        runner=Runner(store);runner.start(rid);await runner.task
        assert store.load(rid)['status']=='completed'
    asyncio.run(run())
    first=[o for a,o in seen if o['phase']==2 and o['conversation_turn']==0]
    assert all(o['messages']==[] for o in first)
    second=[o for a,o in seen if o['phase']==2 and o['conversation_turn']==1]
    assert all(len(o['messages'])==2 for o in second)
    request_b=next(o for a,o in seen if a=='B' and o['phase']==3)
    assert '19' not in dumps(request_b)


def test_two_repairs_then_pause_without_strategy_fallback(tmp_path,monkeypatch):
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'message':{'content':'{"request": -1}'},'prompt_eval_count':20,'eval_count':5}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):return Response()
    monkeypatch.setattr('farm.agents.httpx.AsyncClient',Client)
    async def run():
        store=Store(tmp_path/'test.sqlite3');s=new_game(Config(controller='ollama'));s['phase']=3;rid=store.create(s)
        try:await model_decision(s,'A',observation(s,'A'),store,rid,'1:3:0:A')
        except TechnicalError:pass
        else:raise AssertionError('Invalid action must fail visibly')
        calls=store.calls(rid)
        assert len(calls)==3 and [x['attempt'] for x in calls]==[0,1,2]
        totals=store.call_stats(rid)
        assert totals['calls']==3 and totals['corrections']==2 and totals['errors']==3 and totals['tokens']==75
        assert s['agents']['A']['request']==0 and store.decision(rid,'1:3:0:A') is None
    asyncio.run(run())


def test_error_status_when_ollama_unavailable(tmp_path,monkeypatch):
    async def unavailable():raise OSError('Connection refused')
    monkeypatch.setattr('farm.runner.list_models',unavailable)
    async def run():
        store=Store(tmp_path/'test.sqlite3');rid=store.create(new_game(Config(controller='ollama')))
        runner=Runner(store);runner.start(rid);await runner.task
        s=store.load(rid)
        assert s['status']=='technical_error' and s['round']==1 and s['pond']==5000
    asyncio.run(run())


def test_resume_rejects_changed_source_and_prompt_versions(tmp_path):
    async def run():
        store=Store(tmp_path/'version.sqlite3')
        s=new_game(Config());s['source_sha256']='original'
        rid=store.create(s);runner=Runner(store,source_hash='changed');runner.start(rid);await runner.task
        assert store.load(rid)['status']=='technical_error'
        assert 'implementation changed' in store.load(rid)['error']
        s=new_game(Config(controller='ollama'));s['prompt_version']='old-prompt'
        rid=store.create(s);runner.start(rid);await runner.task
        assert 'prompt version differs' in store.load(rid)['error']
        assert store.calls(rid)==[]
    asyncio.run(run())


def test_prompt_allowlist_and_complete_context_records():
    s=new_game(Config(controller='ollama'));s['config']['seed']=87654321
    s['agents']['B']['memory']='Never leak this foreign note'
    obs=observation(s,'A',[{'large': 'x'*50000}])
    messages=prompt_messages(s,'A',obs)
    prompt=json.dumps(messages)
    assert '87654321' not in prompt and 'Never leak this foreign note' not in prompt
    assert '1,000 rounds' not in prompt and '0.001' not in prompt
    assert json.loads(messages[1]['content'])['observation']['recalled_observations']==[]


def test_phase_specific_schemas_do_not_offer_forbidden_actions():
    for phase, communication, allowed in (
        (1, True, {'memory','recall_query'}),
        (2, False, {'memory','recall_query','pass_turn'}),
        (3, True, {'memory','recall_query','request'}),
        (4, True, {'memory','recall_query','new_plants','irrigation'}),
        (7, True, {'memory','recall_query','pass_turn','message','contracts'})):
        assert set(response_model(phase,communication).model_json_schema()['properties'])==allowed


def test_conversation_requires_explicit_boolean_participation():
    for phase in (2,7):
        for communication in (False,True):
            model=response_model(phase,communication)
            assert 'pass_turn' in model.model_json_schema()['required']
            for body in ({}, {'pass_turn':'false'}, {'pass_turn':0}):
                with pytest.raises(ValidationError):model.model_validate(body)
            assert model.model_validate({'pass_turn':False}).pass_turn is False
            assert model.model_validate({'pass_turn':True}).pass_turn is True


def test_contract_response_repaired_without_silent_participation_default(tmp_path,monkeypatch):
    proposal={'kind':'propose','start_round':1,'end_round':10,
              'limits':[{'agent_id':'B','max_request':5,'max_net':'1000'}]}
    responses=iter([{'contracts':[proposal]},
                    {'pass_turn':True,'contracts':[proposal]},
                    {'pass_turn':False,'contracts':[proposal]}])
    requests=[]
    class Response:
        def __init__(self,body):self.body=body
        def raise_for_status(self):pass
        def json(self):return {'message':{'content':json.dumps(self.body)}}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):
            requests.append(kwargs['json'])
            return Response(next(responses))
    monkeypatch.setattr('farm.agents.httpx.AsyncClient',Client)
    async def run():
        store=Store(tmp_path/'repair.sqlite3')
        s=new_game(Config(controller='ollama',communication=True));s['phase']=2
        rid=store.create(s)
        decision=await model_decision(s,'B',observation(s,'B'),store,rid,'1:2:0:B')
        assert decision.pass_turn is False and decision.contracts[0].limits[0].max_request==5
        assert s['contracts']==[]  # Validation does not execute the proposal.
        calls=store.calls(rid)
        assert len(calls)==3 and calls[-1]['error'] is None
        assert 'pass_turn' in calls[0]['error']
        assert 'cannot also pass' in calls[1]['error']
        assert '"pass_turn": false' in requests[1]['messages'][-1]['content']
        assert '"pass_turn": false' in requests[2]['messages'][-1]['content']
    asyncio.run(run())


def test_model_schema_limits_only_physical_access_not_biology():
    s=new_game(Config());s['phase']=4
    schema=model_format(s,'A')
    assert schema['properties']['irrigation']['maxItems']==0
    assert schema['$defs']['NewPlants']['properties']['water_per_plant']['enum']==['0']
    s['agents']['A']['delivered']=9
    schema=model_format(s,'A')
    assert 'enum' not in schema['$defs']['NewPlants']['properties']['water_per_plant']
    assert 'maximum' not in schema['$defs']['NewPlants']['properties']['count']


def test_api_and_exports(tmp_path):
    app=create_app(tmp_path/'test.sqlite3')
    with TestClient(app) as client:
        assert client.get('/').status_code==200
        assert client.get('/static/app.js').status_code==200
        rid=client.post('/api/runs',json={'rounds':2,'output_directory':str(tmp_path/'export')}).json()['id']
        assert client.get('/api/runs/'+rid).json()['state']['pond']==5000
        assert client.get('/api/runs/not-found').status_code==404
        assert client.post('/api/runs',json={'test_mode':False,'rounds':10}).status_code==422
        assert client.post(f'/api/runs/{rid}/start').status_code==200
        # Querying the task through the test portal avoids timing-dependent sleeps.
        async def join():
            await app.state.runner.task
        client.portal.call(join)
        state=client.get('/api/runs/'+rid).json()['state']
        assert state['status']=='completed'
        assert client.post(f'/api/runs/{rid}/start').status_code==409
        assert client.get(f'/api/runs/{rid}/download/csv').text.startswith('run_id,technical_test')
        payload=loads(client.get(f'/api/runs/{rid}/download/json').text)
        assert isinstance(payload['state']['pond'],Fraction)
        assert payload['events'] and payload['observations'] and payload['decisions']
        assert client.post(f'/api/runs/{rid}/export').status_code==200
        assert (tmp_path/'export'/f'{rid}.json').exists()


def test_paired_queue_uses_shared_weather_not_memories(tmp_path):
    app=create_app(tmp_path/'test.sqlite3')
    with TestClient(app) as client:
        response=client.post('/api/experiments',json={'base':{'rounds':3},'seeds':[17],
                     'models':['ignored-for-tests'],'balance_positions':True})
        assert response.status_code==201,response.text
        experiment=response.json()
        assert len(experiment['runs'])==4
        assert client.post(f"/api/experiments/{experiment['id']}/start").status_code==200
        async def join():await app.state.batch_task
        client.portal.call(join)
        results=client.get(f"/api/experiments/{experiment['id']}/results").json()
        assert all(x['status']=='completed' for x in results['results'])
        a,b=experiment['runs'][:2]
        sa=app.state.store.load(a['run_id']);sb=app.state.store.load(b['run_id'])
        assert [x['weather'] for x in sa['history']]==[x['weather'] for x in sb['history']]
        assert a['pair']==b['pair'] and sa['config']['communication'] is False and sb['config']['communication'] is True


def test_pause_queue_saves_current_decision_and_leaves_next_game_untouched(tmp_path,monkeypatch):
    gate = None
    async def models():return [{'name':'test-model','digest':'fixed'}]
    async def decide(*args):
        nonlocal gate
        gate = asyncio.Event()
        await gate.wait()
        return Decision()
    monkeypatch.setattr('farm.runner.list_models',models)
    monkeypatch.setattr('farm.runner.model_decision',decide)
    app=create_app(tmp_path/'pause.sqlite3')
    with TestClient(app) as client:
        experiment=client.post('/api/experiments',json={
            'base':{'rounds':1,'controller':'ollama','model':'test-model'},
            'seeds':[17],'models':['test-model'],'balance_positions':False}).json()
        eid=experiment['id']
        next_initial=app.state.store.load(experiment['runs'][1]['run_id'])
        client.post(f'/api/experiments/{eid}/start')
        async def wait_started():
            while gate is None:await asyncio.sleep(0)
        client.portal.call(wait_started)
        assert client.post(f'/api/experiments/{eid}/pause').status_code==200
        async def finish():
            gate.set()
            await app.state.batch_task
        client.portal.call(finish)
        assert app.state.store.experiments()[0]['status']=='paused'
        first,second=[x['run_id'] for x in experiment['runs']]
        assert app.state.store.load(first)['status']=='paused'
        assert app.state.store.decision(first,'1:1:0:A') is not None
        assert app.state.store.load(second)==next_initial
        assert app.state.store.decision(second,'1:1:0:A') is None
