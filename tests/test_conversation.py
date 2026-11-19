import pytest

from farm.conversation import is_repeated_message, speaker_order
from farm.engine import advance, new_game
from farm.schema import Config, Decision
from farm.store import dumps, loads
from farm.views import observation
from farm.conversation import repeats_without_progress, fee_claim_needs_review
from farm.agents import model_decision, model_format
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


def discussion(phase=2):
    s=new_game(Config(communication=True,rounds=2))
    s['phase']=phase;s['news_ready']=phase==7
    return s


def repeat(s, **overrides):
    phase = s['phase']
    for aid in speaker_order(s):
        decision = overrides.get(aid, Decision(pass_turn=False, message='My plan is unchanged; I will request 100 liters.'))
        advance(s, {aid: decision})
        if s['phase'] != phase:
            break


@pytest.mark.parametrize('phase',[2,7])
def test_two_stalled_passes_end_the_phase_and_preserve_original_messages(phase):
    s=discussion(phase)
    repeat(s);repeat(s)
    status=observation(s,'A')['conversation_status']
    assert status['stalled_passes']==1 and len(status['repeated_agents'])==1
    s=loads(dumps(s))
    repeat(s)
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


@pytest.mark.parametrize('second_pass',[True,False])
@pytest.mark.parametrize('empty_first',[True,False])
def test_repeated_draft_gets_one_reconsideration_and_original_trace_is_kept(tmp_path,monkeypatch,second_pass,empty_first):
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
    replies=iter(([None] if empty_first else []) + [{'pass_turn':False,'message':text},
                  {'pass_turn':True} if second_pass else {'pass_turn':False,'message':text}])
    monkeypatch.setattr('farm.agents.httpx.AsyncClient',Client)
    async def run():
        store=Store(tmp_path/'echo.sqlite3');rid=store.create(s)
        before=dumps(s)
        decision=await model_decision(s,'B',observation(s,'B'),store,rid,'1:2:1:B')
        assert decision.pass_turn==second_pass
        assert len(store.calls(rid))==2+empty_first and store.calls(rid)[int(empty_first)]['repeated_contribution']
        assert text in store.calls(rid)[int(empty_first)]['raw_response'] and dumps(s)==before
        assert 'has not been published' in requests[-1]['messages'][-1]['content']
        assert all(m['role']!='assistant' for m in requests[-1]['messages'])
    asyncio.run(run())


@pytest.mark.parametrize('text,review', [
    ('We can share delivery costs by signing this agreement.', True),
    ('I accept the smaller cap to minimize delivery costs.', True),
    ('This deal waives return fees.', True),
    ('We cannot share delivery costs.', False),
    ('Can we share delivery costs?', False),
    ('I will request zero to avoid delivery fees.', False),
    ('I will use all delivered water to avoid return fees.', False),
    ('The delivery fee is fixed regardless of quantity.', False),
])
def test_fee_review_targets_suspicious_claims_not_ordinary_cost_planning(text, review):
    assert fee_claim_needs_review(text) == review


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
def test_fee_review_keeps_raw_trace_and_leaves_public_choice_to_model(tmp_path, monkeypatch, deliberate_deception):
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
            return {'message': {'content': json.dumps({'pass_turn': False, 'message': next(replies)})}}
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
    assert decision.message == (claim if deliberate_deception else correction)
    assert dumps(s) == before and len(requests) == 2
    calls = store.calls(rid)
    assert calls[0]['fee_claim_review'] and claim in calls[0]['raw_response']
    feedback = requests[-1]['messages'][-1]['content']
    assert 'fixed 20 coins' in feedback and 'fixed 40 coins' in feedback
    assert 'deliberate public deception' in feedback and 'upper bound' in feedback


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
