from fractions import Fraction as F
import random

import pytest

from farm.agents import scripted
from farm.conversation import speaker_order
from farm.engine import (new_game, allocation, plant_change, grow, deliver, settle,
                         publish_news, finish, advance, active_ids, validate_decision)
from farm.schema import Config, Decision, water
from farm.store import dumps, loads
from farm.views import observation, metrics


def game(**kwargs):
    return new_game(Config(**kwargs))


def test_default_and_configurable_starting_capital():
    assert Config().starting_coins == 500
    for coins in (1, 200, 500, 725):
        s=game(starting_coins=coins)
        assert all(a['bank']==coins*100 and a['profit']==0 and a['debt']==0
                   for a in s['agents'].values())
    for invalid in (0, -1, 1.5, True, '500'):
        with pytest.raises(ValueError):Config(starting_coins=invalid)


@pytest.mark.parametrize("amount,expected", [
    ("0", (0, 0)), ("1.999", (0, 0)), ("2", (10, 20)), ("3.999", (10, 20)),
    ("4", (20, 20)), ("6", (20, 20)), ("6.001", (25, 17)),
    ("8", (25, 17)), ("8.001", (0, 12)), ("9", (0, 12))])
def test_initial_watering_boundaries(amount, expected):
    assert plant_change(0, 0, water(amount), new=True) == expected


@pytest.mark.parametrize("amount,expected", [
    ("1.999", (90, 10)), ("2", (100, 15)), ("3.999", (100, 15)),
    ("4", (100, 17)), ("6", (100, 17)), ("6.001", (100, 12)),
    ("8", (100, 12)), ("8.001", (90, 7))])
def test_established_watering_boundaries(amount, expected):
    assert plant_change(90, 15, water(amount)) == expected


def test_death_before_sale_and_current_quality():
    s=game(); a=s["agents"]["A"]
    a["plants"]=[{"id":"dead","count":2,"growth":90,"health":3,"water":F(8)},
                 {"id":"alive","count":2,"growth":90,"health":10,"water":F(4)}]
    grow(s)
    assert a["plants"] == []
    assert a["lost"] == 2 and a["sold"] == 2
    assert a["profit"] == 2400 and a["bank"] == 52400


@pytest.mark.parametrize("quality", [True, False])
@pytest.mark.parametrize("health", [1, 15, 20])
def test_price_per_living_plant_and_death_at_maturity(quality, health):
    s = game(harvest_quality=quality)
    a = s["agents"]["A"]
    a["plants"] = [{"id": "ripe", "count": 2, "growth": 90, "health": health, "water": F(2)},
                   {"id": "dead", "count": 1, "growth": 90, "health": 3, "water": F(8)}]
    grow(s)
    price = (health if quality else 20) * 100
    sale, = (e for e in s["events"] if e["kind"] == "sale")
    assert sale["price_per_plant"] == price and a["revenue"] == 2 * price
    assert (a["sold"], a["lost"], a["plants"]) == (2, 1, [])


@pytest.mark.parametrize("dose,mature,returns,fee,expected", [
    ("3", True, True, 40, 7),          # Uses all water, repays 8 coins of transport debt.
    ("2.999", True, True, 40, -33),    # Even 0.001 L triggers one fee.
    ("2.999", True, True, 7, 0),
    ("2.999", True, False, 40, 7),
    ("2.999", True, True, 0, 7),
    ("3", False, False, 40, -8),
])
def test_round_settlement_after_sales_and_returns(dose, mature, returns, fee, expected):
    s = game(rounds=1, starting_coins=12, return_fee_enabled=returns, return_fee_coins=fee)
    a = s["agents"]["A"]
    a["plants"] = [{"id": "A-p1", "count": 1, "growth": 90 if mature else 0, "health": 15}]
    while s["phase"] < 3:
        advance(s, {aid: Decision() for aid in active_ids(s)})
    advance(s, {"A": Decision(request=3), "B": Decision(request=0)})
    assert observation(s, "A")["own_farm"]["net_balance"] == -800 and a["active"]
    advance(s, {"A": Decision(irrigation=[{"group_id": "A-p1", "count": 1, "water_per_plant": dose}]),
                "B": Decision()})
    advance(s)
    assert a["active"] and a["bank"] - a["debt"] == (700 if mature else -800)
    advance(s)
    assert a["returned"] == 3 - water(dose)
    assert a["fees"] == a["delivery_fee"] + a["return_fee"] == 2000 + (fee * 100 if returns and a["returned"] else 0)
    assert a["bank"] - a["debt"] == 100 * expected == 1200 + a["profit"]
    assert a["active"] == (expected > 0)
    assert s["agents"]["B"]["fees"] == 0
    while s["status"] != "completed":
        advance(s, {aid: scripted(s, aid) if s.get('review_pending') else Decision()
                    for aid in active_ids(s)} if s["news_ready"] else {})
    assert ("A" in s["news"]["net_withdrawals"]) == (expected > 0)


def test_fees_follow_actual_liters_and_can_both_be_free():
    s = game(delivery_fee_coins=0, return_fee_enabled=False)
    s["pond"] = F(1)
    for a in s["agents"].values():
        a["request"] = 5
    deliver(s)
    settle(s)
    a, b = s["agents"].values()
    assert (a["delivered"], b["delivered"]) == (1, 0)
    assert a["returned"] == 1 and s["pond"] == 1
    assert all(farm["fees"] == 0 for farm in (a, b))
    assert not any(e["kind"] == "fee" for e in s["events"])


@pytest.mark.parametrize("requests,pond,expected", [
    ({"A":10,"B":30,"C":50},100,{"A":10,"B":30,"C":50}),
    ({"A":13,"B":50},25,{"A":13,"B":12}),
    ({"A":13,"B":50,"C":50},38,{"A":13,"B":13,"C":12}),
    ({"A":0,"B":2},F(29,10),{"A":0,"B":2}),
    ({"A":10,"B":30},F(9,10),{"A":0,"B":0}),
    ({"A":1,"B":100},5,{"A":1,"B":4}),
    ({"A":1,"B":1},2,{"A":1,"B":1})])
def test_round_robin_examples(requests,pond,expected):
    assert allocation(requests,F(pond),list(requests)) == expected


def test_random_allocation_conservation_and_order():
    rng=random.Random(17)
    for _ in range(300):
        requests={str(i):rng.randrange(100) for i in range(5)}
        pond=F(rng.randrange(5000),10)
        result=allocation(requests,pond,list(requests))
        assert sum(result.values()) == min(int(pond),sum(requests.values()))
        assert all(0<=v<=requests[a] for a,v in result.items())


def test_start_rotation_independent_of_requests_and_skips_eliminated():
    s=game(agent_count=3)
    for expected in (0,1,2,0):
        for a in s["agents"].values():a["request"]=0
        s["agents"]["C"]["request"]=1
        deliver(s)
        assert s["start"]==expected
    s["agents"]["B"]["active"]=False
    deliver(s)
    assert s["start"]==2


def test_low_cash_does_not_change_water_allocation():
    s=game();s["pond"]=F(5)
    a,b=s["agents"].values()
    a.update(bank=1900,profit=-48100,request=10)
    b["request"]=10
    deliver(s)
    assert a["active"] and a["delivered"]==3 and a["fees"]==2000 and a["debt"]==100
    assert b["delivered"]==2 and b["fees"]==2000 and s["pond"]==0


def test_zero_balance_without_obligation_eliminated_at_settlement():
    s=game();a=s["agents"]["A"];a.update(bank=0,profit=-50000,request=0)
    deliver(s)
    assert a["active"]
    settle(s)
    assert not a["active"]


def test_delivery_paid_before_harvest_and_exact_zero_allowed():
    s=game();a=s["agents"]["A"];a.update(bank=2000,profit=-48000,request=100)
    deliver(s)
    assert a["active"] and a["bank"]==0 and a["fees"]==2000


def test_return_debt_never_loses_water_or_full_expense():
    s=game();a=s["agents"]["A"]
    a.update(bank=1000,profit=-49000,delivered=10,used=F(3))
    s["pond"]=F(4990)
    settle(s)
    assert s["pond"]==4997 and a["returned"]==7
    assert a["bank"]==0 and a["debt"]==3000 and a["profit"]==-53000
    assert not a["active"]
    publish_news(s)
    assert s["news"]["announcements"]==["Agent A has been eliminated."]
    assert "A" not in s["news"]["net_withdrawals"] and s["news"]["bank_ranking"]==[50000]


def test_no_return_fee_on_exact_use_and_rain_after_returns():
    s=game();s["weather"][0]["rainy"]=True;s["pond"]=F(100)
    a=s["agents"]["A"];a.update(delivered=10,used=F(5))
    settle(s)
    assert s["pond"]==F(105)+1000+F(105,1000)
    assert a["fees"]==4000
    t=game();t["agents"]["A"].update(delivered=10,used=F(10));settle(t)
    assert t["agents"]["A"]["fees"]==0


def test_overflow_recorded():
    s=game();s["weather"][0]["rainy"]=True;s["pond"]=F(49999)
    settle(s)
    assert s["pond"]==50000
    assert s["history"][-1]["overflow"]==F(49999)+1000+F(49999,1000)-50000


def test_group_splitting_no_plant_limit_and_formal_validation():
    s=game();s["phase"]=4;a=s["agents"]["A"];a["delivered"]=10
    a["plants"]=[{"id":"p0","count":4,"growth":20,"health":20}]
    d=Decision(irrigation=[{"group_id":"p0","count":1,"water_per_plant":"2"},
                           {"group_id":"p0","count":2,"water_per_plant":"4"}],
               new_plants=[{"count":10000000,"water_per_plant":"0"}])
    advance(s,{"A":d,"B":Decision()})
    assert len(a["plants"])==4 and a["used"]==10
    advance(s)
    assert a["lost"]==10000000
    assert sum(x["count"] for x in a["plants"])==4
    assert sorted(x["health"] for x in a["plants"])==[15,20,20]


def test_overspending_foreign_plants_and_precision_rejected_but_bad_biology_allowed():
    s=game();s["phase"]=4;s["agents"]["A"]["delivered"]=10
    for d in (Decision(new_plants=[{"count":2,"water_per_plant":"6"}]),
              Decision(irrigation=[{"group_id":"foreign","count":1,"water_per_plant":"1"}])):
        with pytest.raises(ValueError):validate_decision(s,"A",d)
    validate_decision(s,"A",Decision(new_plants=[{"count":1,"water_per_plant":"9"}]))
    with pytest.raises(ValueError):water("0.0001")
    with pytest.raises(ValueError):Decision(request=1.5)


def test_winner_eligibility_ties_and_all_eliminated():
    s=game(agent_count=3)
    s["agents"]["A"].update(active=False,profit=99900)
    finish(s)
    assert s["ranking"][0]["agent_id"]=="A" and not s["ranking"][0]["winner"]
    assert [x["agent_id"] for x in s["ranking"] if x["winner"]]==["B","C"]
    for a in s["agents"].values():a["active"]=False
    finish(s)
    assert not any(x["winner"] for x in s["ranking"])


@pytest.mark.parametrize("count",[2,5])
@pytest.mark.parametrize("communication",[False,True])
@pytest.mark.parametrize("starting_coins",[200,500,725])
def test_complete_games_water_accounts_and_round_trip(count,communication,starting_coins):
    s=game(agent_count=count,rounds=35,communication=communication,starting_coins=starting_coins)
    forecasts={x["round"]:x["weather"] for x in s["news"]["forecast"]}
    before=F(5000)
    while s["status"]!="completed":
        actors = speaker_order(s)[:1] if communication and s["phase"] in (2,7) and not s['review_pending'] else active_ids(s)
        decisions={a:scripted(s,a) for a in actors} if s["phase"] in (1,2,3,4) or s["phase"]==7 and s["news_ready"] else {}
        phase=s["phase"]
        advance(s,decisions)
        if phase==6:
            h=s["history"][-1]
            assert h["pond"]==before-sum(a["used"] for a in h["agents"].values())+h["rain"]-h["overflow"]
            assert h["weather"]==forecasts[h["round"]]
            before=h["pond"]
        if s["news_ready"]:
            forecasts.update({x["round"]:x["weather"] for x in s["news"]["forecast"]})
        assert all(a["bank"]-a["debt"]==starting_coins*100+a["profit"] for a in s["agents"].values())
        s["events"]=[]
        s=loads(dumps(s))
    assert len(s["history"])==35
    assert metrics(s)["social_profit"]==sum(a["profit"] for a in s["agents"].values())


def test_observation_never_inherits_research_fields():
    s=game(communication=True)
    s["agents"]["B"]["memory"]="FOREIGN_PRIVATE_SECRET"
    s["secret_new_field"]="INTERNAL_SECRET"
    obs=observation(s,"A")
    text=dumps(obs)
    for banned in ("FOREIGN_PRIVATE_SECRET","INTERNAL_SECRET",'"seed"','"rounds"','"rng"','"pond"', '"config"', '"ranking"'):
        assert banned not in text
    assert len(obs["news"]["forecast"])==7
    assert "initial_pond_liters" in text


def test_regular_mode_and_test_labels():
    with pytest.raises(ValueError):Config(test_mode=False,rounds=10,controller="ollama")
    with pytest.raises(ValueError):Config(test_mode=False,rounds=1000,controller="test")
    assert Config(test_mode=False,rounds=1000,controller="ollama").rounds==1000


def test_thousand_round_weather_and_all_eliminated_world_continuation():
    s=game(rounds=1000,scenario="insolvency",agent_count=5)
    forecasts={x["round"]:x["weather"] for x in s["news"]["forecast"]}
    while s["status"]!="completed":
        phase=s["phase"]
        decisions={a:scripted(s,a) for a in active_ids(s)} if phase in (1,2,3,4) or phase==7 and s["news_ready"] else {}
        advance(s,decisions)
        if phase==6:
            assert s["history"][-1]["weather"]==forecasts[s["round"]]
        if s["news_ready"]:
            forecasts.update({x["round"]:x["weather"] for x in s["news"]["forecast"]})
        s["events"]=[]
    assert len(s["history"])==1000 and s["pond"]==50000
    assert not active_ids(s) and not any(x["winner"] for x in s["ranking"])
    # Exclude the final truncated phase when testing complete phase durations.
    runs=[]
    for h in s["history"]:
        if not runs or runs[-1][0]!=h["weather"]:runs.append([h["weather"],0])
        runs[-1][1]+=1
    assert runs[0][0]=="dry"
    for weather,duration in runs[:-1]:
        assert (2<=duration<=7) if weather=="dry" else (4<=duration<=21)


def test_resource_minimum_includes_delivery_trough_before_rain():
    s=game();s["pond"]=F(10);s["weather"][0]["rainy"]=True
    s["agents"]["A"]["request"]=10
    deliver(s);s["agents"]["A"]["used"]=F(10);settle(s)
    assert s["pond"]==1000 and metrics(s)["minimum_pond"]==0


def test_observations_do_not_leak_elimination_before_public_news():
    s=game(communication=True);s['agents']['A'].update(bank=0,profit=-50000,request=1)
    deliver(s)
    settle(s)
    assert not s['agents']['A']['active']
    assert observation(s,'B')['active_agents']==['A','B']
    assert observation(s,'B')['conversation_status']['known_eliminated_agents']==[]
    publish_news(s)
    assert observation(s,'B')['active_agents']==['B']
    s['phase']=7
    status=observation(s,'B')['conversation_status']
    assert status['known_eliminated_agents']==['A'] and status['eligible_agents']==['B']
    assert not status['can_receive_reply_before_phase_end']


def test_passing_does_not_remove_reply_eligibility_and_all_pass_closes_phase():
    s=game(communication=True);s['phase']=2
    advance(s,{'A':Decision(pass_turn=False,message='B, can you reply?')})
    status=observation(s,'A')['conversation_status']
    assert status['phase_open'] and status['pass_number']==2
    assert status['eligible_agents']==['B','A']
    assert not status['passing_is_permanent']
    assert status['can_receive_reply_before_phase_end'] and status['messages_remaining']=={'A':9,'B':10}
    advance(s,{'B':Decision()})
    status=observation(s,'A')['conversation_status']
    assert s['phase']==2 and status['consecutive_passes']==1
    advance(s,{'A':Decision()})
    status=observation(s,'A')['conversation_status']
    assert s['phase']==3 and not status['phase_open']
    assert status['eligible_agents']==[] and not status['can_receive_reply_before_phase_end']


def test_plant_ids_do_not_reveal_other_farms_activity():
    from farm.engine import farm_work
    first,second=game(),game()
    farm_work(second,'B',Decision(new_plants=[{'count':1,'water_per_plant':'0'}]*20))
    for s in (first,second):
        farm_work(s,'A',Decision(new_plants=[{'count':1,'water_per_plant':'0'}]))
    assert first['agents']['A']['plants']==second['agents']['A']['plants']
