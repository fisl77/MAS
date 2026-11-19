"""Private, measured changes that a farm can retrieve without reading old prompts."""
from decimal import Decimal
import json
import re

from .water_budget import liters_text


ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiences(
    run_id TEXT, agent_id TEXT, round INTEGER, kind TEXT, subject TEXT,
    dose TEXT, tags TEXT, body TEXT,
    PRIMARY KEY(run_id, agent_id, kind, round, subject));
CREATE INDEX IF NOT EXISTS experience_dose ON experiences(run_id, agent_id, kind, dose, round);
CREATE INDEX IF NOT EXISTS experience_subject ON experiences(run_id, agent_id, subject, round);
CREATE INDEX IF NOT EXISTS experience_round ON experiences(run_id, agent_id, round DESC, kind, subject);
"""


def plant_change(result):
    g, before = result['group'], result['before']
    row = {'kind': 'plant', 'round': result['round'], 'group_id': g['id'], 'count': g['count'],
           'water_per_plant': liters_text(g['water']), 'growth': [before['growth'], g['growth']],
           'health': [before['health'], g['health']], 'outcome': result['outcome']}
    if 'newly_sown' in result:
        row['stage'] = 'sown' if result['newly_sown'] else 'established'
    return row


def recent_changes(results, limit=4):
    """Show different observed treatments/outcomes before repeating similar groups."""
    selected, seen = [], set()
    for result in results:
        row = plant_change(result)
        key = (row.get('stage'), row['water_per_plant'], tuple(row['growth']), tuple(row['health']), row['outcome'])
        if key not in seen:
            selected.append(row)
            seen.add(key)
            if len(selected) == limit:
                break
    return selected


def _archive_rows(state, events):
    for event in events:
        r = event['round']
        if event['kind'] == 'plant_result':
            row = plant_change(event)
            tags = [row['outcome'], row.get('stage', '')]
            if row['growth'][1] > row['growth'][0]:
                tags.append('gain')
            if row['health'][1] < row['health'][0]:
                tags.append('decline')
            yield event['agent_id'], row['group_id'], tags, row
        elif event['kind'] == 'weather':
            # Settlement has finished. Project each farm's own accounts separately.
            settled = state['history'][-1]
            if settled['round'] != r:
                settled = next(h for h in reversed(state['history']) if h['round'] == r)
            for aid, a in settled['agents'].items():
                if not any(a[k] for k in ('request', 'fees', 'revenue', 'lost')):
                    continue
                row = {k: a[k] for k in ('request', 'delivered', 'sold', 'lost', 'fees', 'revenue')}
                row.update(kind='accounts', round=r, used=liters_text(a['used']),
                           returned=liters_text(a['returned']), profit_change=a['revenue']-a['fees'])
                yield aid, '', [], row
        elif event['kind'] == 'contract_evaluation':
            evaluation = event['result']
            for aid, result in evaluation['individual'].items():
                row = {'kind': 'agreement', 'round': r, 'contract_id': evaluation['contract_id'],
                       'own_result': {k: result[k] for k in ('status', 'request_met', 'net_met')}}
                yield aid, row['contract_id'], [result['status']], row


def save_experiences(db, rid, state, events):
    db.executemany("INSERT OR IGNORE INTO experiences VALUES(?,?,?,?,?,?,?,?)", (
        (rid, aid, row['round'], row['kind'], subject, row.get('water_per_plant'), ' '.join(tags),
         json.dumps(row, separators=(',', ':')))
        for aid, subject, tags, row in _archive_rows(state, events)))


_TOPICS = {
    'plant': 'plant plants water watering irrigation dose doses growth health seed seedling seedlings sow sowing planted planting harvest',
    'accounts': 'accounts money cost costs fee fees revenue bank coins profit returns returned delivery delivered liquidity',
    'agreement': 'agreement agreements contract contracts breach breaches signature compliance',
}
_TAGS = {
    'died': 'died death deaths dead failed failure', 'sold': 'sold harvested harvest',
    'growing': 'growing immature', 'sown': 'new sown sowing seedlings', 'established': 'existing established',
    'decline': 'decline declined declining', 'gain': 'gain gained', 'breached': 'breached breach breaches',
    'met': 'met fulfilled', 'cancelled': 'cancelled canceled',
}


def _query_filters(query):
    """Return parameterized selectors for facts, never search free-text assertions."""
    query = query.casefold()
    clauses, params = [], []

    def select(column, values):
        if values:
            clauses.append(f"{column} IN (" + ','.join('?' for _ in values) + ')')
            params.extend(values)

    rounds = re.findall(r'\b(?:round|runde)\s*#?\s*(\d+)\b', query)
    select('round', rounds)
    query = re.sub(r'\b(?:round|runde)\s*#?\s*\d+\b', ' ', query)
    ids = re.findall(r'\b[a-e]-p\d+\b|\bc\d+\b', query)
    select('subject', [gid.capitalize() if '-p' in gid else gid for gid in ids])
    query = re.sub(r'\b[a-e]-p\d+\b|\bc\d+\b', ' ', query)
    number = r'(\d+(?:[.,]\d+)?|[.,]\d+)'
    amounts = re.findall(r'(?<![\w.])' + number + r'\s*(?:l\b|lit(?:er|re)s?\b)', query)
    amounts += re.findall(r'\bdose\s*(?:of\s*)?' + number, query)
    if re.fullmatch(number, query.strip()):
        amounts.append(query.strip())
    select('dose', [liters_text(Decimal(amount.replace(',', '.'))) for amount in amounts])
    words = set(re.findall(r'[a-z]+', query))
    kinds = ['plant'] if amounts else [kind for kind, aliases in _TOPICS.items() if words.intersection(aliases.split())]
    select('kind', kinds)
    tags = [tag for tag, aliases in _TAGS.items() if words.intersection(aliases.split())]
    for group in ([t for t in tags if t in ('sown', 'established')], [t for t in tags if t not in ('sown', 'established')]):
        if group:
            clauses.append('(' + ' OR '.join("instr(' ' || tags || ' ', ?) > 0" for _ in group) + ')')
            params.extend(' ' + tag + ' ' for tag in group)
    return clauses, params


def recall_experiences(db, rid, aid, observation, query):
    """Bounded owner lookup. Prefer the requested dose/group/topic over recency."""
    phase, r = observation['phase'], observation['round']
    recent = observation['own_farm']['recent_plant_results']
    shown_plants = {(x['round'], x['group_id']) for x in recent}
    shown_agreements = {(x['round'], x['contract_id']) for x in observation.get('own_agreement_results', [])}
    filters, params = _query_filters(query)
    if query.strip() and not filters:
        return []
    kinds = {1: ('accounts', 'plant', 'agreement'), 2: ('agreement', 'plant', 'accounts'),
             3: ('accounts', 'plant', 'agreement'), 4: ('plant',), 7: ('plant', 'agreement', 'accounts')}
    search_kinds = (None,) if filters else kinds.get(phase, ())
    # Each phase prioritizes a different type. Within a type, sample multiple
    # treatments before repeating a dose. A targeted query can return its trajectory.
    groups = []
    for kind in search_kinds:
        where = ['run_id=?', 'agent_id=?', 'round<=?', *filters]
        values = [rid, aid, r, *params]
        if kind:
            where.append('kind=?')
            values.append(kind)
        if 'agreements' not in observation:
            where.append("kind!='agreement'")
        # The latest settled accounts already appear in own_farm during NEWS.
        if phase == 7:
            where.append("(kind!='accounts' OR round<?)")
            values.append(r)
        # A targeted search reaches the whole archive. Default recall samples a
        # bounded set of recent candidates, even after a thousand identical trials.
        if kind == 'plant' and recent:
            where.append('round<?')
            values.append(recent[0]['round'])
        sql = ('SELECT round,kind,subject,dose,body FROM experiences WHERE '
               + ' AND '.join(where) + ' ORDER BY round DESC,kind,subject')
        rows = db.execute(sql if filters else sql + ' LIMIT 24', values)
        if kind == 'plant':
            inventory = observation['own_farm']['plants']
            group_ids = {g['id'] for g in inventory}
            doses = {liters_text(g['water']) for g in inventory}
            # Within the bounded sample, favor a living group's own trajectory and
            # treatments used on the current inventory. Ties keep recency order.
            rows = sorted(rows, key=lambda row: (row[2] in group_ids, row[3] in doses), reverse=True)
        found, treatments = [], set()
        for number, category, subject, dose, body in rows:
            if category == 'plant' and (number, subject) in shown_plants:
                continue
            if category == 'agreement' and (number, subject) in shown_agreements:
                continue
            if kind == 'plant' and dose in treatments:
                continue
            treatments.add(dose)
            found.append(json.loads(body))
            if len(found) == 3:
                break
        groups.append(found)
    return [group[i] for i in range(3) for group in groups if i < len(group)][:3]
