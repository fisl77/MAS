import asyncio
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from farm.agents import prompt_messages
from farm.app import create_app
from farm.conversation import retain_public_history
from farm.engine import advance, new_game
from farm.runner import Runner
from farm.schema import Config, Decision, NOTE_LENGTH, PrivateNotes
from farm.store import Store, dumps, loads
from farm.views import observation


def test_partial_working_notes_survive_checkpoint_and_clear_individually():
    s = new_game(Config())
    advance(s, {'A': Decision(memory={'goal': 'Compare two doses.', 'open_question': 'Will health decline?'}),
                'B': Decision(memory={'insight': 'PRIVATE_B'})})
    s = loads(dumps(s))
    advance(s, {'A': Decision(memory={'open_question': '', 'insight': 'Still untested.'})})
    advance(s, {'A': Decision()})
    assert observation(s, 'A')['own_farm']['memory'] == {'goal': 'Compare two doses.', 'insight': 'Still untested.'}
    assert 'PRIVATE_B' not in dumps(observation(s, 'A'))
    for memory in ({'goal': 'a'*(NOTE_LENGTH+1)}, 'old free text', {'invented': 'field'}):
        with pytest.raises(ValidationError):
            PrivateNotes(memory=memory)
    assert Decision.model_validate({'memory': 'old free text'}).memory == 'old free text'


def test_archive_retrieval_through_worker_preserves_measured_changes_and_owner(tmp_path, monkeypatch):
    seen = {}
    async def models():
        return [{'name': 'fixture', 'digest': 'fixed'}]
    async def decide(s, aid, obs, _store, _rid, key):
        seen[key] = obs
        r, phase = s['round'], s['phase']
        if phase == 1 and r == 3:
            return Decision(recall_query='round 1 dose 3.125')
        if phase == 2 and s['turn'] < 2 and aid == 'B':
            return Decision(pass_turn=False, message='My crop grew 99 points at 3.125 liters.')
        if phase == 3:
            return Decision(request=4 if aid == 'A' else 8)
        if phase == 4:
            dose = '3.125' if aid == 'A' and r == 1 else str(4 if aid == 'A' else 8)
            return Decision(new_plants=[{'count': 1, 'water_per_plant': dose}])
        return Decision()
    monkeypatch.setattr('farm.runner.list_models', models)
    monkeypatch.setattr('farm.runner.model_decision', decide)
    def no_snapshots(*args, **kwargs):
        pytest.fail('The worker tried to read full old observations')
    monkeypatch.setattr(Store, 'recall', no_snapshots)

    store = Store(tmp_path/'farm.sqlite3')
    rid = store.create(new_game(Config(controller='ollama', model='fixture', rounds=3, communication=True)))
    async def play():
        runner = Runner(store)
        runner.start(rid)
        await runner.task
    asyncio.run(play())
    assert store.load(rid)['status'] == 'completed'
    a = seen['3:2:0:A']
    expected = {'kind': 'plant', 'round': 1, 'group_id': 'A-p1', 'count': 1,
                'water_per_plant': '3.125', 'growth': [0, 10], 'health': [0, 20],
                'outcome': 'growing', 'stage': 'sown'}
    assert a['recalled_experiences'] == [expected]
    assert expected not in seen['3:2:1:B']['recalled_experiences']
    assert all(len(o['recalled_experiences']) <= 3 and 'recalled_observations' not in o for o in seen.values())
    reopened = Store(tmp_path/'farm.sqlite3')
    assert reopened.experiences(rid, 'A', a, 'A-p1 round 1') == [expected]
    assert reopened.experiences(rid, 'B', a, 'A-p1 round 1') == []
    assert reopened.experiences('other-game', 'A', a, 'A-p1') == []
    assert reopened.experiences(rid, 'A', a, 'round 1 fees')[0]['returned'] == '0.875'
    assert reopened.experiences(rid, 'A', a, 'unseen content') == []
    exported = reopened.export(rid)
    assert sum(e == {'agent_id': 'A', **expected} for e in exported['experiences']) == 1
    assert '99 points' not in dumps(exported['experiences'])
    assert any('99 points' in e.get('text','') for e in exported['events'])
    assert all(k in exported for k in ('observations','decisions','calls'))


def test_old_discussion_remains_attributed_and_open_terms_are_exact():
    s = new_game(Config(agent_count=3, communication=True))
    s['phase'] = 2
    advance(s, {'A': Decision()})
    advance(s, {'B': Decision(pass_turn=False, message='Farm A, I offer a cap of 17 L.',
                              contracts=[{'kind':'propose', 'start_round':300, 'end_round':301,
                                          'limits':[{'agent_id':'B','max_request':17},
                                                    {'agent_id':'A','max_net':'16.125'}]}])})
    advance(s, {'C': Decision(pass_turn=False, message='A huge dose guarantees a sale.')})
    advance(s, {'A': Decision(pass_turn=False, message='B, what about return fees?')})
    advance(s, {'B': Decision()})
    advance(s, {'C': Decision()})
    advance(s, {'A': Decision(pass_turn=False, message='I am waiting for the pond forecast.')})
    obs = observation(s, 'A')
    assert [m['turn'] for m in obs['messages']] == [3,6]
    assert obs['followup_messages'][0]['text'] == 'Farm A, I offer a cap of 17 L.'
    assert obs['followup_messages'][0]['source_type'] == 'unverified_peer_claim'
    [claim] = [item for item in obs['older_discussion'] if item['sender']=='C']
    assert claim['round'] == 1 and claim['source_type'] == 'unverified_peer_claim'
    assert claim['text'] == 'A huge dose guarantees a sale.' and 'plant care' in claim['topics']
    [c] = obs['agreements']
    assert c['id'] == 'c1' and c['status'] == 'proposed' and c['signatures'] == ['B']
    assert c['limits'][1]['max_net'] == '16.125'
    assert not obs['own_farm']['recent_plant_results'] and not obs['recalled_experiences']
    # The short attribution survives eviction of all the old turns and a checkpoint.
    for i in range(205):
        s['messages'].append({'round':i+2,'phase':2,'turn':0,'sender':'A','text':f'Water request {i}.'})
    s['round'] = 207
    retain_public_history(s)
    after = observation(loads(dumps(s)), 'A')
    assert len(s['messages']) == 200 and len(after['older_discussion']) <= 3
    assert claim in after['older_discussion']
    assert after['agreements'] == [c]


def test_care_keeps_full_inventory_delivery_and_terms_without_public_dialogue():
    s = new_game(Config(communication=True))
    s['phase'] = 2
    advance(s, {'A': Decision(pass_turn=False, message='A statement for discussion only.',
                              contracts=[{'kind':'propose','start_round':1,'end_round':3,
                                          'limits':[{'agent_id':'A','max_request':24}]}])})
    discussion = prompt_messages(s, 'A', observation(s, 'A'))
    assert 'AGREEMENT HOW-TO' in discussion[0]['content']
    assert 'Split a group' not in discussion[0]['content']
    s['phase'] = 4
    s['agents']['A'].update(delivered=24, plants=[{'id':'A-p2','count':3,'growth':20,'health':18,
                                                 'water':4,'new':False}])
    before = deepcopy(s)
    care = prompt_messages(s, 'A', observation(s, 'A'))
    context = json.loads(care[1]['content'])
    assert context['farm_water_budget']['available_liters'] == '24'
    assert context['observation']['own_farm']['plants'] == s['agents']['A']['plants']
    assert context['observation']['agreements'][0]['limits'][0]['max_request'] == 24
    assert 'AGREEMENT HOW-TO' not in care[0]['content'] and 'Split a group' in care[0]['content']
    assert not {'messages','followup_messages','negotiation_messages','older_discussion','conversation_status'} & set(context['observation'])
    assert s == before


def test_older_games_show_the_original_saved_observation(tmp_path):
    app = create_app(tmp_path/'older.sqlite3')
    store = app.state.store
    s = new_game(Config())
    s['prompt_version'] = 'farm-agent-1.13'
    rid = store.create(s)
    old = {'round': 2, 'phase': 1, 'own_farm': {'id':'A','memory':'long old note '*200},
           'recalled_observations': [{'round':1,'phase':4}]}
    store.accept(rid,'2:1:0:A','A',Decision().model_dump(),old)
    with TestClient(app) as client:
        assert client.get(f'/api/runs/{rid}/agents/A').json() == old
        assert client.get(f'/api/runs/{rid}/download/json').json()['observations'][0]['observation'] == old
