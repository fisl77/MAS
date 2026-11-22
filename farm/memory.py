"""Select evidence from permitted observations and record exactly what a note cited."""
import json
import re

from .experience import _query_filters, recall_experiences
from .water_budget import liters_text


PUBLIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS public_memory(
 run_id TEXT, source TEXT, peer TEXT, contract_id TEXT, round INTEGER, phase INTEGER, turn INTEGER,
 body TEXT, PRIMARY KEY(run_id,source,peer,contract_id));
CREATE INDEX IF NOT EXISTS memory_peer ON public_memory(run_id,peer,round,phase,turn);
CREATE INDEX IF NOT EXISTS memory_contract ON public_memory(run_id,contract_id,round,phase,turn);
CREATE INDEX IF NOT EXISTS note_history_owner ON events(run_id,json_extract(body,'$.agent_id'),id)
 WHERE json_extract(body,'$.kind')='note_changed';
"""
CONTRACT_FIELDS = ('id', 'version', 'participants', 'limits', 'start_round', 'end_round',
                   'status', 'signatures', 'cancelled_from', 'effective_end', 'replaces')
PEER = re.compile(r'(?i:\bfarm\s+([a-e])\b)|\b([A-E])(?=[:,]|\s+(?i:said|claimed|offered|signed|promised))')
CID = re.compile(r'\bc\d+\b', re.I)
DOSE = re.compile(r'(?<![\w.])(\d+(?:[.,]\d+)?)\s*(?:l\b|lit[er]+s?\b)', re.I)


def peers_in(text):
    return list(dict.fromkeys((a or b).upper() for a, b in PEER.findall(text)))


def save_public_memory(db, rid, events, register):
    for i, event in enumerate(events):
        r, phase, turn = event['round'], event['phase'], event.get('turn', 0)
        if event['kind'] == 'news':
            for peer, amount in event['news'].get('net_withdrawals', {}).items():
                applicable = [c['id'] for c in register if peer in c['participants']
                              and c.get('accepted_round', r+1) <= r and c['start_round'] <= r <= c['effective_end']]
                record = json.dumps(dict(kind='published_withdrawal', round=r, agent_id=peer,
                                         net_liters=liters_text(amount)))
                db.executemany('INSERT OR IGNORE INTO public_memory VALUES(?,?,?,?,?,?,?,?)',
                               ((rid, f'n:{r}:{peer}', peer, cid, r, phase, -1, record) for cid in applicable or ['']))
            continue
        if event['kind'] == 'message' and event['text'].strip():
            sender, text = event['sender'], event['text']
            row = dict(kind='claim', round=r, phase=phase, turn=turn, sender=sender, text=text)
            peers = {sender, *peers_in(text)}
            contracts = {c.lower() for c in CID.findall(text)}
            source = f'm:{r}:{phase}:{turn}:{sender}'
        elif event['kind'] == 'contract_action':
            contract = event['contract']
            row = dict(kind='contract_record', round=r, phase=phase, turn=turn, actor=event['actor'],
                       action=event['action']['kind'], **{k: contract[k] for k in CONTRACT_FIELDS})
            peers, contracts = contract['participants'], [contract['id']]
            source = f's:{r}:{phase}:{turn}:{contract["id"]}:{i}'
        else:
            continue
        body = json.dumps(row, separators=(',', ':'))
        db.executemany('INSERT OR IGNORE INTO public_memory VALUES(?,?,?,?,?,?,?,?)',
                       ((rid, source, p, c, r, phase, turn, body) for p in peers for c in contracts or ['']))


def public_matches(db, rid, aid, obs, text, *, explicit=False):
    if 'agreements' not in obs:
        return []
    ids = [c.lower() for c in CID.findall(text)]
    peers = [p for p in peers_in(text) if p != aid]
    keys = ids or peers
    if not keys:
        return []
    column = 'contract_id' if ids else 'peer'
    slots = ','.join('?' for _ in keys)
    rounds = re.findall(r'\bround\s+#?(\d+)\b', text, re.I) if explicit else []
    round_filter = ' AND round=?' if rounds else ''
    asks_claim = re.search(r'\b(?:said|say|told|claim\w*|promise\w*|statement)\b', text, re.I)
    official_first = not asks_claim and (ids or re.search(r'\bsign\w*|\bcontract|\bagreement', text, re.I))
    preferred = 's:%' if official_first else 'm:%'
    withdrawal = re.search(r'\b(?:net|withdr\w*|used|honou?r\w*|compli\w*|breach\w*)\b', text, re.I)
    if withdrawal and peers and not asks_claim:
        preferred = 'n:%'
    rows = db.execute(f'SELECT DISTINCT source,round,phase,turn,body FROM public_memory WHERE run_id=? '
                      f'AND {column} IN ({slots}){round_filter} AND (round,phase,turn)<(?,?,?) '
                      'ORDER BY source LIKE ? DESC,round DESC,phase DESC,turn DESC,source DESC LIMIT 32',
                      [rid, *keys, *rounds[:1], obs['round'], obs['phase'], obs['conversation_turn'], preferred])
    seen_messages = {(m['sender'], m.get('text')) for k in ('messages', 'followup_messages', 'older_discussion')
                     for m in obs.get(k, [])}
    register = {c['id']: c for c in obs['agreements']}
    matches = []
    for _, _, _, _, body in rows:
        row = json.loads(body)
        if row['kind'] == 'claim':
            key = (row['sender'], row['text'])
            if key in seen_messages:
                continue
            seen_messages.add(key)
            row['source_type'] = 'unverified_own_statement' if row['sender'] == aid else 'unverified_peer_claim'
        elif row['kind'] == 'published_withdrawal':
            if (not withdrawal or peers and row['agent_id'] not in peers
                    or row['round'] == obs['news']['round']):
                continue
        elif row['id'] in register and all(row[k] == register[row['id']][k] for k in CONTRACT_FIELDS):
            continue
        matches.append(row)
    return matches[:3]


def identity(row):
    return (row['kind'], row['round'], row.get('group_id'), row.get('contract_id') or row.get('id'),
            row.get('phase'), row.get('turn'), row.get('sender') or row.get('agent_id'), row.get('action'))


def decision_recall(db, rid, aid, obs, query, turn_text='', public=False):
    """Order by an explicit lookup, the current question, the farm's plan and finally phase."""
    own = obs['own_farm']
    limit = 1 if public else 3

    def measured(text):
        saved = recall_experiences(db, rid, aid, obs, text)
        if not public:
            return saved
        # During a public turn the recent-results table is removed at formatting
        # time. Its matching rows must compete for the single displayed slot.
        filters, params = _query_filters(text)
        if text and not filters:
            return saved
        fresh = []
        for result in obs.get('own_agreement_results', []):
            cid = result['contract_id']
            if cid in CID.findall(text.lower()) and not re.search(r'\b(?:sign|propos|accept|offer)', text, re.I):
                fresh.append({'kind': 'agreement', **result})
        for row in own['recent_plant_results']:
            tags = [row.get('stage', ''), row['outcome']]
            if row['health'][1] < row['health'][0]:
                tags.append('decline')
            if row['growth'][1] > row['growth'][0]:
                tags.append('gain')
            sql = 'SELECT 1 FROM (SELECT ? AS round, ? AS subject, ? AS dose, ? AS kind, ? AS tags)'
            if filters:
                sql += ' WHERE ' + ' AND '.join(filters)
            if db.execute(sql, (row['round'],row['group_id'],row['water_per_plant'],'plant',' '.join(tags),*params)).fetchone():
                fresh.append(row)
        return fresh + saved

    if query.strip():
        social = public_matches(db, rid, aid, obs, query, explicit=True)
        facts = measured(query)
        personal_result = re.search(r'\b(?:my|our|own)\b', query, re.I) or not peers_in(query) and re.search(
            r'\b(?:met|breach\w*|compli\w*)\b', query, re.I)
        result = facts + social if personal_result else social + facts
        return result[:limit]
    notes = own['memory']
    targets = list(dict.fromkeys(x['water_per_plant'] for x in own.get('planned_sowing', [])))
    candidates = {}

    def include(rows):
        for row in rows:
            candidates.setdefault(identity(row), row)
            if len(candidates) >= limit:
                return True
        return False

    for text in (turn_text, notes.get('open_question', ''), notes.get('goal', '')):
        if not text:
            continue
        social = public_matches(db, rid, aid, obs, text)
        if not peers_in(text) and re.search(r'\b(?:met|breach\w*|compli\w*|honou?r\w*|fulfill\w*)\b', text, re.I):
            if include(measured(text)[:1]):
                return list(candidates.values())
        asks_for_trial = DOSE.search(text) and re.search(r'\b(?:own|my|our|test\w*|grow\w*|health|surviv\w*)\b', text, re.I)
        if public and text == turn_text and '?' in text and not DOSE.search(text):
            addressed = peers_in(text)
            if (not addressed or aid in addressed) and re.search(r'\b(?:experiments?|trials?|test results?)\b', text, re.I):
                if include(measured('plant')[:1]):
                    return list(candidates.values())
        if not asks_for_trial and include(social):
            return list(candidates.values())
        amounts = [n.replace(',', '.') for n in DOSE.findall(text)]
        stage = ('established' if re.search(r'\bestablished|\bexisting|\bmature', text, re.I) else
                 'sown' if re.search(r'\bseedling|\bsow|\bnew plant', text, re.I) else '')
        if not amounts and targets and not stage and re.search(r'\bwater|\bdose|\bplant|\bgrowth', text, re.I):
            stage = 'sown'
        for dose in dict.fromkeys(amounts or (targets if stage == 'sown' else [])):
            if include(measured(f'dose {dose} {stage}')[:1]):
                return list(candidates.values())
        if asks_for_trial and include(social):
            return list(candidates.values())
        if not amounts and not social and include(measured(text)[:1]):
            return list(candidates.values())
    for dose in targets:
        if include(measured(f'dose {dose} sown')[:1]):
            return list(candidates.values())
    if obs['phase'] in (1, 3, 4):
        for dose in dict.fromkeys(liters_text(g['water']) for g in own['plants']):
            if include(measured(f'dose {dose} established')[:1]):
                return list(candidates.values())
    include(measured(''))
    return list(candidates.values())


def records(value):
    if isinstance(value, dict) and 'columns' in value:
        return [dict(zip(value['columns'], row)) for row in value['rows']]
    return value


def shown_sources(obs):
    """Use only the final, possibly windowed or losslessly packed model context."""
    refs = {}
    for prefix, rows in [('recall', obs['recalled_experiences']), ('plant', obs['own_farm']['recent_plant_results']),
                         ('message', obs.get('messages', [])), ('direct', obs.get('followup_messages', [])),
                         ('result', obs.get('own_agreement_results', []))]:
        for i, row in enumerate(records(rows), 1):
            refs[f'{prefix}:{i}'] = row
    refs.update((c['id'], c) for c in records(obs.get('agreements', [])))
    own = obs['own_farm']
    refs['accounts'] = {k: own[k] for k in ('id', 'bank', 'debt', 'net_balance', 'profit', 'fees',
                                            'delivery_fee', 'return_fee', 'revenue', 'delivered', 'returned') if k in own}
    refs['news'] = obs['news']
    return refs
