from fractions import Fraction as F
import random

import pytest

from farm.agents import scripted
from farm.engine import (new_game, allocation, plant_change, grow, deliver, settle,
                         publish_news, finish, advance, active_ids, validate_decision)
from farm.schema import Config, Decision, water
from farm.store import dumps, loads
from farm.views import observation, metrics


def game(**kwargs):
    return new_game(Config(**kwargs))


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
    assert a["profit"] == 2400 and a["bank"] == 22400


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


def test_insolvent_delivery_reallocated_without_payment():
    s=game();s["pond"]=F(5)
    a,b=s["agents"].values()
    a.update(bank=1900,profit=-18100,request=10)
    b["request"]=10
    deliver(s)
    assert not a["active"] and a["delivered"]==0 and a["fees"]==0
    assert b["delivered"]==5 and b["fees"]==2000 and s["pond"]==0


def test_zero_balance_without_obligation_is_active():
    s=game();a=s["agents"]["A"];a.update(bank=0,profit=-20000,request=0)
    deliver(s)
    assert a["active"]
    a["request"]=1;deliver(s)
    assert not a["active"]


def test_delivery_paid_before_harvest_and_exact_zero_allowed():
    s=game();a=s["agents"]["A"];a.update(bank=2000,profit=-18000,request=100)
    deliver(s)
    assert a["active"] and a["bank"]==0 and a["fees"]==2000


def test_return_debt_never_loses_water_or_full_expense():
    s=game();a=s["agents"]["A"]
    a.update(bank=1000,profit=-19000,delivered=10,used=F(3))
    s["pond"]=F(4990)
    settle(s)
    assert s["pond"]==4997 and a["returned"]==7
    assert a["bank"]==0 and a["debt"]==3000 and a["profit"]==-23000
    assert not a["active"]
    publish_news(s)
    assert s["news"]["announcements"]==["Agent A has been eliminated."]
    assert "A" not in s["news"]["net_withdrawals"] and s["news"]["bank_ranking"]==[20000]


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
def test_complete_games_water_accounts_and_round_trip(count,communication):
    s=game(agent_count=count,rounds=35,communication=communication)
    forecasts={x["round"]:x["weather"] for x in s["news"]["forecast"]}
    before=F(5000)
    while s["status"]!="completed":
        decisions={a:scripted(s,a) for a in active_ids(s)} if s["phase"] in (1,2,3,4) or s["phase"]==7 and s["news_ready"] else {}
        phase=s["phase"]
        advance(s,decisions)
        if phase==6:
            h=s["history"][-1]
            assert h["pond"]==before-sum(a["used"] for a in h["agents"].values())+h["rain"]-h["overflow"]
            assert h["weather"]==forecasts[h["round"]]
            before=h["pond"]
        if s["news_ready"]:
            forecasts.update({x["round"]:x["weather"] for x in s["news"]["forecast"]})
        assert all(a["bank"]-a["debt"]==20000+a["profit"] for a in s["agents"].values())
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
    s=game();s['agents']['A'].update(bank=0,profit=-20000,request=1)
    deliver(s)
    assert not s['agents']['A']['active']
    assert observation(s,'B')['active_agents']==['A','B']
    publish_news(s)
    assert observation(s,'B')['active_agents']==['B']


def test_plant_ids_do_not_reveal_other_farms_activity():
    from farm.engine import farm_work
    first,second=game(),game()
    farm_work(second,'B',Decision(new_plants=[{'count':1,'water_per_plant':'0'}]*20))
    for s in (first,second):
        farm_work(s,'A',Decision(new_plants=[{'count':1,'water_per_plant':'0'}]))
    assert first['agents']['A']['plants']==second['agents']['A']['plants']
