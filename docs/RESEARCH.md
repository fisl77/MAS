# Research protocol and analytical boundaries

## Question

How does communication affect agreement compliance, individual and aggregate
profits, survival, and the common water resource among competing autonomous farms?

Communication is available only during discussion and after official NEWS.
Participants choose whether to contribute. Both communication conditions allow
the same maximum number of discretionary inference steps. Report actual usage,
because equal opportunity does not imply equal computation or equal wall time.

## Pilot gate

1. Pass mechanics, accounting, information-boundary and checkpoint tests.
2. Run separate short technical pilots for each installed target model.
3. Examine invalid-action rates, token consumption, context headroom, elapsed time,
   request/irrigation behavior, memory writes, and spontaneous contract usage.
4. Freeze rule, prompt, model digest, generation parameters, profiles, call budgets,
   and seed list before a main experiment. Do not tune prompts on measured main runs.
5. Choose repeat counts after pilot timing. A technically successful anecdote is not
   evidence of a communication effect.

## Comparisons

Use communication-on/off pairs with identical model, weather seed, profile
composition, start position, and limits. Counterbalance starting positions. Use
multiple seeds and independent memories. Treat two- and five-farm populations as
different conditions. Keep model comparisons in separate games, never mix models
within one game. Restrict primary outcome comparisons to completed research games;
list interruptions and technical failures separately rather than treating them as
strategic bankruptcies.

Report individual profit, social profit including eliminated farms, pond trajectory
and extrema, elimination times and survivor count. Also report deliveries, requests,
returns, sales, deaths, inference time, actual tokens and correction attempts.
Agreement rates have their own denominators: self-commitments, multiparty contracts,
individual evaluable obligations and jointly evaluable contract-rounds. Missing or
partially unassessable obligations are not zero or perfect compliance. Overlapping
agreements contribute distinct observations; they are not independent samples.

The dashboard provides descriptive comparisons, not causal significance tests.
Statistical inference requires a prespecified design and adequate independent
replicates. Weather seeds match the exogenous weather, not every model decision.

## Limited economic analysis

A useful transparent reference is a hypothetical stationary inventory of `k`
healthy plants receiving four liters every day, with harvested plants replaced on
the next day. Ignoring transient planting and liquidity effects, sufficient supply
supports one harvest per plant every five days. Average sale revenue is therefore
`4k` coins per day, gross water use `4k` liters per day, and the daily delivery fee
is 20 coins when there is a positive delivery. The steady-cycle private net is
`4k − 20` coins per day when no water is returned. This is a feasible-policy
accounting reference under its assumptions, **not** a game-wide optimum or Nash
equilibrium. It does not account for rationing, weather, exploration, imperfect
information, learning, or capital constraints during initial growth.

For a finite one-round strategic comparison, fix the entire initial state, starting
distributor, weather realization, feasible complete action policies, and whether
continuation plant value is included. Use the authoritative engine for every joint
policy combination. A pure-strategy Nash candidate must have no profitable
unilateral deviation within that explicitly enumerated policy set. A social optimum
within the same restricted set maximizes the sum of the corresponding payoffs.
Those results concern only the stated state, payoff and policy set. No equilibrium
of the full partially observed, multi-round LLM game follows from them.

The application does not label any observed run as an equilibrium or optimum.
Resource sustainability, economic welfare, and compliance are different measures.
