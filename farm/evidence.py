"""Owner-only cultivation evidence from executed actions, not model-written beliefs."""
from decimal import Decimal
from fractions import Fraction
from math import ceil, floor


def dose_text(value):
    result = format(Decimal(value.numerator) / Decimal(value.denominator), 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def healthy_rounds_min(row):
    # Older ledgers counted plants but did not retain dates of healthy growth.
    return row.get('healthy_rounds_min', int(row['healthy_productive_plants'] > 0))


def seedling_trial_hint(agent):
    """Optional follow-up using only this farm's measured, comparable seedling outcomes."""
    rows = sorted((r for r in agent.get('cultivation_trials', []) if r['kind'] == 'new_plants'),
                  key=lambda r: r['water_per_plant'])
    if not rows:
        return None
    if all(r['plants_died'] == r['plants_observed'] for r in rows):
        lower = ceil(rows[0]['water_per_plant']) - 1
        upper = floor(rows[-1]['water_per_plant']) + 1
        candidates = [lower, upper, upper + 1] if lower >= 0 else [upper, upper + 1, upper + 2]
        reason = 'All measured seedling doses caused death. Explore outside the failed range.'
    else:
        # All newly sown plants share the same initial growth and health.
        intervals = []
        for left, right in zip(rows, rows[1:]):
            if (left['growth_gain_max'] == right['growth_gain_max'] and
                    left['health_after_max'] == right['health_after_max']):
                continue
            lo = floor(10 * left['water_per_plant']) + 1
            hi = ceil(10 * right['water_per_plant']) - 1
            if lo <= hi:
                intervals.append((max(left['last_round'], right['last_round']), lo, hi))
        if not intervals:
            return None
        _, lo, hi = max(intervals, key=lambda interval: interval[0])
        mid = (lo + hi) // 2
        candidates = [Fraction(n, 10) for n in range(max(lo, mid - 1), min(hi, mid + 1) + 1)]
        reason = 'Adjacent measured seedling doses gave different growth or health. Compare inside that interval.'
    doses = ', '.join(dose_text(d) for d in candidates)
    total = dose_text(sum(candidates))
    return f'{reason} One possible trial uses one seedling at each of {doses} L per plant ({total} L total).'


def record_trial(agent, round_number, before, group, newly_sown, outcome):
    kind = 'new_plants' if newly_sown else 'existing_plants'
    amount = group['water']
    ledger = agent.setdefault('cultivation_trials', [])
    row = next((x for x in ledger if x['kind'] == kind and x['water_per_plant'] == amount), None)
    if row is None:
        row = {'kind': kind, 'water_per_plant': amount, 'first_round': round_number,
               'last_round': round_number, 'observations': 0, 'plants_observed': 0,
               'plants_died': 0, 'plants_survived': 0, 'productive_plants': 0,
               'healthy_productive_plants': 0, 'healthy_rounds_min': 0, 'last_healthy_round': None,
               'growth_gain_min': None, 'growth_gain_max': None,
               'health_after_min': None, 'health_after_max': None}
        ledger.append(row)
    row['observations'] += 1
    row['plants_observed'] += group['count']
    row['plants_died' if outcome == 'died' else 'plants_survived'] += group['count']
    gain = group['growth'] - before['growth']
    productive = outcome != 'died' and gain > 0
    if productive:
        row['productive_plants'] += group['count']
        if group['health'] >= (20 if newly_sown else before['health']):
            previous = healthy_rounds_min(row)
            last = row.get('last_healthy_round', row['last_round'] if previous else None)
            row['healthy_rounds_min'] = previous + int(last != round_number)
            row['last_healthy_round'] = round_number
            row['healthy_productive_plants'] += group['count']
    row['last_round'] = round_number
    for field, value in (('growth_gain', gain), ('health_after', group['health'])):
        low, high = field+'_min', field+'_max'
        row[low] = value if row[low] is None else min(row[low], value)
        row[high] = value if row[high] is None else max(row[high], value)


def cultivation_evidence(agent, *, compare_doses=False):
    rows = sorted(agent.get('cultivation_trials', []), key=lambda x:x['last_round'], reverse=True)
    failed = [x for x in rows if x['kind']=='new_plants' and x['plants_died']==x['plants_observed']]
    productive = [x for x in rows if x['healthy_productive_plants']]
    evidence = {'new_plant_doses_with_only_deaths': [dose_text(x['water_per_plant']) for x in failed[:8]],
                'observed_healthy_productive_doses': list(dict.fromkeys(dose_text(x['water_per_plant']) for x in productive))[:8]}
    if compare_doses and rows:
        for kind in ('new_plants', 'existing_plants'):
            recent = [x for x in rows if x['kind'] == kind][:8]
            if recent:
                evidence[kind] = {
                    'columns': ['L_per_plant', 'growth_gain_min_max', 'health_after_min_max', 'healthy_growth_rounds_at_least'],
                    'rows': [[dose_text(x['water_per_plant']), [x['growth_gain_min'], x['growth_gain_max']],
                              [x['health_after_min'], x['health_after_max']], healthy_rounds_min(x)]
                             for x in sorted(recent, key=lambda x: x['water_per_plant'])]}
    return evidence
