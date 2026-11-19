import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from farm.agents import model_decision, model_format
from farm.engine import advance, new_game
from farm.reporting import REPORT_TOKEN, describes_trial, grounded_text, trial_report
from farm.schema import Config, Decision
from farm.store import Store, dumps
from farm.views import observation


ANECDOTE = ("I've had some success with a 50-plant trial using 200 units of water, "
            "but I've also seen some plants die off with the same dose.")
PROFILES = ['short_term', 'reciprocal', 'cunning_experimenter']


@pytest.mark.parametrize('text', [
    ANECDOTE, 'I tested 1.5 L.', 'We observed improved seedling health.',
    'Farm C claims 4 L worked, and I also tested it on my plants.',
    'Why did my 50 seedlings die at 4 L?', 'My plants are thriving at 2 L.',
    'At 4 L: 100% survival.', 'In one trial, a 20-coin delivery led to a 10% increase in growth.',
])
def test_unsupported_trial_stories(text):
    assert describes_trial(text)


@pytest.mark.parametrize('text', [
    'Farm C claims its 50 plants died.', 'If I try 1.5 L, will they grow?',
    'Did your seedlings survive?', 'My plan is to compare two doses tomorrow.',
    'I have not yet tested 1.5 L.', 'I will keep enough coins for delivery.',
    'I have no measured plant results yet.',
])
def test_free_discussion_and_hypotheses(text):
    assert not describes_trial(text)


def game(phase=2, first=0):
    s = new_game(Config(agent_count=3, profiles=PROFILES, communication=True, start_agent=first))
    s['phase'] = phase
    return s


def decide(s, aid, store, rid, drafts):
    replies = iter(drafts)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'message': {'content': json.dumps(next(replies))}}))
    local_client = httpx.AsyncClient
    with patch('farm.agents.httpx.AsyncClient', side_effect=lambda **kw: local_client(transport=transport)):
        return asyncio.run(model_decision(s, aid, observation(s, aid, store=store, rid=rid),
                                          store, rid, f"{s['round']}:{s['phase']}:{s['turn']}:{aid}"))


def test_second_unverified_story_preserves_offer_and_previous_private_note(tmp_path):
    s = game()
    s['agents']['A']['memory'] = {'insight': 'Keep a cash reserve.'}
    store = Store(tmp_path/'game.db')
    rid = store.create(s)
    action = {'kind': 'propose', 'start_round': 1, 'end_round': 2, 'limits': {'A': {'max_request': 20}}}
    draft = {'pass_turn': False, 'message': ANECDOTE, 'contracts': [action],
             'memory': {'insight': ANECDOTE, 'open_question': 'What did Farm C actually measure?'}}
    d = decide(s, 'A', store, rid, [draft, draft])
    assert not d.message and not d.pass_turn
    advance(s, {'A': d})
    assert s['contracts'][0]['signatures'] == ['A']
    assert s['agents']['A']['memory'] == {
        'insight': 'Keep a cash reserve.', 'open_question': 'What did Farm C actually measure?'}
    assert set(store.calls(rid)[-1]['withheld_fields']) == {'memory.insight', 'message'}


def test_marked_bluff_survives_checkpoint_without_becoming_a_fact(tmp_path):
    s = game(first=2)
    store = Store(tmp_path/'game.db')
    rid = store.create(s)
    reason = 'Encourage a rival to pay for an oversized delivery.'
    draft = {'pass_turn': False, 'message': ANECDOTE, 'private_bluff_reason': reason,
             'memory': {'insight': ANECDOTE}}
    d = decide(s, 'C', store, rid, [draft, draft])
    advance(s, {'C': d})
    store.save(rid, s)
    s = store.load(rid)
    own = observation(s, 'C')['own_farm']
    assert own['last_deliberate_bluff']['intended_benefit'] == reason
    assert own['last_deliberate_bluff']['statement'] == ANECDOTE
    assert not own['memory'] and not own['recent_plant_results']
    peer = observation(s, 'A')
    assert peer['messages'][0]['source_type'] == 'unverified_peer_claim'
    assert peer['messages'][0]['text'] == ANECDOTE and reason not in dumps(peer)
    assert reason not in dumps(s['messages'])


def test_unmarked_claim_cannot_be_relabelled_as_bluff_after_review(tmp_path):
    s = game(first=2)
    store = Store(tmp_path/'game.db')
    rid = store.create(s)
    draft = {'pass_turn': False, 'message': ANECDOTE, 'private_bluff_reason': 'N/A'}
    d = decide(s, 'C', store, rid, [draft, {**draft, 'private_bluff_reason': 'Mislead rival farms.'}])
    assert d.pass_turn and not d.message and not d.private_bluff_reason


def test_revision_can_attribute_a_peer_and_request_evidence(tmp_path):
    s = game()
    store = Store(tmp_path/'game.db')
    rid = store.create(s)
    question = 'Farm C claims 50 plants received the same dose. Which outcomes did you actually measure?'
    d = decide(s, 'A', store, rid, [{'pass_turn': False, 'message': ANECDOTE},
                                     {'pass_turn': False, 'message': question}])
    assert d.message == question and not d.pass_turn
    assert [c['trial_report_review'] for c in store.calls(rid)] == [['message'], []]


def test_real_result_rendered_only_for_its_owner(tmp_path):
    s = game(phase=4)
    s['agents']['A']['delivered'] = 3
    advance(s, {'A': Decision(new_plants=[{'count': 2, 'water_per_plant': '1.5'}])})
    advance(s)
    s.update(phase=7, news_ready=True)
    store = Store(tmp_path/'game.db')
    rid = store.create(s)
    literal = trial_report(s['agents']['A'], observation(s, 'A'))
    assert '2 seedlings received 1.5 L each' in literal and 'health' in literal
    d = decide(s, 'A', store, rid, [{'pass_turn': False, 'message': '[[trial]] Did yours survive?'}])
    assert d.message == literal + ' Did yours survive?'
    assert trial_report(s['agents']['B'], observation(s, 'B')) == 'I have no measured plant results yet.'
    assert grounded_text('It is false that [[trial]]', literal, 600) is None
    assert grounded_text(REPORT_TOKEN, literal, 5) is None
    obs = observation(s, 'A')
    obs['own_farm']['recent_plant_results'] = []
    assert 'no matching' in trial_report(s['agents']['A'], obs)


def test_all_profiles_make_distinct_private_choices(tmp_path):
    s = game(phase=1)
    store = Store(tmp_path/'game.db')
    rid = store.create(s)
    moves = [
        ('A', 'cash_plan', 'cash reserve', 'Hold enough coins for another delivery.'),
        ('B', 'partner_plan', 'Farm C', 'Ask which result C can corroborate.'),
        ('C', 'experiment_plan', 'survival', 'Compare two doses and keep the survivor count private.')]
    decisions = {}
    for aid, field, focus, move in moves:
        schema = model_format(s, aid)['$defs']['WorkingNotes']
        assert schema['required'] == [field]
        assert focus in schema['properties'][field]['properties']['focus']['enum']
        decisions[aid] = decide(s, aid, store, rid, [
            {'planned_sowing': [], 'memory': {field: {'focus': focus, 'next_move': move}}}])
    advance(s, decisions)
    for aid, _, focus, move in moves:
        assert observation(s, aid)['own_farm']['memory']['goal'] == f'{focus} — {move}'
        for other in s['agents'].keys() - {aid}:
            assert move not in dumps(observation(s, other))
    s['config']['communication'] = False
    s['phase'] = 1
    schema = model_format(s, 'B')['$defs']['WorkingNotes']
    assert schema['properties']['partner_plan']['properties']['focus']['enum'] == ['independent check']


def test_checkpoint_keep_close_and_visible_citation(tmp_path):
    s = game(phase=1)
    store = Store(tmp_path/'notes.db')
    rid = store.create(s)
    day_one = {'planned_sowing': [], 'memory': {'cash_plan': {'focus': 'cash reserve', 'next_move': 'Wait.'},
               'open_question': 'Can I afford another order?', 'based_on': 'accounts'}}
    d = decide(s, 'A', store, rid, [day_one])
    store.accept(rid, '1:1:0:A', 'A', d.model_dump(), observation(s, 'A'))
    reopened = Store(tmp_path/'notes.db')
    advance(s, {'A': Decision.model_validate(reopened.decision(rid, '1:1:0:A'))})
    reopened.save(rid, s)
    changes = reopened.note_history(rid, 'A')['changes']
    assert len(changes) == 2 and all(c['evidence']['record']['id'] == 'A' for c in changes)
    assert not reopened.note_history(rid, 'B')['changes']
    s = reopened.load(rid)
    s.update(round=2, phase=1)
    keep = {'planned_sowing': [], 'memory': {'cash_plan': 'keep'}}
    advance(s, {'A': decide(s, 'A', reopened, rid, [keep])})
    reopened.save(rid, s)
    assert len(reopened.note_history(rid, 'A')['changes']) == 2
    s['phase'] = 3
    close = {'request': 0, 'memory': {'open_question': '', 'based_on': 'recall:99'}}
    d = decide(s, 'A', reopened, rid, [close])
    assert d.note_evidence is None
    advance(s, {'A': d})
    reopened.save(rid, s)
    latest = reopened.note_history(rid, 'A')['changes'][0]
    assert latest['round'] == 2 and latest['previous'] == day_one['memory']['open_question']
    assert latest['value'] is None and latest['evidence'] is None
    assert s['agents']['A']['memory'] == {'goal': 'cash reserve — Wait.'}
    assert 'Can I afford another order?' not in dumps(observation(s, 'A'))
    assert any(e['kind'] == 'note_changed' for e in reopened.export(rid)['events'])
