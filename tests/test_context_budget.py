import asyncio
from copy import deepcopy
import json

import pytest

from farm.agents import TechnicalError, model_decision, prompt_messages
from farm.context import input_budget, message_bytes
from farm.contracts import apply_contract_action
from farm.engine import farm_work, grow, new_game
from farm.schema import Config, ContractAction, Decision, NOTE_LENGTH
from farm.store import Store
from farm.views import observation


def records(value):
    if isinstance(value, dict) and 'columns' in value:
        return [dict(zip(value['columns'], row)) for row in value['rows']]
    return value


def discussion(farms=3):
    s = new_game(Config(agent_count=farms, communication=True,
                        profiles=['cunning_experimenter'] * farms))
    s['round'], s['phase'], s['turn'] = 6, 2, 5
    return s


def test_latest_speaker_stays_visible_under_long_history():
    s = discussion(5)
    s['agents']['E']['memory'] = 'Private hypothesis. ' * 200
    s['agents']['A']['memory'] = 'FOREIGN_PRIVATE_NOTE'
    for turn in range(6):
        for aid in s['agents']:
            s['messages'].append({'round': 6, 'phase': 2, 'turn': turn, 'sender': aid,
                                  'text': f'PUBLIC_{turn}_{aid} ' + 'What is your response? ' * 80,
                                  'contracts': []})
    obs = observation(s, 'E')
    original = deepcopy(obs)
    messages = prompt_messages(s, 'E', obs)
    body = json.loads(messages[1]['content'])
    shown = body['observation']['messages']
    assert len(shown)==1 and shown[0]['sender']=='E' and shown[0]['turn']==5
    assert body['context_window']['omitted_history_records']['public_messages'] > 0
    assert message_bytes(messages) <= input_budget(s['config'])
    assert body['observation']['own_farm']['memory'] == obs['own_farm']['memory']
    assert 'FOREIGN_PRIVATE_NOTE' not in json.dumps(messages)
    assert obs == original


def test_large_current_agreements_and_inventory_are_packed_without_losing_terms():
    s = discussion()
    s['config']['context_tokens'] = 12288  # Force packing even with the shorter phase instructions.
    a = s['agents']['A']
    a['memory'] = 'm' * 4000
    a['plants'] = [{'id': f'A-p{i}', 'count': i+1, 'growth': i, 'health': 20,
                    'water': 3, 'new': False} for i in range(20)]
    for i in range(65):
        apply_contract_action(s, 'A', ContractAction(kind='propose', start_round=6,
                              end_round=7+i, limits=[{'agent_id': 'A', 'max_request': 100+i}]))
    obs = observation(s, 'A')
    original = deepcopy(obs)
    messages = prompt_messages(s, 'A', obs)
    body = json.loads(messages[1]['content'])
    assert records(body['observation']['agreements']) == obs['agreements']
    assert records(body['observation']['own_farm']['plants']) == obs['own_farm']['plants']
    assert body['observation']['own_farm']['memory'] == {'insight': 'm'*(NOTE_LENGTH-1) + '…'}
    assert a['memory'] == 'm'*4000
    assert body['context_window']['current_records_packed_losslessly']
    assert message_bytes(messages) <= input_budget(s['config'])
    assert obs == original


def test_recall_uses_owner_outcomes_instead_of_repeated_past_conversations(tmp_path):
    s = discussion()
    store = Store(tmp_path/'recall.sqlite3')
    rid = store.create(s)
    past = {'own_farm': {'id': 'A', 'memory': 'PAST_UNVERIFIED_PRIVATE_GUESS'},
            'messages': [{'text': 'OLD_PEER_MESSAGE ' * 4000}],
            'recalled_observations': [{'nested': 'MUST_NOT_RECURSE'}]}
    store.accept(rid, '5:1:0:A', 'A', Decision().model_dump(), past)
    farm_work(s, 'A', Decision(new_plants=[{'count': 2, 'water_per_plant': '3.125'}]))
    grow(s)
    store.save(rid, s)
    s['round'] += 1
    grow(s)
    store.save(rid, s)
    s['agents']['A']['recall_query'] = 'round 6 dose 3.125'
    obs = observation(s, 'A', store=store, rid=rid)
    messages = prompt_messages(s, 'A', obs)
    recalled = json.loads(messages[1]['content'])['observation']['recalled_experiences']
    assert recalled == [{'kind': 'plant', 'round': 6, 'group_id': 'A-p1', 'count': 2,
                         'water_per_plant': '3.125', 'growth': [0, 10], 'health': [0, 20],
                         'outcome': 'growing', 'stage': 'sown'}]
    assert 'OLD_PEER_MESSAGE' not in json.dumps(messages)
    assert 'PAST_UNVERIFIED_PRIVATE_GUESS' not in json.dumps(messages)
    assert 'MUST_NOT_RECURSE' not in json.dumps(messages)
    assert store.export(rid)['observations'][0]['observation'] == past


def test_genuinely_oversized_current_state_fails_without_discarding_inventory():
    s = discussion()
    s['agents']['A']['plants'] = [{'id': f'A-p{i}', 'count': 1, 'growth': 10,
                                  'health': 20, 'water': 3, 'new': False} for i in range(4000)]
    obs = observation(s, 'A')
    with pytest.raises(TechnicalError, match='current farm records and agreement terms were preserved'):
        prompt_messages(s, 'A', obs)
    assert len(obs['own_farm']['plants']) == 4000
    assert len(s['agents']['A']['plants']) == 4000


@pytest.mark.parametrize('oversized_first_output', [False, True])
def test_each_repair_obeys_budget_and_keeps_only_latest_invalid_response(tmp_path, monkeypatch,
                                                                       oversized_first_output):
    requests = []
    first = {'request': -1, 'memory': 'FIRST_INVALID_MARKER ' + 'x' * 3900}
    if oversized_first_output:
        first['unexpected_padding'] = 'z' * 20000
    responses = [first, {'request': -2, 'memory': 'SECOND_INVALID_MARKER ' + 'y' * 3900},
                 {'request': 4}]

    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return {'message': {'content': json.dumps(self.value)}}

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            requests.append(json)
            return Response(responses[len(requests)-1])

    monkeypatch.setattr('farm.agents.httpx.AsyncClient', Client)

    async def run():
        s = new_game(Config(context_tokens=8192)); s['phase'] = 3
        store = Store(tmp_path/'repairs.sqlite3'); rid = store.create(s)
        decision = await model_decision(s, 'A', observation(s, 'A'), store, rid, '1:3:0:A')
        assert decision.request == 4
        assert len(store.calls(rid)) == 3
        assert 'FIRST_INVALID_MARKER' in store.calls(rid)[0]['raw_response']
        for request in requests:
            assert message_bytes(request['messages']) <= input_budget(s['config'])
            assert sum(m['role'] == 'assistant' for m in request['messages']) <= 1
        assert 'FIRST_INVALID_MARKER' not in json.dumps(requests[2]['messages'])
        assert s['agents']['A']['request'] == 0
        assert store.decision(rid, '1:3:0:A') is None
        if oversized_first_output:
            window = json.loads(requests[1]['messages'][1]['content'])['context_window']
            assert window['previous_invalid_response_omitted']

    asyncio.run(run())
