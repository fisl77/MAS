import json

from fastapi.testclient import TestClient

from farm.app import create_app
from farm.agents import prompt_messages
from farm.engine import advance, new_game
from farm.schema import Config, Decision
from farm.store import Store, dumps
from farm.views import observation


def test_sowing_plan_selects_matching_stage_and_explicit_search_wins(tmp_path):
    s = new_game(Config())
    store = Store(tmp_path/'game.db')
    rid = store.create(s)
    with store.connection() as db:
        for i, (aid, dose, stage) in enumerate([('A','2','sown'), ('A','2','established'),
                                                 ('B','2','sown'), ('A','4','sown')], 1):
            group = f'{aid}-p{i}'
            row = dict(kind='plant', round=i, group_id=group, count=2, water_per_plant=dose,
                       growth=[0,10], health=[0,20], outcome='growing', stage=stage)
            db.execute('INSERT INTO experiences VALUES(?,?,?,?,?,?,?,?)',
                       (rid,aid,i,'plant',group,dose,stage,json.dumps(row)))
    s.update(round=6,phase=3)
    a = s['agents']['A']
    a['planned_sowing'] = [{'count':1,'water_per_plant':'2.0'}]
    a['memory'] = {'open_question':'How did my seedlings grow?'}
    obs = observation(s,'A',store=store,rid=rid)
    rows = obs['recalled_experiences']
    assert rows[0]['group_id'] == 'A-p1' and len(rows) <= 3
    assert len({r['group_id'] for r in rows}) == len(rows)
    a['recall_query'] = 'round 2 dose 2 established'
    assert [r['group_id'] for r in observation(s,'A',store=store,rid=rid)['recalled_experiences']] == ['A-p2']
    a['recall_query'] = 'dose 9'
    assert not observation(s,'A',store=store,rid=rid)['recalled_experiences']


def test_later_negotiation_separates_quote_signature_and_own_compliance(tmp_path):
    s = new_game(Config(communication=True))
    s['phase'] = 2
    store = Store(tmp_path/'game.db')
    rid = store.create(s)
    def play(a, d):
        advance(s, {a:d})
        store.save(rid,s)
    claim = 'I promise to share my findings under c1.'
    play('A', Decision(pass_turn=False,message=claim,contracts=[dict(
        kind='propose',start_round=1,end_round=1,limits=[{'agent_id':a,'max_request':2} for a in 'AB'])]))
    play('B', Decision(pass_turn=False, contracts=[dict(kind='accept',contract_id='c1')]))
    s['agents']['A']['memory']={'insight':'PRIVATE_A'}
    s['agents']['A']['last_deliberate_bluff']={'intended_benefit':'SECRET_A'}
    s.update(round=4,phase=2,turn=0,messages=[])
    s['contracts'][0]['status']='expired'
    b=s['agents']['B']
    def read(query):
        b['recall_query']=query
        obs=observation(s,'B',store=store,rid=rid)
        msg=json.loads(prompt_messages(s,'B',obs)[1]['content'])['observation']
        assert 'PRIVATE_A' not in dumps(msg) and 'SECRET_A' not in dumps(msg)
        assert len(msg['recalled_experiences']) <= 1
        return msg['recalled_experiences']
    [signature]=read('Who signed c1?')
    assert signature['kind']=='contract_record' and signature['signatures']==['A','B']
    [quote]=read('What did Farm A promise under c1?')
    assert quote['kind']=='claim' and quote['source_type']=='unverified_peer_claim' and quote['text']==claim
    assert 'own_result' not in signature
    s['config']['communication']=False
    assert read('Farm A promise under c1')==[]


def test_note_history_api_pages_only_this_farm(tmp_path):
    app=create_app(tmp_path/'history.db')
    store=app.state.store
    s=new_game(Config())
    rid=store.create(s)
    for i in range(53):
        s['events'].append(dict(kind='note_changed',round=i+1,phase=1,turn=0,agent_id='A',
                                field='insight',value=str(i),previous=None,evidence=None))
    store.save(rid,s)
    with TestClient(app) as client:
        path=f'/api/runs/{rid}/agents'
        first=client.get(path+'/A/notes').json()
        assert len(first['changes'])==50 and first['changes'][0]['round']==53
        second=client.get(path+'/A/notes',params={'before':first['before']}).json()
        assert [r['round'] for r in second['changes']]==[3,2,1] and second['before'] is None
        assert client.get(path+'/B/notes').json()['changes']==[]
        assert client.get(path+'/X/notes').status_code==404
