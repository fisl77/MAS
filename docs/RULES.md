# Authoritative rule reference — researcher only

Current rules: `farm-1.6`. Agents receive the public subset in their observations.

## Starting state and objective

Each farm starts empty, with configurable starting coins (default 500) and no debt.
Starting coins must be a positive whole number and are equal for all farms in a game.
Historical games without this setting started with 200 coins. The shared pond starts at
5,000 liters and holds at most 50,000. Profit is sales minus delivery and return
expenses. Starting capital is not profit. Always reconcile:

`available balance − debt = configured starting coins + cumulative profit`.

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
harvest check. A surviving plant reaching 100% is sold automatically and removed.
With harvest quality enabled (default), its price is 20 coins times final health / 20.
With quality disabled every living ripe plant sells for 20 coins. Plant count
is an integer; irrigation uses at most three decimal places per plant. Formal
validation does not reject a biologically harmful decision.

## Water and charges

Requests and deliveries are whole liters. Rotate the initial distributor through
the fixed farm order each round, skipping eliminated farms but not basing rotation
on positive requests. Deliver one liter to each active farm with an outstanding
request in turn, until no demand or fewer than one liter remain. Never deliver
more than requested. A fractional remainder stays in the pond.

Charge each recipient once for a positive delivery. The default is 20 coins.
Available cash pays the fee and any shortfall becomes debt. All active farms can
receive water, including farms whose balance becomes negative. Harvest sales repay
debt first and credit the rest to cash. Record the full sale as revenue once.

Unused water returns after harvest. A positive return triggers the configured flat fee
(default 40 coins). Disabling return fees makes every return free. Both fees accept
whole coins from zero upward. Returned water becomes available for the next round.
After all sales and fees, eliminate each farm with cash minus debt at or below zero,
including rounds without a harvest. Remove its remaining plants.

Through version 1.5, positive deliveries required 20 coins upfront, returns cost 40,
and exact zero alone allowed a farm to survive. Historical runs retain their recorded version.

## Weather and round order

Dry and rainy phases always alternate. Start dry. Independent durations are uniform
integers: dry 2–7 days; rainy 4–21. Maintain three consecutive phases using a private
weather-only RNG. Each rainy day's inflow is `1000 + pond_before_rain / 1000` liters.
Dry days add nothing. Apply rain after returns, then discard capacity overflow.

1. Privately choose provisional sowing and existing-group irrigation, including counts and doses.
2. Optional public discussion, or optional private reflection in the control condition.
3. Collect all requests without exposing peers' current decisions; allocate and charge.
4. Plant and allocate the actual delivered water.
5. Update health/growth, remove dead plants, sell living mature plants.
6. Return unused water, charge, eliminate if needed, evaluate contracts, then add rain.
7. Publish official NEWS and hold the public exchange or private control steps. Each surviving farm then completes one private review of the settled round, including the final round.

The next round starts only after phase 7. If all farms are eliminated, weather and
the pond series continue without agent actions to the configured final round.

Public discussion and post-NEWS each give every active farm ten actual contributions.
A message and/or formal agreement actions consume one contribution; passing or private
notes consume none. One farm speaks per turn. The discussion opener rotates each round, starting
with the configured starting farm. NEWS opens with the next eligible farm after that discussion's
opener. Each published turn, including agreement actions, is committed before the next farm decides.
After a pass a farm can still reply. All remaining eligible farms passing consecutively, exhausted
budgets or two full cycles of passes and repeated contributions end the phase. New claims, first
personal stances, changed offers and fresh signatures reset the cycle counter. A change of agreement
ID alone in the text is an echo. The model's echoed text stays in the call log.
It consumes no speaking budget. An accompanying new signature or changed agreement
is published and consumes one contribution. Passing preserves private note edits.
Private reflection ends after two silent steps or ten steps. Water orders remain simultaneous.
Identical pending/active agreement terms reuse a contract ID; an explicit matching
proposal signs those same terms for that actor. Already recorded signatures do not
create progress or new agreements. Different terms are not coalesced.

Own watering trials are stored as measured evidence independently of model notes.
The evidence contains only observed outcomes, never hidden biology. It does not reject
biologically harmful decisions or automatically substitute a better farming policy.

## Official observations

Start-NEWS contain the initial pond and forecast for rounds 1–7, no invented past
sales or withdrawals. Subsequent NEWS contain named net withdrawals for surviving
farms, the combined number of plants sold, sorted anonymous surviving balances,
exactly seven forecast days, and one-time elimination announcements with no score.
An eliminated farm's sales earlier that round may contribute to the aggregate.

Agents know the starting volume and capacity, the seven-day forecast, plant
health/growth ranges, automatic harvest, active price and fees, and the settlement deadline.
No current pond level, rival detailed accounts/plants/sales, secret biology, exact spell durations, extra
rain term, future weather outside the forecast, seed, exact end round, tie rule,
private memories, or researcher configuration enters agent observations. Public
agent claims may be false and do not receive automatic private-state verification.

Communication, signatures and next-round cancellations follow README.md. These
user-approved additions extend the original project handover's NEWS phase.
