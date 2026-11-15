# Authoritative rule reference — researcher only

Rule version: `farm-1.0`. This file is not an agent prompt.

## Starting state and objective

Each farm starts empty, with 200 coins and no debt. The shared pond starts at
5,000 liters and holds at most 50,000. Profit is sales minus delivery and return
expenses. Starting capital is not profit. Always reconcile:

`available balance − debt = 200 coins + cumulative profit`.

Only active farms can win. The highest cumulative profit among active farms wins;
ties have multiple winners. If nobody survives, nobody wins. The final ranking
includes eliminated farms and their frozen profits. Their profits also remain in
social welfare. The exact 1,000-round horizon and tie rule are hidden from agents.

## Plants

Plants are free and have no fixed numerical ceiling. New plants begin at 0% growth
and must receive at least 2 liters in their planting round to survive. Successful
initial watering sets health to 20, then applies the normal rule in that same round.

| Liters per plant | Growth increment | Health change |
| --- | --- | --- |
| Below 2 | 0 | −5 |
| 2 to below 4 | +10 | 0 |
| 4 through 6 | +20 | +2 |
| Above 6 through 8 | +25 | −3 |
| Above 8 | 0 | −8 |

Clamp growth to 100 and health to 0–20. At zero health the plant dies before any
harvest check. A surviving plant reaching 100% is sold automatically for health
in coins, then removed. Thus a fully healthy plant sells for 20 coins. Plant count
is an integer; irrigation uses at most three decimal places per plant. Formal
validation does not reject a biologically harmful decision.

## Water and charges

Requests and deliveries are whole liters. Rotate the initial distributor through
the fixed farm order each round, skipping eliminated farms but not basing rotation
on positive requests. Deliver one liter to each active farm with an outstanding
request in turn, until no demand or fewer than one liter remain. Never deliver
more than requested. A fractional remainder stays in the pond.

Before physical delivery, eliminate any prospective recipient unable to pay the
20-coin delivery charge. Recompute all allocations using the unchanged pond and
same relative order. Repeat until every positive recipient can pay; only then
deliver and charge once per recipient, never per portion. A zero allocation has
no fee. A zero balance alone does not eliminate a farm.

Water is available for the current round only. Unused water returns after harvest,
costing an additional 40 coins whenever the return is positive. Even if that fee
cannot be fully paid, return all unused water and record the full expense. Deduct
available money, record the remainder as debt, and eliminate the farm immediately.
Remove all plants at elimination. Returned water is not redistributed in that round.

## Weather and round order

Dry and rainy phases always alternate. Start dry. Independent durations are uniform
integers: dry 2–7 days; rainy 4–21. Maintain three consecutive phases using a private
weather-only RNG. Each rainy day's inflow is `1000 + pond_before_rain / 1000` liters.
Dry days add nothing. Apply rain after returns, then discard capacity overflow.

1. Private strategy planning.
2. Optional public discussion, or optional private reflection in the control condition.
3. Collect all requests without exposing peers' current decisions; allocate and charge.
4. Plant and allocate the actual delivered water.
5. Update health/growth, remove dead plants, sell living mature plants.
6. Return unused water, charge, eliminate if needed, evaluate contracts, then add rain.
7. Publish official NEWS, then optional conversation/reflection. Check for completion.

The next round starts only after phase 7. If all farms are eliminated, weather and
the pond series continue without agent actions to the configured final round.

## Official observations

Start-NEWS contain the initial pond and forecast for rounds 1–7, no invented past
sales or withdrawals. Subsequent NEWS contain named net withdrawals for surviving
farms, the combined number of plants sold, sorted anonymous surviving balances,
exactly seven forecast days, and one-time elimination announcements with no score.
An eliminated farm's sales earlier that round may contribute to the aggregate.

No current pond level, rival detailed accounts/plants/sales, secret biology, extra
rain term, future weather outside the forecast, seed, exact end round, tie rule,
private memories, or researcher configuration enters agent observations. Public
agent claims may be false and do not receive automatic private-state verification.

Communication, signatures and next-round cancellations follow README.md. These
user-approved additions extend the original project handover's NEWS phase.
