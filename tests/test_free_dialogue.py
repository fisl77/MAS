"""Topic-neutral followups, compact replies and archival compatibility."""
import asyncio
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from farm.agents import model_decision, model_format, prompt_messages
from farm.conversation import public_discussion
from farm.engine import new_game
from farm.schema import Config, Decision, response_model
from farm.store import Store, dumps
from farm.views import observation


def discussion():
    s = new_game(Config(agent_count=3, communication=True, model='llama3.1:8b'))
    s.update(phase=2, turn=6)
    return s


def message(turn, text, sender='B', phase=2, round=1):
    return {'round': round, 'phase': phase, 'turn': turn, 'sender': sender, 'text': text}


def tail():
    return [message(4, 'A recent statement.'), message(5, 'Another recent statement.')]


def test_newer_plant_and_strategy_questions_can_displace_an_older_open_offer():
    s = discussion()
    s['contracts'] = [{'id': 'c1', 'status': 'proposed', 'participants': ['A', 'B']}]
    s['messages'] = [message(0, 'Farm A, please consider c1.'),
                     message(1, 'Farm A, how did plant health change in your trial?'),
                     message(2, 'Does anyone want to compare approaches to preserving capital?', 'C'), *tail()]
    before = deepcopy(s)
    view = public_discussion(s, 'A')
    assert [m['turn'] for m in view['followup_messages']] == [1, 2]
    assert all(m['source_type'] == 'unverified_peer_claim' for m in view['followup_messages'])
    assert all('unanswered' not in m for m in view['followup_messages'])
    assert 'negotiation_messages' not in view and s == before


def test_closed_offer_wrong_recipient_and_old_phase_questions_are_not_selected():
    s = discussion()
    s['messages'] = [message(0, 'Farm A, accept the cap in c9.'),
                     message(1, 'Farm C, how did your plants respond?'),
                     message(1, 'Farm A, which observation changed your plan?', phase=7, round=0),
                     message(2, 'Everyone, which uncertainties should we test next?'), *tail()]
    assert [m['turn'] for m in public_discussion(s, 'A')['followup_messages']] == [2]


def test_open_older_offer_remains_available_but_only_latest_quote_per_contract():
    s = discussion()
    s['contracts'] = [{'id': 'c1', 'status': 'proposed', 'participants': ['A', 'B']}]
    s['messages'] = [message(0, 'Farm A, here is c1.', round=0),
                     message(1, 'Farm A, what do you think about c1?'), *tail()]
    extras = public_discussion(s, 'A')['followup_messages']
    assert len(extras) == 1 and extras[0]['turn'] == 1


def test_followups_do_not_duplicate_current_messages_or_identical_older_questions():
    s = discussion()
    question = 'Farm A, how did health change?'
    s['messages'] = [message(0, question), message(1, question),
                     message(2, 'Does anyone know which observation is missing?', 'C'),
                     message(4, question), message(5, 'One recent statement.')]
    extras = public_discussion(s, 'A')['followup_messages']
    assert len(extras) == 1 and extras[0]['sender'] == 'C'


def test_long_questions_with_same_excerpt_are_not_confused_with_one_another():
    s = discussion()
    prefix = 'Farm A, ' + 'I have been examining the observations from my own plants. ' * 4
    first, second = prefix+'What happened to health?', prefix+'What happened to growth?'
    s['messages'] = [message(1, first), message(4, second), message(5, 'Current contribution.')]
    assert public_discussion(s, 'A')['followup_messages'][0]['text'] == first


def test_new_output_cap_does_not_rewrite_historical_decisions():
    text = 'x' * 601
    assert Decision(message=text, pass_turn=False).message == text
    with pytest.raises(ValidationError):
        response_model(2, True).model_validate({'pass_turn': False, 'message': text})
    for branch in model_format(discussion(), 'A')['oneOf']:
        assert branch['properties']['message']['maxLength'] == 600


def test_replayed_legacy_window_is_bounded_without_mutating_the_saved_observation():
    s = discussion()
    obs = observation(s, 'A')
    obs.pop('followup_messages')
    obs['negotiation_messages'] = [message(0, 'Farm A, an old offer.')]
    before = dumps(obs)
    context = json.loads(prompt_messages(s, 'A', obs)[1]['content'])
    assert context['observation']['followup_messages'] == []  # An old offer is not a current direct question.
    assert 'negotiation_messages' not in context['observation']
    assert dumps(obs) == before


def test_reply_limit_requires_a_model_revision_preserves_raw_trace_and_never_truncates(tmp_path, monkeypatch):
    s = discussion()
    original = 'A long claim. ' * 55
    revised = 'B, I need the observed health change before deciding whether to try your method.'
    replies = iter([original, revised])
    requests = []
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'message': {'content': json.dumps({'pass_turn': False, 'message': next(replies)})}}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            requests.append(kwargs['json']); return Response()
    monkeypatch.setattr('farm.agents.httpx.AsyncClient', Client)
    store = Store(tmp_path/'short-replies.sqlite3'); rid = store.create(s)
    before = dumps(s)
    result = asyncio.run(model_decision(s, 'A', observation(s, 'A'), store, rid, '1:2:6:A'))
    assert result.message == revised and not result.contracts and len(requests) == 2
    assert original in store.calls(rid)[0]['raw_response']
    assert store.calls(rid)[0]['error'] and dumps(s) == before


def test_information_remains_private_until_the_model_chooses_to_publish_it():
    s = discussion()
    s['agents']['B']['memory'] = {'goal': 'PRIVATE_B_STRATEGY'}
    s['agents']['A']['memory'] = {'open_question': 'Which observation is missing?'}
    text = dumps(prompt_messages(s, 'A', observation(s, 'A')))
    assert 'PRIVATE_B_STRATEGY' not in text and 'Which observation is missing?' in text
    assert 'You need not share knowledge or cooperate' in text
    assert '600 characters' in text and 'AGREEMENT HOW-TO' in text
