"""Participant uniqueness and lossless model-format translation for proposals."""
import asyncio
import json

import pytest
from pydantic import ValidationError

from farm.agents import model_format, model_decision, parse_model_response
from farm.engine import new_game, validate_decision, advance
from farm.schema import Config, Decision, response_model
from farm.store import Store, dumps
from farm.views import observation


def state(phase=2):
    s = new_game(Config(agent_count=5, communication=True, model='qwen3.5:9b'))
    s.update(round=12, phase=phase, news_ready=phase == 7)
    return s


def parse(body):
    raw = body if isinstance(body, str) else json.dumps(body)
    return Decision.model_validate(parse_model_response(raw, response_model(2, True), public=True).model_dump())


@pytest.mark.parametrize('phase,aid', [(2, 'A'), (2, 'E'), (7, 'C')])
def test_output_schema_names_participants_once_and_requires_the_actor(phase, aid):
    s = state(phase)
    s['public_active_agents'] = ['A', 'C', 'E']
    schema = model_format(s, aid)
    limits = schema['$defs']['ContractAction']['oneOf'][0]['properties']['limits']
    assert limits['type'] == 'object' and limits['additionalProperties'] is False
    assert limits['required'] == [aid]
    assert set(limits['properties']) == {'A', 'C', 'E'}
    for branch in schema['$defs']['Limit']['oneOf']:
        assert 'agent_id' not in branch['properties']
        assert branch['required'] in (['max_request'], ['max_net'])


def test_keyed_limits_preserve_distinct_model_chosen_terms_and_existing_action_storage():
    s = state()
    body = {'pass_turn': False, 'contracts': [{'kind': 'propose', 'start_round': 12, 'end_round': 15,
            'limits': {'E': {'max_request': 2, 'max_net': '2.5'}, 'B': {'max_net': '1.5'}}}]}
    decision = parse(body)
    assert [(v.agent_id, v.max_request, v.max_net) for v in decision.contracts[0].limits] == [
        ('E', 2, '2.5'), ('B', None, '1.5')]
    s['config']['start_agent'] = 3  # E opens round 12.
    advance(s, {'E': decision})
    assert s['contracts'][0]['participants'] == ['E', 'B']
    assert s['contracts'][0]['signatures'] == ['E']
    assert s['contracts'][0]['limits'] == [v.model_dump() for v in decision.contracts[0].limits]


def test_terms_retry_couples_replacement_id_to_exact_members_and_keeps_independent_proposals():
    s = state(7)
    s['contracts'] = [dict(id=cid, status='active', participants=members) for cid, members in
                      [('c1', ['A','E']), ('c2', ['E','A']), ('c3', ['E']), ('c4', ['A'])]]
    variants = model_format(s, 'E', repair_terms=True)['$defs']['ContractAction']['oneOf']
    new, *replacements = [v for v in variants if v['properties']['kind']['enum'] == ['propose']]
    assert new['properties']['replaces']['type'] == 'null'
    assert new['properties']['limits']['required'] == ['E']
    assert [(v['properties']['replaces']['enum'],v['properties']['limits']['required']) for v in replacements] == [
        (['c1','c2'], ['A','E']), (['c3'], ['E'])]
    for v in replacements:
        assert set(v['properties']['limits']['properties']) == set(v['properties']['limits']['required'])
        assert 'replaces' in v['required']
    raw = json.dumps({'pass_turn':False,'contracts':[{'kind':'propose','start_delay':2,'additional_rounds':0,
                     'limits':{'E':{'max_request':0}}}]})
    action = parse_model_response(raw,response_model(7,True),public=True,earliest=13).contracts[0]
    assert (action.start_round,action.end_round) == (15,15)


@pytest.mark.parametrize('limits,match', [
    ({'B': {'max_request': 2}}, 'include yourself: Farm E'),
    ({'E': {'max_request': 2}, 'Z': {'max_request': 1}}, 'active agents'),
    ({'E': {}}, 'at least one limit'),
    ({'E': {'agent_id': 'B', 'max_request': 2}}, 'omit nested agent_id'),
    ({'E': {'max_request': 2, 'condition': 'if rain'}}, 'Extra inputs'),
])
def test_unconstrained_provider_cannot_bypass_participant_or_term_validation(limits, match):
    s = state(); before = dumps(s)
    with pytest.raises(ValueError, match=match):
        decision = parse({'pass_turn': False, 'contracts': [{'kind': 'propose',
                         'start_round': 12, 'end_round': 15, 'limits': limits}]})
        validate_decision(s, 'E', decision)
    assert dumps(s) == before


def test_duplicate_json_farm_keys_are_rejected_instead_of_silently_overwritten():
    raw = '{"pass_turn":false,"contracts":[{"kind":"propose","start_round":12,"end_round":15,"limits":{"E":{"max_request":2},"E":{"max_request":1}}}]}'
    with pytest.raises(ValueError, match="Duplicate JSON key 'E'"):
        parse(raw)


def test_incomplete_public_json_keeps_output_budget_error_classification():
    with pytest.raises(ValidationError) as error:
        parse('{"pass_turn":false,"contracts":[')
    assert error.value.errors()[0]['type'] == 'json_invalid'


def test_recorded_duplicate_proposal_gets_specific_feedback_and_model_selects_its_own_repair(tmp_path, monkeypatch):
    s = state()
    bad = {'kind': 'propose', 'start_round': 12, 'end_round': 15, 'limits': [
        {'agent_id': 'E', 'max_request': 2, 'max_net': '2.5'},
        {'agent_id': 'E', 'max_request': 1, 'max_net': '1.5'}]}
    # The model explicitly chooses different terms. The adapter must not merge or
    # keep a bound from the failed draft on the model's behalf.
    fixed = {**bad, 'limits': {'E': {'max_request': 3}, 'A': {'max_net': '4.25'}}}
    replies = iter([bad, fixed]); requests = []
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'message': {'content': json.dumps({'pass_turn': False, 'contracts': [next(replies)]})}}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            requests.append(kwargs['json']); return Response()
    monkeypatch.setattr('farm.agents.httpx.AsyncClient', Client)
    store = Store(tmp_path/'participants.sqlite3'); rid = store.create(s)
    before = dumps(s)
    decision = asyncio.run(model_decision(s, 'E', observation(s, 'E'), store, rid, '12:2:5:E'))
    assert dumps(s) == before
    assert [(v.agent_id, v.max_request, v.max_net) for v in decision.contracts[0].limits] == [
        ('E', 3, None), ('A', None, '4.25')]
    assert 'Duplicate participants: E' in requests[1]['messages'][-1]['content']
    calls = store.calls(rid)
    assert len(calls) == 2 and calls[0]['raw_response'].count('"agent_id": "E"') == 2
    assert calls[1]['error'] is None
