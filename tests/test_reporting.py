import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from farm.agents import model_decision, model_format
from farm.engine import advance, new_game
from farm.knowledge import fee_report
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
    "I've reviewed my experiment plan and found that the comparison settled the effectiveness "
    "of watering my plants with 3.7 L each.",
    'The comparison confirmed that 3.7 L per seedling was effective.',
    '3.7 L each was effective in my experiment.',
    'The experiment at 3.7 L confirmed the best dose for my plants.',
])
def test_unsupported_trial_stories(text):
    assert describes_trial(text)


@pytest.mark.parametrize('text', [
    'Farm C claims its 50 plants died.', 'If I try 1.5 L, will they grow?',
    'Did your seedlings survive?', 'My plan is to compare two doses tomorrow.',
    'I have not yet tested 1.5 L.', 'I will keep enough coins for delivery.',
    'I have no measured plant results yet.',
    'Did your comparison establish whether 3.7 L per plant is useful?',
    'I plan to compare 1.7 L and 2.0 L per plant.',
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


def test_saved_bluff_citation_stays_unverified_and_recall_requires_a_claim_query(tmp_path):
    s = game(first=2)
    store = Store(tmp_path/'claims.db')
    rid = store.create(s)
    claim = 'Watering with 1.1 L per plant reliably gives healthy growth.'
    advance(s, {'C': Decision(pass_turn=False, message=claim, private_bluff_reason='Sell a rival on a weak dose.')})
    store.save(rid, s)
    choice = decide(s, 'A', store, rid, [{'pass_turn': True, 'memory': {
        'insight': 'Verify the reported dose in a small comparison.', 'based_on': 'message:1'}}])
    advance(s, {'A': choice})
    store.save(rid, s)
    s = store.load(rid)
    s.update(round=2, phase=3, turn=0)
    a = s['agents']['A']
    a['recall_query'] = 'Farm C water'
    ordinary = observation(s, 'A', store=store, rid=rid)
    assert ordinary['own_farm']['memory_provenance']['insight'] == {
        'status': 'unverified_claim', 'source': 'message:1', 'source_status': 'unverified_claim',
        'sender': 'C', 'round': 1, 'phase': 2, 'turn': 0}
    assert not any(row['kind'] == 'claim' for row in ordinary['recalled_experiences'])
    a['recall_query'] = 'What did Farm C say about water?'
    [quote] = observation(s, 'A', store=store, rid=rid)['recalled_experiences']
    assert quote['text'] == claim and quote['source_type'] == 'unverified_peer_claim'
    assert 'insight' not in observation(s, 'B')['own_farm'].get('memory_provenance', {})


def test_order_revision_and_actual_farm_work_can_avoid_a_fractional_return(tmp_path):
    s = game(phase=3)
    store = Store(tmp_path/'fit.db')
    rid = store.create(s)
    sowing = [{'count': 1, 'water_per_plant': '3.4'}, {'count': 2, 'water_per_plant': '2'}]
    a = s['agents']['A']
    a.update(planned_sowing=sowing, planned_irrigation=[])
    own = observation(s, 'A')['own_farm']
    assert [(q['delivery_liters'], q['shortfall_liters'], q['unused_liters'], q['return_fee_coins'])
            for q in own['whole_order_choices']] == [(0, '7.4', '0', 0), (7, '0.4', '0', 0), (8, '0', '0.6', 40)]
    revision = [{'count': 1, 'water_per_plant': '3'}, {'count': 2, 'water_per_plant': '2'}]
    order = decide(s, 'A', store, rid, [{'request': 8}, {'request': 7, 'planned_sowing': revision, 'planned_irrigation': []}])
    advance(s, {'A': order, 'B': Decision(request=0), 'C': Decision(request=0)})
    assert a['planned_sowing'] == revision and a['delivered'] == 7
    work = decide(s, 'A', store, rid, [
        {'new_plants': [{'count': 1, 'water_per_plant': '2.9'}, revision[1]]},
        {'new_plants': revision},
    ])
    fees = [c['water_return_quote'] for c in store.calls(rid) if c['water_return_quote']]
    assert [q['unused_liters'] for q in fees] == ['0.6', '0.1']
    advance(s, {'A': work})
    advance(s)
    advance(s)
    assert s['history'][-1]['agents']['A']['return_fee'] == 0
    assert s['history'][-1]['agents']['A']['used'] == 7


@pytest.mark.parametrize('enabled,attempts', [(True, 2), (False, 1)])
def test_farm_can_keep_a_measured_dose_and_choose_to_pay_for_the_rest(tmp_path, enabled, attempts):
    s = game(phase=4)
    s['config']['return_fee_enabled'] = enabled
    s['agents']['A']['delivered'] = 3
    store = Store(tmp_path/'return.db')
    rid = store.create(s)
    work = {'new_plants': [{'count': 1, 'water_per_plant': '2.9'}]}
    choice = decide(s, 'A', store, rid, [work] * attempts)
    calls = store.calls(rid)
    assert len(calls) == attempts and choice.new_plants[0].water_per_plant == '2.9'
    if enabled:
        assert '0.1 L' in calls[1]['request']['messages'][-1]['content']
        assert '40 coins' in calls[1]['request']['messages'][-1]['content']


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


def test_a_repeated_false_premise_and_trial_never_reach_the_next_farm(tmp_path):
    s = game()
    store = Store(tmp_path/'claims.db')
    rid = store.create(s)
    draft = {'pass_turn': False, 'message': "My comparison settled the effectiveness of 3.7 L per plant. "
             "Can you elaborate on the recent delivery fee increase?",
             'memory': {'open_question': 'Does a second trial confirm this?'},
             'contracts': [{'kind': 'propose', 'start_round': 1, 'end_round': 2,
                            'limits': {'A': {'max_request': 6}, 'B': {'max_request': 6}}}]}
    d = decide(s, 'A', store, rid, [draft, draft])
    advance(s, {'A': d})
    store.save(rid, s)
    saved = store.load(rid)
    assert len(store.calls(rid)) == 2
    assert all(c['fee_claim_review'] and 'message' in c['trial_report_review'] for c in store.calls(rid))
    peer = observation(saved, 'B', store=store, rid=rid)
    assert peer['messages'][0]['text'] == '' and peer['agreements'][0]['signatures'] == ['A']
    assert '3.7' not in dumps(peer) and saved['agents']['A']['memory']['open_question']


def test_echo_becomes_a_free_pass_but_an_actual_signature_still_reaches_peers(tmp_path):
    s = game()
    store = Store(tmp_path/'echo.db')
    rid = store.create(s)
    text = "Can you share any insights or results from your experiment?"
    proposal = {'kind': 'propose', 'start_round': 1, 'end_round': 2,
                'limits': [{'agent_id': a, 'max_request': 6} for a in 'AB']}
    advance(s, {'A': Decision(pass_turn=False, message=text, contracts=[proposal])})
    accept = {'pass_turn': False, 'message': text, 'contracts': [{'kind':'accept','contract_id':'c1'}]}
    advance(s, {'B': decide(s, 'B', store, rid, [accept])})
    echo = {'pass_turn': False, 'message': text, 'memory': {'insight': 'Ask about one specific dose.'}}
    advance(s, {'C': decide(s, 'C', store, rid, [echo])})
    assert [m['text'] for m in s['messages']] == [text, '']
    assert s['contracts'][0]['status'] == 'active'
    assert s['conversation_budget']['messages_used'] == {'A':1, 'B':1, 'C':0}
    assert s['agents']['C']['memory']['insight'] == echo['memory']['insight']
    s.update(round=2, phase=2, turn=0)
    assert decide(s, 'B', store, rid, [echo]).pass_turn
    fresh = {'pass_turn': False, 'message': 'Farm C, what happened at 1.7 L this round?'}
    assert decide(s, 'B', store, rid, [fresh]).message == fresh['message']


def test_official_contract_caps_cannot_be_presented_as_a_fee_cap_or_irrigation_dose(tmp_path):
    s = game()
    store = Store(tmp_path/'scope.db')
    rid = store.create(s)
    false_terms = {'pass_turn': False, 'message': 'The contract will cap our delivery fees at 20 coins per farm. '
                   'It will limit our water usage to 2.5 L per plant.'}
    assert decide(s, 'A', store, rid, [false_terms, false_terms]).pass_turn
    assert all(c['agreement_scope_review'] for c in store.calls(rid))
    honest = {'pass_turn': False, 'message': 'The proposed contract limits requests to 10 L per farm. '
              'I will limit watering to 2.5 L per plant.'}
    assert decide(s, 'A', store, rid, [false_terms, honest]).message == honest['message']
    mixed = {'pass_turn': False, 'message': "The proposal is to limit the delivery fee to 10 coins per farm, "
             "not to cap the water usage or fees."}
    assert decide(s, 'A', store, rid, [mixed, mixed]).pass_turn
    assert store.calls(rid)[-1]['fee_claim_review'] and store.calls(rid)[-1]['agreement_scope_review']


def test_delivery_rules_and_verbal_passes_on_public_turns(tmp_path):
    s = game()
    store = Store(tmp_path/'public-water.db')
    rid = store.create(s)
    draft = {'pass_turn': False, 'message': "I'd like to order 2.5 L to account for water loss during transport."}
    assert decide(s, 'A', store, rid, [draft, draft]).pass_turn
    assert store.calls(rid)[-1]['water_rule_review']
    treatment = {'pass_turn': False, 'message': 'I will request 5 L and try 2.5 L per seedling.'}
    assert decide(s, 'A', store, rid, [treatment]).message == treatment['message']
    spoken = {'pass_turn': False, 'message': "I'm considering the latest question from Farm B, but I don't have "
              "any new information to share. I'll pass for now."}
    assert decide(s, 'A', store, rid, [spoken]).pass_turn
    assert store.calls(rid)[-1]['spoken_pass']


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


def test_public_fee_reference_quotes_active_settings_and_combines_with_an_owner_record(tmp_path):
    s = game()
    s['config'].update(delivery_fee_coins=7, return_fee_enabled=False)
    store = Store(tmp_path/'fees.db')
    rid = store.create(s)
    tariffs = fee_report(s['config'])
    assert '7 coins for a positive delivery and 0 coins for a positive return' in tariffs
    draft = {'pass_turn': False, 'message': '[[fees]]. [[trial]]'}
    d = decide(s, 'A', store, rid, [draft])
    assert d.message == tariffs + ' I have no measured plant results yet.'
    invalid = {'pass_turn': False, 'message': 'It is false that [[fees]]'}
    assert decide(s, 'A', store, rid, [invalid, invalid]).pass_turn


def test_farm_can_answer_with_its_own_settled_water_instead_of_repeating_the_question(tmp_path):
    s = game(phase=3)
    store = Store(tmp_path/'water.db')
    rid = store.create(s)
    advance(s, {a: Decision(request=3 if a=='A' else 0) for a in s['agents']})
    advance(s, {'A': Decision(new_plants=[{'count': 1, 'water_per_plant': '1.7'}])})
    advance(s)
    advance(s)
    advance(s)
    advance(s, {'B': Decision(pass_turn=False, message='Farm A, what were the results of your experiment?')})
    store.save(rid, s)
    owner = observation(s, 'A', store=store, rid=rid)['recalled_experiences'][0]
    assert owner['kind'] == 'plant' and owner['water_per_plant'] == '1.7'
    drafts = [{'pass_turn': False, 'message': '[[water]]'}]
    assert decide(s, 'A', store, rid, drafts).message == (
        'In round 1 I received 3 L, used 1.7 L and returned 1.3 L. '
        'I paid 20 coins for delivery and 40 coins for returns.')
    assert 'received 0 L' in decide(s, 'B', store, rid, drafts).message
    mixed = {'pass_turn': False, 'message': "I plan to use 2 L, which is less than the 3 L I received and used last round."}
    corrected = decide(s, 'A', store, rid, [mixed, {'pass_turn': False, 'message': 'I plan to use 2 L. [[water]]'}])
    assert corrected.message.startswith('I plan to use 2 L. In round 1 I received 3 L, used 1.7 L')
    assert decide(s, 'B', store, rid, [mixed, mixed]).pass_turn
    stock = {'pass_turn': False, 'message': 'I have 10 L of water available, so I can meet my needs.'}
    assert decide(s, 'A', store, rid, [stock, stock]).pass_turn
    conditional = {'pass_turn': False, 'message': 'If I have 10 L available after my next delivery, I will test 2 L per plant.'}
    assert decide(s, 'A', store, rid, [conditional]).message == conditional['message']


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
