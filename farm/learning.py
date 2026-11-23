"""Owner-only plans, round reviews and bounded active memory."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from math import ceil, floor
import re

from .experience import recent_changes
from .knowledge import return_cost
from .schema import water
from .water_budget import liters_text


LIMITS = {'question': 3, 'note': 6, 'lesson': 12}
MONEY_FIELDS = {'bank', 'profit', 'debt', 'net_balance', 'fees', 'delivery_fee', 'return_fee',
                'revenue', 'profit_change', 'price_per_plant', 'debt_repaid'}


def coins(cents):
    return cents // 100 if cents % 100 == 0 else cents / 100


def model_money(value):
    """Convert raw observations once, including archived account rows and official NEWS."""
    if isinstance(value, list):
        return [model_money(item) for item in value]
    if not isinstance(value, dict) or value.get('money_unit') == 'coins':
        return value
    result = {}
    for key, item in value.items():
        if key in MONEY_FIELDS and isinstance(item, (int, float)):
            result[key] = coins(item)
        elif key == 'bank_ranking':
            result[key] = [coins(amount) for amount in item]
        else:
            result[key] = model_money(item)
    return result


def plan_amounts(agent):
    def subtotal(rows):
        return sum((r['count'] * water(r['water_per_plant']) for r in rows), Fraction(0))
    return subtotal(agent.get('planned_sowing', [])), subtotal(agent.get('planned_irrigation', []))


def water_quote(config, liters, planned):
    spare = max(Fraction(0), liters - planned)
    return {'delivery_liters': liters, 'planned_use_liters': liters_text(planned),
            'unused_liters': liters_text(spare), 'shortfall_liters': liters_text(max(0, planned-liters)),
            'delivery_fee_coins': config['delivery_fee_coins'] if liters else 0,
            'return_fee_coins': return_cost(config) if spare else 0}


def order_choices(config, total):
    """Compare no delivery and the two whole-liter neighbors under full delivery."""
    return [water_quote(config, amount, total) for amount in sorted({0, floor(total), ceil(total)})]


def own_caps(s, aid):
    r = s['round']
    return [{'contract_id': c['id'], 'start_round': c['start_round'], 'end_round': c['effective_end'],
             'max_request': lim['max_request'], 'max_net': lim['max_net']}
            for c in s['contracts'] if c['status'] == 'active' and c['start_round'] <= r <= c['effective_end']
            and c['cancelled_from'].get(aid, r+1) > r for lim in c['limits'] if lim['agent_id'] == aid]


def review_facts(s, aid):
    a = s['agents'][aid]
    r = s['round']
    sow, existing = plan_amounts(a)
    difference = a['used'] - sow - existing
    facts = {'water': {'round': r, 'planned_sowing_liters': liters_text(sow),
                       'planned_irrigation_liters': liters_text(existing), 'planned_total_liters': liters_text(sow+existing),
                       'used_minus_planned_liters': liters_text(difference),
                       'use_vs_plan': 'as planned' if difference == 0 else 'above plan' if difference > 0 else 'below plan',
                       'ordered_liters': a['request'], 'delivered_liters': a['delivered'],
                       'used_liters': liters_text(a['used']), 'returned_liters': liters_text(a['returned']),
                       'delivery_fee_coins': coins(a['delivery_fee']), 'return_fee_coins': coins(a['return_fee'])},
             'accounts': {'round': r, 'money_unit': 'coins', **{k: coins(a[k]) for k in
                          ('bank', 'debt', 'delivery_fee', 'return_fee', 'fees', 'revenue', 'profit')},
                          'net_balance': coins(a['bank']-a['debt']), 'round_profit': coins(a['revenue']-a['fees']),
                          'sold_plants': a['sold'], 'lost_plants': a['lost']}}
    results = sorted(a['recent_plant_results'], key=lambda x: x['outcome'] == 'growing')
    for i, row in enumerate(recent_changes(results, limit=6), 1):
        facts[f'plant:{i}'] = row
    for evaluation in reversed(s['contract_results']):
        if evaluation['round'] < r:
            break
        if aid in evaluation['individual']:
            cid = evaluation['contract_id']
            facts[cid] = {'round': r, 'contract_id': cid, 'own_result': deepcopy(evaluation['individual'][aid])}
    return facts


def fact_text(ref, record):
    if ref == 'water':
        return (f"Planned {record['planned_total_liters']} L (sowing {record['planned_sowing_liters']} L, "
                f"existing plants {record['planned_irrigation_liters']} L). Ordered {record['ordered_liters']} L, "
                f"received {record['delivered_liters']} L, used {record['used_liters']} L ({record['use_vs_plan']}), "
                f"returned {record['returned_liters']} L. Delivery fee {record['delivery_fee_coins']} coins, "
                f"return fee {record['return_fee_coins']} coins.")
    if ref == 'accounts':
        return (f"Cash {record['bank']} coins, debt {record['debt']} coins, net balance {record['net_balance']} coins. "
                f"Sales {record['revenue']} coins, delivery fee {record['delivery_fee']} coins, return fee "
                f"{record['return_fee']} coins. Round profit {record['round_profit']} coins. "
                f"Sold {record['sold_plants']} plants and lost {record['lost_plants']}.")
    if record.get('kind') == 'plant':
        g, h = record['growth'], record['health']
        return (f"{record['group_id']}, {record['count']} plants at {record['water_per_plant']} L each, "
                f"{record.get('stage','observed')}. Growth {g[0]}% to {g[1]}%, health {h[0]} to {h[1]}. "
                f"Outcome: {record['outcome']}.")
    result = record['own_result']
    bounds = []
    for key, label in [('request_met','order cap'), ('net_met','net-use cap')]:
        if result[key] is not None:
            bounds.append(label + (' met' if result[key] else ' breached'))
    return f"{ref}, own result {result['status']}. " + ', '.join(bounds)


def review_conflicts(review, facts):
    """Check explicit first-person measurements for this round. Inferences and future choices stay free."""
    w, a = facts['water'], facts['accounts']
    number = r'\s*(\d+(?:[.,]\d+)?)\s*'
    liters = r'(?:lit(?:er|re)s?|l)\b'
    checks = [
        (r'\b(?:actually used|I used|we used|water (?:usage|use|consumption) (?:was|is))', liters, w['used_liters'], 'water used'),
        (r'\b(?:I|we) returned', liters, w['returned_liters'], 'water returned'),
        (r'\b(?:I|we) (?:ordered|requested)', liters, w['ordered_liters'], 'order'),
        (r'\b(?:I|we) received', liters, w['delivered_liters'], 'delivery'),
        (r'\bdelivery fee (?:was|is|of)', r'coins?\b', a['delivery_fee'], 'delivery fee'),
        (r'\breturn fee (?:was|is|of)', r'coins?\b', a['return_fee'], 'return fee'),
        (r'\bnet balance (?:was|is|of)', r'coins?\b', a['net_balance'], 'net balance'),
        (r'\bcash balance (?:was|is|of)', r'coins?\b', a['bank'], 'cash balance'),
    ]
    findings = {}
    for field, text in [('conclusion', review.conclusion), ('working_note', review.working_note.text if review.working_note else '')]:
        for sentence in re.split(r'(?<=[.!?])\s+', text):
            if ('?' in sentence or re.search(r'\b(?:if|will|would|might|should|previous round|last round|per plant|each)\b', sentence, re.I)):
                continue
            for prefix, unit, value, label in checks:
                for match in re.finditer(prefix + number + unit, sentence, re.I):
                    if Decimal(match[1].replace(',','.')) != Decimal(str(value)):
                        findings[field] = f"Your recorded {label} was {value}."
            comparison = re.search(r'\b(?:water us(?:e|age) (?:was|is)|(?:I|we) (?:used|consumed))\s+'
                                   r'(less|more|lower|higher)\s+(?:water\s+)?than (?:I |we )?planned\b', sentence, re.I)
            if comparison:
                expected = 'below plan' if comparison[1].lower() in ('less','lower') else 'above plan'
                if expected != w['use_vs_plan']:
                    findings[field] = f"Used {w['used_liters']} L against a plan of {w['planned_total_liters']} L."
    return findings


def entries(agent):
    return agent.get('learning', {}).get('entries', {})


def slots(kind):
    return [f'{kind}:{i}' for i in range(1, LIMITS[kind]+1)]


def review_choices(agent):
    active = entries(agent)
    options = ['keep_strategy']
    for kind in ('lesson', 'question'):
        keys = slots(kind)
        if any(k not in active for k in keys):
            options.append('add_' + kind)
        for key in keys:
            if key in active:
                operations = ('revise', 'confirm', 'retire') if kind == 'lesson' else ('revise', 'close')
                options.extend(f'{op}_{key}' for op in operations)
    return options


def note_targets(agent):
    keys = slots('note')
    return (['new'] if any(k not in entries(agent) for k in keys) else []) + [k for k in keys if k in entries(agent)]


def check_review(s, aid, review):
    if not review or review.source not in review_facts(s, aid):
        raise ValueError('Cite one of the displayed private round records.')
    a = s['agents'][aid]
    if not a.get('learning', {}).get('long_term_goal') and not review.long_term_goal:
        raise ValueError('Choose your own long-term goal at the first review.')
    if review.choice not in review_choices(a):
        raise ValueError('Choose an available private memory action and an existing slot for changes.')
    if review.working_note and review.working_note.target not in note_targets(a):
        raise ValueError('Choose an available named working note or an existing note to replace.')


def apply_review(s, aid, review):
    a = s['agents'][aid]
    book = a.setdefault('learning', {})
    active = book.setdefault('entries', {})
    facts = review_facts(s, aid)
    fact = fact_text(review.source, facts[review.source])
    evidence = {'ref': review.source, 'round': s['round'], 'record': facts[review.source],
                'summary': fact, 'evidence_status': 'observed'}
    conflicts = review_conflicts(review, facts)
    conclusion = review.conclusion.replace('[[record]]', fact)
    changes = []

    def save(slot, text, title='', *, source=evidence):
        before = active.get(slot)
        status = 'question' if slot.startswith('question:') else (
            'observed' if text == source.get('summary') else 'hypothesis')
        after = {'title': title, 'text': text, 'round': s['round'], 'evidence': source,
                 'evidence_status': status} if text else None
        if after:
            active[slot] = after
        else:
            del active[slot]
        changes.append({'slot': slot, 'previous': before, 'current': after})

    if review.choice != 'keep_strategy':
        operation, slot = review.choice.split('_', 1)
        if operation == 'add':
            slot = next(key for key in slots(slot) if key not in active)
        text = conclusion
        if 'conclusion' in conflicts and slot.startswith('lesson:'):
            text = fact
        if operation == 'confirm' and 'conclusion' not in conflicts:
            previous = active[slot]
            save(slot, previous['text'], previous['title'], source=previous['evidence'])
        elif operation != 'confirm':
            save(slot, None if operation in ('retire', 'close') else text)
    if review.working_note:
        note = review.working_note
        key = next(k for k in slots('note') if k not in active) if note.target == 'new' else note.target
        save(key, fact if 'working_note' in conflicts else note.text.replace('[[record]]', fact), note.title.strip())
    for key in ('next_intent', 'long_term_goal'):
        value = getattr(review, key)
        if value and value.strip() != book.get(key):
            changes.append({'slot': key, 'previous': book.get(key), 'current': value.strip()})
            book[key] = value.strip()
    record = {'agent_id': aid, 'round': s['round'], 'choice': review.choice, 'conclusion': conclusion,
              'conclusion_status': 'observed' if conclusion == fact else 'hypothesis',
              'next_intent': book['next_intent'], 'evidence': evidence, 'changes': changes, 'money_unit': 'coins'}
    if conflicts:
        record['measurement_conflicts'] = conflicts
    book['last_review'] = record
    return record


def learning_context(agent, phase, review=False):
    book = agent.get('learning', {})
    if not book:
        return {}
    topics = {1: 'plan test seedling health growth dose', 2: 'agreement offer trust water',
              3: 'order request return cost fee water', 4: 'plant growth irrigation dose health',
              7: 'results fee harvest evidence'}
    query = agent.get('recall_query', '') + ' ' + topics.get(phase, '')
    terms = set(re.findall(r'\w+', query.casefold()))

    def relevance(item):
        slot, row = item
        words = set(re.findall(r'\w+', f"{slot} {row['title']} {row['text']}".casefold()))
        return (slot in query, len(terms & words), row['round'])

    selected = sorted(entries(agent).items(), key=relevance, reverse=True)
    if not review:
        selected = selected[:3]
    return {'long_term_goal': book.get('long_term_goal'), 'next_intent': book.get('next_intent'),
            'entries': {slot: {'title': row['title'], 'text': row['text'],
                       'source': row['evidence']['ref'], 'round': row['round'],
                       'evidence_status': row.get('evidence_status', 'hypothesis'),
                       'source_round': row['evidence'].get('round', row['round']),
                       'measured_record': row['evidence'].get('summary')} for slot, row in selected}}
