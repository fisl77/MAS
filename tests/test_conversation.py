import pytest

from farm.conversation import is_repeated_message, speaker_order
from farm.engine import advance, new_game
from farm.schema import Config, Decision
from farm.store import dumps, loads
from farm.views import observation
from farm.conversation import (fee_claim_needs_review, payment_conflict, repeats_public_text, repeats_without_progress,
                               turn_messages, unsupported_agreement_terms)
from farm.agents import model_decision, model_format, scripted
from farm.store import Store
import asyncio
import json


@pytest.mark.parametrize('text',[
    'Our limit remains 150 liters and we do not need a new agreement.',
    'OUR LIMIT REMAINS 150 LITERS AND WE DO NOT NEED A NEW AGREEMENT!',
    'Our limit is still 150 liters and we do not need a new agreement.',
])
def test_reworded_statement_is_still_a_repetition(text):
    assert is_repeated_message(text,['Our limit remains 150 liters and we do not need a new agreement.'])


@pytest.mark.parametrize('text',[
    'Our limit remains 180 liters and we do not need a new agreement.',
    'Our limit remains 150 liters and we need a new agreement.',
    'Our limit remains 150 liters and we do not need a new agreement. Will you accept c2?',
    'Our limit remains 150 liters and we do not need a new agreement?',
])
def test_new_terms_polarity_and_questions_are_not_silenced(text):
    assert not is_repeated_message(text,['Our limit remains 150 liters and we do not need a new agreement.'])


@pytest.mark.parametrize('text',[
    'I will return 150 liters for my existing plants today.',
    'I will request 150 liters for my existing plants tomorrow.',
])
def test_changed_action_or_timing_is_not_a_repetition(text):
    assert not is_repeated_message(text,['I will request 150 liters for my existing plants today.'])


def test_similarly_worded_new_question_gets_an_answer_opportunity():
    assert not is_repeated_message(
        'Can you tell me whether selling plants with this budget is sensible?',
        ['Can you tell me whether buying plants with this budget is sensible?'])


def test_old_generic_question_with_copied_preamble_is_an_echo_but_a_new_topic_or_observation_is_not():
    s = discussion()
    s['round'] = 3
    previous = "I'd like to ask Farm C about their experiment plan. Can you share any insights from your experiment?"
    s['messages'] = [{'round': 2, 'phase': 7, 'turn': 2, 'sender': 'B', 'text': previous}]
    wrapped = ("I've reviewed the latest question and published reply. " +
               previous.replace('Farm C about', 'Farm C for more information about').replace('Can you', 'Could you'))
    assert repeats_public_text(s, 'A', wrapped)
    assert not repeats_public_text(s, 'A', wrapped.replace('experiment plan', 'cash plan'))
    assert not repeats_public_text(s, 'A', wrapped.replace('Farm C', 'Farm B'))
    assert not repeats_public_text(s, 'A', "I can sign the new offer. " + previous)


def test_same_indirect_request_preserves_new_rounds_and_subjects():
    s = discussion()
    s['messages'] = [{'round': 1, 'phase': 2, 'turn': 0, 'sender': 'B', 'text':
        "I'd like to know if anyone has any information about the upcoming weather forecast for round 4. "
        "It might affect our water usage and delivery fees."}]
    ask = "I'd like to know more about the weather forecast for round 4 and how it might impact our water usage and delivery fees."
    assert repeats_public_text(s, 'A', ask)
    assert not repeats_public_text(s, 'A', ask.replace('round 4', 'round 5'))


def test_new_framing_with_the_same_question_is_an_echo_but_a_new_observation_is_not():
    s = discussion()
    advance(s, {'A': Decision(pass_turn=False, message=
        "I'd like to ask Farm B about their trial. Could you share your trial results?")})
    repeated = "I'm interested in Farm B's experiment. Can you describe your experiment findings?"
    assert repeats_public_text(s, 'B', repeated)
    fresh = "At 2 L my plants grew 10 points. Can you describe your experiment findings?"
    assert not repeats_public_text(s, 'B', fresh)
    assert not repeats_public_text(s, 'B', repeated.replace('Farm B', 'Farm A'))


def test_an_unanswered_question_is_delivered_once_until_someone_adds_a_message():
    s = discussion()
    advance(s, {'A': Decision(pass_turn=False, message='Farm B, what did you observe?')})
    assert turn_messages(s, 'B')[0]
    advance(s, {'B': Decision()})
    assert turn_messages(s, 'B') == ([], [])
    advance(s, {'A': Decision(pass_turn=False, message='Farm B, did your seedlings survive?')})
    assert 'seedlings' in turn_messages(s, 'B')[0][0]['text']


def test_same_invitation_to_discuss_water_is_an_echo_but_a_concrete_comparison_is_new():
    s = discussion()
    advance(s, {'A': Decision(pass_turn=False, message="I'd like to review our water usage.")})
    assert repeats_public_text(s, 'B', "Let's talk about how to manage the pond.")
    assert not repeats_public_text(s, 'B', "I'd like to discuss comparing 1.7 L with 2.4 L.")


def discussion(phase=2):
    s=new_game(Config(communication=True,rounds=2))
    s['phase']=phase;s['news_ready']=phase==7
    return s


def repeat(s, **overrides):
    phase = s['phase']
    for aid in speaker_order(s):
        decision = overrides.get(aid, Decision(pass_turn=False, message='My plan is unchanged; I will request 100 liters.'))
        advance(s, {aid: decision})
        if s['phase'] != phase or s['review_pending']:
            break


@pytest.mark.parametrize('phase',[2,7])
def test_two_stalled_passes_end_the_phase_and_preserve_original_messages(phase):
    s=discussion(phase)
    repeat(s);repeat(s)
    status=observation(s,'A')['conversation_status']
    assert status['stalled_passes']==1 and len(status['repeated_agents'])==1
    s=loads(dumps(s))
    repeat(s)
    if phase == 7:
        assert s['review_pending'] and not observation(s,'A')['conversation_status']['phase_open']
        advance(s, {aid: scripted(s, aid) for aid in s['agents']})
    assert s['phase']==(3 if phase==2 else 1)
    assert s['last_conversation_end']['reason']=='repetition'
    assert s['last_conversation_end']['turns']==5
    assert len(s['messages'])==5
    assert len([e for e in s['events'] if e['kind']=='message'])==5
    assert observation(s,'A')['conversation_status']['stalled_passes']==0


def test_new_message_or_changed_contract_resets_stall_counter():
    s=discussion();repeat(s);repeat(s)
    repeat(s,A=Decision(pass_turn=False,message='I propose a request cap of 90 liters instead.'))
    assert s['phase']==2 and s['conversation_progress']['stalled_passes']==0
    repeat(s);assert s['conversation_progress']['stalled_passes']==1
    repeat(s,A=Decision(pass_turn=False,message='My plan is unchanged; I will request 100 liters.',
        contracts=[{'kind':'propose','start_round':1,'end_round':2,'limits':[
            {'agent_id':'A','max_request':100},{'agent_id':'B','max_request':100}]}]))
    assert s['phase']==2 and s['conversation_progress']['stalled_passes']==0
    repeat(s,B=Decision(pass_turn=False,message='My plan is unchanged; I will request 100 liters.',
                       contracts=[{'kind':'accept','contract_id':s['contracts'][0]['id']}]))
    assert s['contracts'][0]['status']=='active' and s['conversation_progress']['stalled_passes']==0


def test_repeating_a_signature_without_changing_a_contract_is_not_progress():
    s=discussion()
    proposal=Decision(pass_turn=False,message='My plan is unchanged; I will request 100 liters.',
        contracts=[{'kind':'propose','start_round':1,'end_round':2,'limits':[
            {'agent_id':'A','max_request':100},{'agent_id':'B','max_request':100}]}])
    repeat(s,A=proposal)
    for _ in range(2):
        repeat(s,A=Decision(pass_turn=False,message='My plan is unchanged; I will request 100 liters.',
                           contracts=[{'kind':'accept','contract_id':s['contracts'][0]['id']}]))
    assert s['phase']==3 and s['last_conversation_end']['reason']=='repetition'
    assert s['contracts'][0]['signatures']==['A']


def test_each_public_phase_starts_with_a_fresh_stall_counter():
    s=discussion();repeat(s);repeat(s)
    s['phase']=7;s['news_ready']=True;s['turn']=0
    repeat(s)
    assert s['conversation_progress']['stalled_passes']==0
    assert s['phase']==7 and s['turn']==2


def test_each_speaker_can_express_first_consent_privately():
    s=discussion()
    for aid in ('A','B'):
        advance(s,{aid:Decision(pass_turn=False,message='I support a cap of 100 liters.',memory='DIFFERENT_PRIVATE_NOTES_'+aid)})
        assert s['conversation_progress']['novel_agents']==[aid]
    obs=observation(s,'A')
    assert 'DIFFERENT_PRIVATE_NOTES_B' not in dumps(obs)


def test_new_signature_is_preserved_even_when_its_text_echoes_a_peer():
    s=discussion()
    draft={'kind':'propose','start_round':1,'end_round':2,
           'limits':[{'agent_id':a,'max_request':37} for a in ('A','B')]}
    text='These limits protect the plants we intend to cultivate this round.'
    advance(s,{'A':Decision(pass_turn=False,message=text,contracts=[draft])})
    acceptance=Decision(pass_turn=False,message=text,contracts=[{'kind':'accept','contract_id':'c1'}])
    before=dumps(s)
    assert not repeats_without_progress(s,'B',acceptance)
    assert dumps(s)==before
    advance(s,{'B':acceptance})
    assert s['contracts'][0]['status']=='active'
    assert repeats_without_progress(s,'A',Decision(pass_turn=False,message=text,contracts=[draft]))


@pytest.mark.parametrize('empty_first',[True,False])
def test_echo_is_logged_without_an_extra_model_call(tmp_path,monkeypatch,empty_first):
    s=discussion()
    s['config']['model']='qwen3.5:9b'
    text='My plan is unchanged and I will keep the same request.'
    repeat_action=Decision(pass_turn=False,message=text)
    advance(s,{'A':repeat_action})
    advance(s,{'B':Decision()})
    requests=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):
            value=next(replies)
            return ({'message':{'content':''},'done_reason':'length'} if value is None
                    else {'message':{'content':json.dumps(value)}})
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):requests.append(kwargs['json']);return Response()
    # Only response-model fields are valid in an actual model reply.
    replies=iter(([None] if empty_first else []) + [{'pass_turn':False,'message':text}])
    monkeypatch.setattr('farm.agents.httpx.AsyncClient',Client)
    async def run():
        store=Store(tmp_path/'echo.sqlite3');rid=store.create(s)
        before=dumps(s)
        decision=await model_decision(s,'B',observation(s,'B'),store,rid,'1:2:1:B')
        assert decision.pass_turn and not decision.message
        assert len(store.calls(rid))==1+empty_first and store.calls(rid)[int(empty_first)]['repeated_contribution']
        assert text in store.calls(rid)[int(empty_first)]['raw_response'] and dumps(s)==before
        assert len(requests) == 1+empty_first
    asyncio.run(run())


@pytest.mark.parametrize('text,review', [
    ('We can share delivery costs by signing this agreement.', True),
    ('I accept the smaller cap to minimize delivery costs.', True),
    ('We can minimize delivery fees by using exactly the amount of water needed.', True),
    ('We can work together to reduce our delivery fees.', True),
    ('My proposed contract would involve choosing a different delivery service that offers lower fees.', True),
    ('Can you explain the new delivery service?', True),
    ('Can we choose a delivery service?', False),
    ('There are no alternative delivery services.', False),
    ('This deal waives return fees.', True),
    ('We cannot share delivery costs.', False),
    ('Can we share delivery costs?', False),
    ('I will request zero to avoid delivery fees.', False),
    ('I will use all delivered water to avoid return fees.', False),
    ('The delivery fee is fixed regardless of quantity.', False),
    ('I will account for the return fee, which is currently 20 coins.', True),
    ('Consider the current return fee of 20 coins.', True),
    ('Can you elaborate on the recent delivery fee increase?', True),
    ('Can you explain the recent increase in the delivery fee?', True),
    ('Why did the return fee go up?', True),
    ("I've noticed that the delivery fee has been increasing.", True),
    ('The delivery fee has been 20 coins, which is higher than usual.', True),
    ('The delivery fee has been 30 coins.', True),
    ('Can you explain why the delivery fee increased?', True),
    ('The return fee is 40 coins per liter.', True),
    ('The news mentioned higher delivery fees.', True),
    ('Have delivery fees increased?', False),
    ('The delivery fee has not increased.', False),
    ('Our return fee is higher than the delivery fee.', False),
    ('I paid a return fee of 0 coins last round.', False),
    ('My return fee was 0 coins last round.', False),
    ('I will share my calculation of the return fee.', False),
    ('Our total delivery costs increased after we started ordering every round.', False),
    ('The delivery fee is zero if no water is delivered.', False),
    ('Fewer deliveries can reduce my total delivery costs.', False),
    ('The delivery fee is 20 coins and the return fee is 40 coins.', False),
    ('The delivery fee is 20 coins and the return fee is 20 coins.', True),
])
def test_fee_review_targets_suspicious_claims_not_ordinary_cost_planning(text, review):
    assert fee_claim_needs_review(text, Config().model_dump()) == review


def test_fee_claims_use_this_games_prices():
    cfg = Config(delivery_fee_coins=6, return_fee_enabled=False).model_dump()
    assert fee_claim_needs_review('The delivery fee is 20 coins.', cfg)
    assert not fee_claim_needs_review('The transport fee is 6 coins.', cfg)
    assert fee_claim_needs_review('The return fee is 40 coins.', cfg)
    assert not fee_claim_needs_review('The return fee is free.', cfg)


def test_existing_agreement_terms_require_a_record_and_net_caps_can_be_fractional():
    register = [{'id': 'c1', 'status': 'active', 'limits': [{'max_net':'0.5', 'max_request':10}]}]
    assert not unsupported_agreement_terms('The maximum net of 0.5 L applies under c1.', register)
    assert unsupported_agreement_terms('The maximum net of 5 L applies under c1.', register)
    assert unsupported_agreement_terms('A maximum net of 0.5 is not a standard unit of measurement.', register)
    assert not unsupported_agreement_terms('I propose a new maximum net of 5 L.', register)


@pytest.mark.parametrize('phase', [2, 7])
def test_public_output_grammar_separates_passing_from_speaking(phase):
    schema = model_format(discussion(phase), 'A')
    contribute, passing = schema['oneOf']
    assert contribute['properties']['pass_turn']['const'] is False
    assert passing['properties']['pass_turn']['const'] is True
    assert passing['properties']['message']['const'] == ''
    assert passing['properties']['contracts']['maxItems'] == 0
    for branch in schema['oneOf']:
        assert branch['required'] == ['pass_turn']
        assert branch['additionalProperties'] is False
        assert 'memory' in branch['properties']
    assert contribute['properties']['contracts']['items']['$ref'] == '#/$defs/ContractAction'
    assert 'ContractAction' in schema['$defs']


@pytest.mark.parametrize('deliberate_deception', [False, True])
def test_fee_review_accepts_a_correction_and_withholds_a_repeated_error(tmp_path, monkeypatch, deliberate_deception):
    s = discussion()
    if deliberate_deception:
        s['agents']['A']['profile'] = 'cunning_experimenter'
    claim = 'We should sign this pact to share delivery costs.'
    correction = 'Each farm pays its own fixed delivery fee; the pact only limits requests.'
    requests = []
    replies = iter([claim, claim if deliberate_deception else correction])
    class Response:
        def raise_for_status(self): pass
        def json(self):
            draft = {'pass_turn': False, 'message': next(replies)}
            if deliberate_deception:
                draft['private_bluff_reason'] = 'Try to persuade another farm to sign.'
            return {'message': {'content': json.dumps(draft)}}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            requests.append(kwargs['json'])
            return Response()
    monkeypatch.setattr('farm.agents.httpx.AsyncClient', Client)
    store = Store(tmp_path/'fees.sqlite3'); rid = store.create(s)
    before = dumps(s)
    decision = asyncio.run(model_decision(s, 'A', observation(s, 'A'), store, rid, '1:2:0:A'))
    assert decision.message == ('' if deliberate_deception else correction)
    assert decision.pass_turn == deliberate_deception and not decision.private_bluff_reason
    assert dumps(s) == before and len(requests) == 2
    calls = store.calls(rid)
    assert calls[0]['fee_claim_review'] and claim in calls[0]['raw_response']
    feedback = requests[-1]['messages'][-1]['content']
    assert 'fixed 20 coins' in feedback and 'fixed 40 coins' in feedback
    assert 'stay fixed' in feedback and 'upper bound' in feedback
    assert calls[-1]['withheld_fields'] == (['message'] if deliberate_deception else [])


def test_settled_debit_is_distinct_from_tariff_and_scoped_to_speaker_and_round():
    s = discussion()
    s.update(round=3, history=[{'agents': {'A': {'return_fee': 0}, 'B': {'return_fee': 4000}}},
                               {'agents': {'A': {'return_fee': 4000}, 'B': {'return_fee': 0}}}])
    assert not payment_conflict('I paid a return fee of 0 coins in round 1.', s, 'A')
    claim = 'I paid 0 coins in return fees last round.'
    assert payment_conflict(claim, s, 'A') == 'Your own round 2 return charge was 40 coins.'
    assert not payment_conflict(claim, s, 'B')
    assert not payment_conflict('I may pay a return fee of 40 coins this round.', s, 'B')


@pytest.mark.parametrize('count', [2, 3, 4, 5])
def test_openers_rotate_with_round_and_news_and_each_turn_reaches_all_farms(count):
    s = new_game(Config(agent_count=count, start_agent=1, communication=True, rounds=count+1))
    ring = list(s['agents'])
    for r in range(1, count+1):
        for phase in (2, 7):
            s.update(round=r, phase=phase, news_ready=phase==7, turn=0)
            start = (1 + r-1 + (phase==7)) % count
            expected = ring[start:] + ring[:start]
            for i, actor in enumerate(expected):
                assert observation(s, actor)['conversation_status']['next_speaker'] == actor
                advance(s, {actor: Decision(pass_turn=False, message=f'I measured {i} liters.')})
                if i+1 < count:
                    assert observation(s, expected[i+1])['messages'][-1]['sender'] == actor
            for actor in expected:
                advance(s, {actor: Decision()})
            assert s['last_conversation_end']['reason'] == 'all_passed'
            assert s['last_conversation_end']['opener'] == expected[0]
            if s['review_pending']:
                advance(s, {aid: scripted(s, aid) for aid in s['agents']})


def test_changed_contract_number_alone_repeats_but_a_changed_amount_does_not():
    previous = ['I propose c17 with a request cap of 81 liters.']
    assert is_repeated_message('I propose c18 with a request cap of 81 liters.', previous)
    assert not is_repeated_message('I propose c18 with a request cap of 78 liters.', previous)


def test_direct_question_latest_reply_and_one_owner_measurement_lead_public_turn():
    from farm.contracts import apply_contract_action
    from farm.schema import ContractAction
    from farm.agents import prompt_messages
    s = new_game(Config(agent_count=3, communication=True))
    s['phase'] = 2
    for actor, value in [('C',18), ('A',25), ('B',32)]:
        apply_contract_action(s, actor, ContractAction(kind='propose', start_round=1, end_round=2,
            limits=[{'agent_id': farm, 'max_request': value} for farm in (actor, 'B' if actor=='C' else 'C')]))
    advance(s, {'A': Decision(pass_turn=False, message='Farm C, what happened at 2 L under c2?')})
    advance(s, {'B': Decision(pass_turn=False, message='I would wait for rain.')})
    obs = observation(s, 'C')
    obs['recalled_experiences'] = [
        {'kind':'plant', 'water_per_plant':'3', 'group_id':'C-p1'},
        {'kind':'plant', 'water_per_plant':'2', 'group_id':'C-p2'}]
    model = json.loads(prompt_messages(s, 'C', obs)[1]['content'])['observation']
    assert [m['sender'] for m in model['messages']] == ['B']
    assert [m['sender'] for m in model['followup_messages']] == ['A']
    assert all(m['source_type']=='unverified_peer_claim' for m in model['messages']+model['followup_messages'])
    assert [r['group_id'] for r in model['recalled_experiences']] == ['C-p2']
    register = model['agreements']
    rows = [dict(zip(register['columns'], row)) for row in register['rows']]
    assert [row['id'] for row in rows] == ['c2','c3','c1']
    assert sorted(rows, key=lambda row: row['id']) == obs['agreements']


def test_news_passes_over_an_eliminated_successor():
    s = new_game(Config(agent_count=4, communication=True))
    s.update(phase=2)
    for actor in 'ABCD':
        advance(s, {actor:Decision()})
    assert s['last_conversation_end']['opener']=='A'
    s['agents']['B']['active']=False
    s.update(phase=7, news_ready=False)
    advance(s)
    assert speaker_order(s)==['C','D','A']


def test_counteroffer_preserves_terms_and_can_be_signed_on_the_next_turn():
    s=discussion()
    def offer(amount):
        return Decision(pass_turn=False, message=f'I can commit to {amount} L because of my new seedlings.',
            contracts=[{'kind':'propose','start_round':1,'end_round':2,
                        'limits':[{'agent_id':a,'max_request':amount} for a in ('A','B')]}])
    advance(s,{'A':offer(5)})
    assert observation(s,'B')['agreements'][0]['signatures']==['A']
    alternative=offer(8)
    assert not repeats_without_progress(s,'B',alternative)
    advance(s,{'B':alternative})
    assert [c['limits'][0]['max_request'] for c in observation(s,'A')['agreements']]==[5,8]
    advance(s,{'A':Decision(pass_turn=False,contracts=[{'kind':'accept','contract_id':'c2'}])})
    assert [c['status'] for c in s['contracts']]==['proposed','active']
