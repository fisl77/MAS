import asyncio
from fractions import Fraction
import json

import pytest

from farm.agents import model_decision, model_format, prompt_messages, scripted
from farm.contracts import apply_contract_action
from farm.conversation import exchange_references
from farm.engine import advance, farm_work, grow, new_game, validate_decision
from farm.learning import apply_review, learning_context, review_choices
from farm.runner import Runner
from farm.schema import Config, ContractAction, Decision, NotebookEdit, RoundReview
from farm.store import Store
from farm.views import observation


def review(source='accounts', choice='keep_strategy', conclusion='Use the settled account to plan.'):
    return RoundReview(source=source, choice=choice, conclusion=conclusion,
                       next_intent='Compare my total planned irrigation with the order.',
                       long_term_goal='Finance the next harvest.')


def model_view(s, aid, store=None, rid=None):
    obs = observation(s, aid, store=store, rid=rid)
    return json.loads(prompt_messages(s, aid, obs)[1]['content'])['observation']


def test_whole_order_comparison_includes_both_plans_and_distinct_voluntary_caps(tmp_path, monkeypatch):
    s = new_game(Config(communication=True))
    a = s['agents']['A']
    a['plants'] = [{'id': 'A-p1', 'count': 2, 'growth': 20, 'health': 18, 'water': Fraction(1), 'new': False}]
    advance(s, {'A': Decision(planned_sowing=[{'count': 2, 'water_per_plant': '2'}],
                              planned_irrigation=[{'group_id': 'A-p1', 'count': 2, 'water_per_plant': '3'}])})
    apply_contract_action(s, 'A', ContractAction(kind='propose', start_round=1, end_round=1,
                          limits=[{'agent_id': 'A', 'max_request': 12, 'max_net': '9'}]))
    s['phase'] = 3
    own = observation(s, 'A')['own_farm']
    assert own['planned_total_liters'] == '10' and own['planned_irrigation_liters'] == '6'
    assert own['order_if_following_plan']['unused_liters'] == '0'
    assert [(c['max_request'], c['max_net']) for c in own['effective_voluntary_caps']] == [(12, '9')]
    assert 'planned_irrigation' not in observation(s, 'B')['own_farm']
    validate_decision(s, 'A', Decision(request=15))
    requests = []

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, path, json):
            requests.append(json)
            return self
        def raise_for_status(self): pass
        def json(self): return {'message': {'content': '{"request":15}'}}

    monkeypatch.setattr('farm.agents.httpx.AsyncClient', Client)
    store = Store(tmp_path/'water.sqlite3')
    rid = store.create(s)
    choice = asyncio.run(model_decision(s, 'A', observation(s, 'A'), store, rid, '1:3:0:A'))
    assert choice.request == 15 and len(requests) == 2
    reminder = requests[1]['messages'][-1]['content']
    assert all(term in reminder for term in ('15 L', '5 L', '10 L', '40 coins', '20 coins'))
    advance(s, {'A': choice, 'B': Decision(request=0)})
    assert observation(s, 'A')['own_farm']['actual_delivery_against_plan']['unused_liters'] == '5'
    advance(s, {'A': Decision(new_plants=a['planned_sowing'], irrigation=a['planned_irrigation'])})
    advance(s)
    advance(s)
    advance(s)
    assert observation(s, 'A')['own_agreement_results'][0]['own_result'] == {
        'status': 'breached', 'request_met': False, 'net_met': False}


def test_coin_projection_includes_archived_accounts_news_and_evidence(tmp_path):
    s = new_game(Config())
    a = s['agents']['A']
    a.update(bank=34_025, debt=25, profit=-16_000, fees=6_000, delivery_fee=2_000, return_fee=4_000, revenue=125)
    s['news']['bank_ranking'] = [50_000, 34_025]
    obs = observation(s, 'A')
    obs['recalled_experiences'] = [{'kind':'accounts', 'fees':6_000, 'profit_change':-5_875}]
    messages = prompt_messages(s, 'A', obs)
    shown = json.loads(messages[1]['content'])['observation']
    own = shown['own_farm']
    assert [own[k] for k in ('bank','debt','net_balance','delivery_fee','return_fee','revenue','profit')] == [
        340.25, 0.25, 340, 20, 40, 1.25, -160]
    assert shown['news']['bank_ranking'] == [500, 340.25]
    assert shown['recalled_experiences'][0]['profit_change'] == -58.75
    assert obs['own_farm']['bank'] == 34_025
    s.update(phase=7, news_ready=True, review_pending=True)
    assert 'Cash 340.25 coins' in model_view(s,'A')['private_round_records']['accounts']
    assert all('cents' not in m['content'] for m in messages)


def test_dead_crop_is_citable_and_revisions_are_only_retrieved_by_owner_in_same_game(tmp_path):
    s = new_game(Config())
    farm_work(s, 'A', Decision(new_plants=[{'count':2, 'water_per_plant':'1'}]))
    grow(s)
    assert not s['agents']['A']['plants']
    s.update(phase=7, news_ready=True, review_pending=True)
    store = Store(tmp_path/'archive.sqlite3')
    rid = store.create(s)
    first = review('plant:1', 'add_lesson', 'The first trial lost both seedlings.')
    first.working_note = NotebookEdit(target='new', title='Trial ledger', text='Compare a different dose.')
    advance(s, {'A': Decision(review=first), 'B': scripted(s,'B')})
    store.save(rid, s)
    s.update(phase=7, news_ready=True, review_pending=True)
    advance(s, {'A': Decision(review=review('accounts', 'retire_lesson:1', 'Revisit the evidence before generalizing.')),
                'B': scripted(s,'B')})
    store.save(rid, s)
    assert 'lesson:1' not in s['agents']['A']['learning']['entries']
    archive = store.recall_reviews(rid, 'A', 'archive lesson:1')
    assert len(archive) == 2 and archive[1]['evidence']['record']['outcome'] == 'died'
    assert archive[0]['changes'][0]['previous']['text'] == first.conclusion
    assert not store.recall_reviews(rid, 'B', 'archive lesson:1') and not store.recall_reviews('other','A','archive')
    s['agents']['A']['recall_query'] = 'archive lesson:1'
    assert 'Trial ledger' in json.dumps(model_view(s,'A',store,rid))
    assert 'Trial ledger' not in json.dumps(model_view(s,'B',store,rid))


def test_full_notebook_requires_owner_to_select_replacement():
    s = new_game(Config())
    a = s['agents']['A']
    for r in range(1, 13):
        s['round'] = r
        item = review('water', 'add_lesson', f'Observation from round {r}')
        apply_review(s, 'A', item)
    assert 'add_lesson' not in review_choices(a)
    assert len(learning_context(a, 3)['entries']) == 3 and len(learning_context(a, 7, True)['entries']) == 12
    s.update(phase=7, news_ready=True, review_pending=True)
    with pytest.raises(ValueError):
        validate_decision(s,'A',Decision(review=review('water','add_lesson')))
    replacement = review('water','revise_lesson:4','Check the forecast before ordering.')
    validate_decision(s,'A',Decision(review=replacement))
    change = apply_review(s, 'A', replacement)['changes'][0]
    assert change['slot'] == 'lesson:4' and change['previous']['round'] == 4
    assert len(a['learning']['entries']) == 12


@pytest.mark.parametrize('claim', ['Actual water usage was 0 liters.', 'Water usage was less than planned.'])
def test_cited_record_survives_a_contradictory_interpretation_without_changing_intent(claim):
    s = new_game(Config())
    a = s['agents']['A']
    a.update(planned_sowing=[{'count':5,'water_per_plant':'1'}], used=Fraction(5), request=5, delivered=5)
    decision = review('water','add_lesson',claim)
    record = apply_review(s, 'A', decision)
    assert record['conclusion'] == claim and 'conclusion' in record['measurement_conflicts']
    memory = learning_context(a, 1)
    assert memory['next_intent'] == decision.next_intent
    assert 'used 5 L (as planned)' in memory['entries']['lesson:1']['text']
    assert claim not in memory['entries']['lesson:1']['text']


def test_confirming_a_hypothesis_does_not_turn_it_into_a_measured_record():
    s = new_game(Config())
    a = s['agents']['A']
    apply_review(s, 'A', review('water', 'add_lesson', 'A different planting mix might save coins.'))
    apply_review(s, 'A', review('accounts', 'confirm_lesson:1', 'I still want to test the mix.'))
    apply_review(s, 'A', review('accounts', 'add_lesson', '[[record]]'))
    lessons = learning_context(a, 7, review=True)['entries']
    assert lessons['lesson:1']['evidence_status'] == 'hypothesis'
    assert lessons['lesson:1']['source'] == 'water'
    assert lessons['lesson:2']['evidence_status'] == 'observed'


def test_review_clarification_shows_the_real_amount_and_accepts_the_farms_new_strategy(tmp_path, monkeypatch):
    s = new_game(Config())
    s.update(phase=7, news_ready=True, review_pending=True)
    s['agents']['A'].update(used=Fraction(5), planned_sowing=[{'count':1,'water_per_plant':'5'}], delivered=5)
    wrong = review('water','add_lesson','Actual water usage was 0 liters.')
    corrected = review('water','add_question','Can I afford to compare another dose?')
    corrected.next_intent = 'Allocate one plant to a comparison.'
    replies = iter([wrong,corrected])
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return self
        def raise_for_status(self): pass
        def json(self):
            return {'message':{'content':json.dumps({'review':next(replies).model_dump()})}}
    monkeypatch.setattr('farm.agents.httpx.AsyncClient', Client)
    st = Store(tmp_path/'review.sqlite3')
    rid = st.create(s)
    accepted = asyncio.run(model_decision(s,'A',observation(s,'A'),st,rid,'1:7:0:A:review'))
    calls = st.calls(rid)
    assert len(calls) == 2 and calls[0]['review_measurement_conflicts'] and not calls[1]['review_measurement_conflicts']
    assert 'water used was 5' in calls[1]['request']['messages'][-1]['content']
    assert accepted.review == corrected


def test_full_questions_and_named_notes_can_be_replaced_or_closed():
    s = new_game(Config())
    for n in range(6):
        s['round'] = n+1
        item = review(choice='add_question' if n < 3 else 'keep_strategy', conclusion=f'What about dose {n}?')
        item.working_note = NotebookEdit(target='new', title=f'Trial {n}', text='Follow up after harvest.')
        apply_review(s, 'A', item)
    s.update(phase=7, news_ready=True, review_pending=True)
    schema = model_format(s,'A')
    assert 'add_question' not in schema['$defs']['RoundReview']['properties']['choice']['enum']
    assert 'new' not in schema['$defs']['NotebookEdit']['properties']['target']['enum']
    item = review(choice='close_question:1')
    item.working_note = NotebookEdit(target='note:5', title='Retested', text='Repeat the comparison.')
    validate_decision(s,'A',Decision(review=item))
    record = apply_review(s,'A',item)
    assert record['changes'][1]['previous']['title'] == 'Trial 4'
    assert 'add_question' in review_choices(s['agents']['A'])


def test_exchange_shows_attributed_question_own_stance_and_existing_reply():
    s = new_game(Config(agent_count=3, communication=True))
    s['phase'] = 2
    for aid, text in [('A','I can accept a cap of 12 liters.'), ('C','Farm B, how much was your delivery fee?'),
                      ('B','Our delivery fee was 20 coins.')]:
        s['messages'].append({'round':1,'phase':2,'turn':len(s['messages']),'sender':aid,'text':text})
    refs = exchange_references(s, 'A')
    assert refs['your_last_statement']['sender'] == 'A'
    assert refs['latest_question']['sender'] == 'C'
    assert refs['published_reply_to_consider']['text'] == 'Our delivery fee was 20 coins.'
    assert refs['published_reply_to_consider']['source_type'] == 'unverified_peer_claim'
    shown = model_view(s, 'A')
    assert shown['exchange']['published_reply_to_consider']['reference'] == 'messages:1'
    assert shown['messages'][0]['source_type'] == 'unverified_peer_claim'


def test_caps_are_effective_in_time_and_only_include_the_owners_bounds():
    s = new_game(Config(communication=True))
    s['phase'] = 2
    for aid, when, cap in [('A', 1, 11), ('A',2,41), ('B',1,500)]:
        apply_contract_action(s, aid, ContractAction(kind='propose', start_round=when, end_round=when+1,
                              limits=[{'agent_id':aid,'max_request':cap}]))
    s['phase'] = 3
    assert [c['max_request'] for c in model_view(s,'A')['own_farm']['effective_voluntary_caps']] == [11]
    s['contracts'][0]['cancelled_from']['A'] = 2
    s['round'] = 2
    assert [c['max_request'] for c in model_view(s,'A')['own_farm']['effective_voluntary_caps']] == [41]
    validate_decision(s, 'A', Decision(request=50))


@pytest.mark.parametrize('communication', [True, False])
def test_final_private_reviews_resume_once_without_publication_or_new_charges(tmp_path, monkeypatch, communication):
    async def play():
        store = Store(tmp_path/'resume.sqlite3')
        s = new_game(Config(communication=communication, controller='ollama', rounds=1))
        s.update(phase=7, news_ready=True, review_pending=True)
        rid = store.create(s)
        runner = Runner(store)
        seen = []
        async def models(): return [{'name':'llama3.1:8b','digest':'fixture'}]
        async def choose(state, aid, obs, *args):
            assert 'private_round_records' in obs
            assert 'contracts' not in model_format(state,aid)['properties']
            seen.append(aid)
            if aid == 'A':
                runner.pause(rid)
            return scripted(state, aid)
        monkeypatch.setattr('farm.runner.list_models', models)
        monkeypatch.setattr('farm.runner.model_decision', choose)
        runner.start(rid)
        await runner.task
        assert store.load(rid)['status'] == 'paused' and store.decision(rid,'1:7:0:A:review')
        assert not store.events(rid)
        runner = Runner(Store(store.path))
        runner.start(rid)
        await runner.task
        events = store.events(rid)
        assert seen == ['A','B'] and store.load(rid)['status'] == 'completed'
        assert [e['kind'] for e in events] == ['round_review','round_review','completed']
        assert [e['choice'] for e in events[:2]] == ['keep_strategy','keep_strategy']
    asyncio.run(play())
