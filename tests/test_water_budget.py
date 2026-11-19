import asyncio
from copy import deepcopy
from fractions import Fraction as F
import json
import re

import pytest

from farm.agents import model_decision, model_format, prompt_messages, TechnicalError
from farm.engine import new_game, validate_decision
from farm.schema import Config, Decision
from farm.store import Store
from farm.views import observation
from farm.water_budget import WaterBudgetError, allocation_report, dose_pattern


def state():
    s = new_game(Config())
    s['phase'] = 4
    s['agents']['A']['delivered'] = 2
    s['agents']['A']['plants'] = [{'id': 'A-p1', 'count': 2, 'growth': 10, 'health': 15,
                                  'water': F(0), 'new': False}]
    return s


def failed_action():
    return Decision(new_plants=[{'count': 1, 'water_per_plant': '2.0'},
                                {'count': 1, 'water_per_plant': '3.0'}],
                    irrigation=[{'group_id': 'A-p1', 'count': 2, 'water_per_plant': '0'}])


def test_shared_budget_error_identifies_new_plant_spending_instead_of_zero_irrigation():
    s = state()
    with pytest.raises(WaterBudgetError) as caught:
        validate_decision(s, 'A', failed_action())
    report = caught.value.report
    assert report['available_liters'] == '2'
    assert report['new_plants_liters'] == '5' and report['existing_plants_liters'] == '0'
    assert report['total_liters'] == '5' and report['excess_liters'] == '3'
    message = str(caught.value)
    assert 'NEW plants consume 5 L' in message and 'EXISTING plants consume 0 L' in message
    assert 'new_plants[1]: 1 * 3 = 3 L' in message
    assert 'With zero' not in message


def test_fractional_accounting_multiplies_counts_and_keeps_exact_excess():
    s = state(); s['agents']['A']['delivered'] = 1
    action = Decision(new_plants=[{'count': 3, 'water_per_plant': '0.333'},
                                 {'count': 1, 'water_per_plant': '0.002'}])
    with pytest.raises(WaterBudgetError) as caught:
        validate_decision(s, 'A', action)
    assert caught.value.report['total_liters'] == '1.001'
    assert caught.value.report['excess_liters'] == '0.001'
    assert caught.value.report['entries'][0]['subtotal_liters'] == '0.999'


@pytest.mark.parametrize('delivery', [F(0), F(1,1000), F(1,2), F(2), F(2321,1000), F(10), F(99), F(50000)])
def test_native_dose_bound_allows_every_tested_legal_amount_and_blocks_excess(delivery):
    pattern = re.compile(dose_pattern(delivery))
    candidates = [0, 1, 2, 9, 10, 99, 100, 321, 499, 500, 999, 1000, 1999, 2000,
                  2001, 2320, 2321, 2322, 9999, 10000, 99000, 50000000, 50000001]
    for milli in candidates:
        amount = F(milli, 1000)
        text = str(milli//1000) + f'.{milli%1000:03d}'
        assert bool(pattern.fullmatch(text)) == (amount <= delivery), (delivery, text)
        assert bool(pattern.fullmatch(text.rstrip('0').rstrip('.'))) == (amount <= delivery)
    assert not pattern.fullmatch('-1') and not pattern.fullmatch('0.0001')


def test_schema_does_not_turn_physical_water_bound_into_a_biological_prescription():
    s = state(); schema = model_format(s, 'A')
    for name in ('NewPlants', 'Irrigation'):
        pattern = schema['$defs'][name]['properties']['water_per_plant']['pattern']
        assert re.fullmatch(pattern, '0.001') and re.fullmatch(pattern, '2.000')
        assert not re.fullmatch(pattern, '3')
    assert 'maximum' not in schema['$defs']['NewPlants']['properties']['count']
    assert 'maxItems' not in schema['properties']['new_plants']
    action = Decision(new_plants=[{'count': 1, 'water_per_plant': '0.5'}],
                      irrigation=[{'group_id': 'A-p1', 'count': 2, 'water_per_plant': '0.75'}])
    validate_decision(s, 'A', action)
    report = allocation_report(2, action.new_plants, action.irrigation)
    assert report['total_liters'] == '2' and report['excess_liters'] == '0'
    context = json.loads(prompt_messages(s, 'A', observation(s, 'A'))[1]['content'])
    assert context['farm_water_budget']['available_liters'] == '2'
    assert not context['farm_water_budget']['new_planting_required']
    assert not context['farm_water_budget']['simultaneous_dose_comparison_required']


@pytest.mark.parametrize('corrected', [True, False])
def test_resource_correction_uses_exact_ledger_and_never_scales_the_rejected_plan(tmp_path, monkeypatch, corrected):
    requests = []
    bad = failed_action().model_dump(include={'new_plants','irrigation'})
    responses = [bad, {'keep_id':'n0'}, {'finish':True}] if corrected else [bad, {'keep_id':'n1'}]

    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return {'message': {'content': json.dumps(self.body)}}

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            requests.append(json)
            return Response(responses[min(len(requests)-1, len(responses)-1)])

    monkeypatch.setattr('farm.agents.httpx.AsyncClient', Client)

    async def run():
        s = state(); before = deepcopy(s)
        store = Store(tmp_path/'water.sqlite3'); rid = store.create(s)
        if corrected:
            result = await model_decision(s, 'A', observation(s, 'A'), store, rid, '1:4:0:A')
            assert result.new_plants[0].water_per_plant == '2.0' and not result.irrigation
            assert len(store.calls(rid)) == 3
        else:
            with pytest.raises(TechnicalError, match='Invalid budget-planning choice'):
                await model_decision(s, 'A', observation(s, 'A'), store, rid, '1:4:0:A')
            assert len(store.calls(rid)) == 4
        assert store.calls(rid)[0]['water_budget_report']['new_plants_liters'] == '5'
        assert s == before and store.decision(rid, '1:4:0:A') is None
    asyncio.run(run())
    tool = json.loads(requests[1]['messages'][1]['content'])['budget_planning_tool']
    assert tool['remaining_liters'] == '2' and tool['used_liters'] == '0'
    assert [x['allocation_id'] for x in tool['proposed_allocations'] if x['keep_affordable']] == ['n0','i0']
    assert 'keep_id' in requests[1]['messages'][0]['content']
    assert not any(m['role']=='assistant' for m in requests[1]['messages'])
