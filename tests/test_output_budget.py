import asyncio
from copy import deepcopy
import json

import pytest

from farm.agents import TechnicalError, model_decision, model_format
from farm.context import input_budget, message_bytes
from farm.engine import new_game, validate_decision, farm_work
from farm.schema import Config, Decision
from farm.store import Store
from farm.views import observation


def farm_state(water=0):
    s = new_game(Config())
    s['phase'] = 4
    s['agents']['A']['delivered'] = water
    return s


def test_zero_water_has_one_combined_sowing_entry_without_a_plant_count_limit():
    s = farm_state()
    schema = model_format(s, 'A')
    assert schema['properties']['new_plants']['maxItems'] == 1
    assert schema['properties']['irrigation']['maxItems'] == 0
    assert 'maximum' not in schema['$defs']['NewPlants']['properties']['count']
    action = Decision(new_plants=[{'count': 10000, 'water_per_plant': '0'}])
    validate_decision(s, 'A', action)
    farm_work(s, 'A', action)
    assert len(s['agents']['A']['plants']) == 1
    assert s['agents']['A']['plants'][0]['count'] == 10000


def test_positive_water_still_allows_many_distinct_doses_and_large_same_dose_groups():
    s = farm_state(49)
    schema = model_format(s, 'A')
    assert 'maxItems' not in schema['properties']['new_plants']
    action = Decision(new_plants=[{'count': 20, 'water_per_plant': '2'},
                                 {'count': 1, 'water_per_plant': '3'},
                                 {'count': 1, 'water_per_plant': '6'}])
    validate_decision(s, 'A', action)
    farm_work(s, 'A', action)
    assert [(g['count'], g['water']) for g in s['agents']['A']['plants']] == [(20, 2), (1, 3), (1, 6)]


def fake_client(monkeypatch, responses, requests):
    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            requests.append(json)
            return Response(responses[min(len(requests)-1, len(responses)-1)])

    monkeypatch.setattr('farm.agents.httpx.AsyncClient', Client)


def truncated_output():
    raw = '{"new_plants":[' + ','.join('{"count":1,"water_per_plant":"0"}' for _ in range(100))
    raw += ',{"count":1,"water_per_plant'
    return {'message': {'content': raw}, 'done_reason': 'length', 'eval_count': 2048}


def test_truncated_loop_is_not_replayed_or_executed_and_retry_uses_fresh_complete_json(tmp_path, monkeypatch):
    requests = []
    bad = truncated_output()
    good = {'message': {'content': '{"new_plants":[{"count":7,"water_per_plant":"0"}],"irrigation":[]}'},
            'done_reason': 'stop'}
    fake_client(monkeypatch, [bad, good], requests)

    async def run():
        s = farm_state(); before = deepcopy(s)
        store = Store(tmp_path/'truncated.sqlite3'); rid = store.create(s)
        result = await model_decision(s, 'A', observation(s, 'A'), store, rid, '1:4:0:A')
        assert result.new_plants[0].count == 7  # chosen by the new response, not salvaged from the fragment
        calls = store.calls(rid)
        assert len(calls) == 2 and calls[0]['output_truncated']
        assert '2048-token limit' in calls[0]['error']
        assert calls[0]['raw_response'] == bad['message']['content']
        assert calls[1]['error'] is None and not calls[1]['output_truncated']
        assert s == before and store.decision(rid, '1:4:0:A') is None
        assert bad['message']['content'] not in json.dumps(requests[1]['messages'])
        assert not any(m['role'] == 'assistant' for m in requests[1]['messages'])
        feedback = requests[1]['messages'][-1]['content']
        assert 'NEW complete JSON object' in feedback and 'ONE combined zero-dose entry' in feedback
        window = json.loads(requests[1]['messages'][1]['content'])['context_window']
        assert window['previous_invalid_response_omitted']
        assert all(message_bytes(r['messages']) <= input_budget(s['config']) for r in requests)

    asyncio.run(run())


def test_three_truncated_responses_stop_without_executing_a_partial_action(tmp_path, monkeypatch):
    requests = []
    fake_client(monkeypatch, [truncated_output()], requests)

    async def run():
        s = farm_state(); before = deepcopy(s)
        store = Store(tmp_path/'repeat.sqlite3'); rid = store.create(s)
        with pytest.raises(TechnicalError, match='token limit before completing JSON'):
            await model_decision(s, 'A', observation(s, 'A'), store, rid, '1:4:0:A')
        assert len(store.calls(rid)) == 3
        assert all(c['output_truncated'] for c in store.calls(rid))
        assert s == before and store.decision(rid, '1:4:0:A') is None

    asyncio.run(run())


def test_complete_valid_json_at_length_boundary_is_accepted(tmp_path, monkeypatch):
    requests = []
    fake_client(monkeypatch, [{'message': {'content': '{"new_plants":[],"irrigation":[]}'},
                              'done_reason': 'length', 'eval_count': 2048}], requests)

    async def run():
        s = farm_state(); store = Store(tmp_path/'complete.sqlite3'); rid = store.create(s)
        result = await model_decision(s, 'A', observation(s, 'A'), store, rid, '1:4:0:A')
        assert not result.new_plants and not result.irrigation
        assert len(store.calls(rid)) == 1 and not store.calls(rid)[0]['output_truncated']

    asyncio.run(run())


def test_qwen_empty_exhausted_planning_answer_retries_directly_with_same_budget(tmp_path, monkeypatch):
    requests = []
    fake_client(monkeypatch, [
        {'message': {'content': ''}, 'done_reason': 'length', 'eval_count': 2048},
        {'message': {'content': '{"planned_sowing":[],"memory":{"cash_plan":{"focus":"cash reserve",'
                                '"next_move":"Keep enough coins for the next delivery."}}}'}, 'done_reason': 'stop'},
    ], requests)

    async def run():
        s = new_game(Config(model='qwen3.5:9b', controller='ollama'))
        store = Store(tmp_path/'qwen.sqlite3')
        rid = store.create(s)
        choice = await model_decision(s, 'A', observation(s, 'A'), store, rid, '1:1:0:A')
        assert choice.memory.goal == 'cash reserve — Keep enough coins for the next delivery.'
        assert 'think' not in requests[0] and requests[1]['think'] is False
        assert requests[0]['options'] == requests[1]['options']
        assert 'zero-dose' not in requests[1]['messages'][-1]['content']
        assert store.calls(rid)[0]['output_truncated']
    asyncio.run(run())
