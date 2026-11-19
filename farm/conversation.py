"""Conservative repetition checks on published messages, never private agent notes."""
from difflib import SequenceMatcher
import re
from .schema import PUBLIC_MESSAGE_LIMIT


def fee_claim_needs_review(text):
    """Advisory trigger for common fee misconceptions, not a truth/deception judge."""
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', text.casefold().replace('’', "'")):
        if '?' in sentence or re.search(r"\b(no|not|cannot|can't|don't|doesn't|never)\b", sentence):
            continue
        fees = re.search(r'\b(delivery|return|shipping|transport)\s+(fees?|costs?|charges?)\b', sentence)
        if not fees:
            continue
        if re.search(r'\b(shar\w*|split\w*|pool\w*|waiv\w*|amortiz\w*)\b', sentence):
            return True
        if fees[1] == 'delivery' and re.search(r'\b(avoid\w*|sav\w*|reduc\w*|minimiz\w*|eliminat\w*)\b', sentence):
            if not re.search(r'\b(zero|skip\w*|forgo\w*|forego\w*)\b', sentence):
                return True
    return False


# Changes to amounts, polarity, scope or commitment must not be treated as paraphrases.
_MEANING_WORDS = frozenset("""no not never without unless except cannot can't won't don't
doesn't isn't aren't neither only all each per shared individual total combined optional
mandatory required guaranteed binding voluntary active inactive accept accepted reject
rejected cancel cancelled propose proposal replace instead increase decrease more less
higher lower must will may could would should can a b c d e request requests return
returned delivery delivered withdrawal net irrigation planting sowing growth health
died sold lost profit bank fee fees cost costs income coins today tomorrow now later
next current future before after until first last sufficient insufficient enough
available unavailable empty full free paid unpaid affordable unaffordable""".split())


def _units(text):
    text = text.casefold().replace("’", "'")
    text = re.sub(r"^\s*(?:round\s+\d+\s*[,.-]?\s*)?phase\s+\d+\s*[:.-]\s*", "", text)
    text = re.sub(r"^\s*farm\s+[a-e]\s+here\s*[-:]\s*", "", text)
    text = re.sub(r"^\s*farm\s+[a-e](?:\s*(?:,|and)\s*(?:farm\s+)?[a-e])*\s*[-:]\s*", "", text)
    units = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", text) if x.strip()]
    if len(units) > 1:
        units = [x for x in units if not re.fullmatch(r"\d+[.)]", x)]
    return [x for x in units if x.rstrip('.!') not in ("thanks", "thank you", "agreed", "understood", "ok", "okay")]


def _same_unit(current, previous):
    # A renamed agreement alone contributes no new claim. Actual signed actions are checked separately.
    current = re.sub(r'\bc\d+\b', 'contract', current, flags=re.I)
    previous = re.sub(r'\bc\d+\b', 'contract', previous, flags=re.I)
    words = lambda x: re.findall(r"\w+(?:[.']\w+)*|[<>≤≥=]", x)
    a, b = words(current), words(previous)
    if not a or not b:
        return current == previous
    if ('?' in current) != ('?' in previous):
        return False
    if a == b:
        return True
    if '?' in current:
        # A changed question may ask about a different action despite similar wording.
        return False
    if re.findall(r"\d+(?:\.\d+)?", current) != re.findall(r"\d+(?:\.\d+)?", previous):
        return False
    if set(a) & _MEANING_WORDS != set(b) & _MEANING_WORDS:
        return False
    # Short, changed answers can carry a new decision in just one or two words.
    return min(len(a), len(b)) >= 8 and SequenceMatcher(None, a, b, autojunk=False).ratio() >= .82


def is_repeated_message(text, earlier_texts):
    """Every sentence must repeat a sentence from the supplied earlier contributions.

    New sentences, changed numeric terms and changed commitment/polarity keep a message
    novel. This intentionally misses some semantic repetitions rather than assuming
    that a new question or changed offer is redundant.
    """
    if not earlier_texts:
        return False
    old_units = [unit for earlier in earlier_texts for unit in _units(earlier)]
    return all(any(_same_unit(unit, old) for old in old_units) for unit in _units(text))


def classify_public_pass(previous_messages, contributions):
    novel, repeated = [], []
    for contribution in contributions:
        text, aid = contribution['text'], contribution['sender']
        if not text.strip():
            continue
        earlier = [m['text'] for m in previous_messages if m['text'].strip()]
        own = [m['text'] for m in previous_messages if m['sender'] == aid]
        # A first concise statement of personal consent/objection is new information.
        stance = len(text.split()) <= 25 and re.match(r"\s*i\s+(agree|support|accept|reject|oppose)\b", text, re.I)
        duplicate = is_repeated_message(text, earlier)
        if stance and not is_repeated_message(text, own):
            duplicate = False
        (repeated if duplicate else novel).append(aid)
    return {'novel_agents': novel, 'repeated_agents': repeated}


def repeats_without_progress(s, aid, decision):
    """Check a published-text echo after validation, preserving fresh signatures/terms."""
    if decision.pass_turn or not decision.message.strip():
        return False
    history = [m for m in s['messages'] if (m['round'], m['phase']) == (s['round'], s['phase'])]
    result = classify_public_pass(history, [{'sender': aid, 'text': decision.message}])
    if aid not in result['repeated_agents']:
        return False
    if decision.contracts:
        from copy import deepcopy
        from .contracts import apply_contract_action
        candidate = deepcopy(s)
        for action in decision.contracts:
            apply_contract_action(candidate, aid, action)
        if candidate['contracts'] != s['contracts']:
            return False
    return True


def current_progress(s):
    progress = s.get('conversation_progress', {})
    if progress.get('round') == s['round'] and progress.get('phase') == s['phase']:
        return progress
    return {'stalled_passes': 0, 'repeated_agents': []}


def phase_budget(s):
    """Persisted accounting for the current phase."""
    saved = s.get('conversation_budget', {})
    if saved.get('round') == s['round'] and saved.get('phase') == s['phase']:
        return saved
    return {'round': s['round'], 'phase': s['phase'],
            'messages_used': {aid: 0 for aid in s['agents']}, 'quiet_passes': 0,
            'passed_agents': []}


def eligible_speakers(s):
    budget = phase_budget(s)
    return [aid for aid in s.get('public_active_agents', s['agents'])
            if budget['messages_used'].get(aid, 0) < PUBLIC_MESSAGE_LIMIT]


def speaker_order(s):
    """Eligible farms in speaking order, starting with the next turn."""
    ring = list(s['agents'])
    eligible = set(eligible_speakers(s))
    if not eligible:
        return []
    last = phase_budget(s).get('last_speaker')
    discussion = s.get('last_conversation_end', {})
    if not last and s['phase'] == 7 and discussion.get('round') == s['round'] and discussion.get('phase') == 2:
        last = discussion.get('opener')
    if last in ring:
        index = ring.index(last) + 1
    else:
        start = s['config']['start_agent']
        active = [a for a in ring[start:] + ring[:start] if a in eligible]
        opener = active[(s['round'] - 1 + int(s['phase'] == 7)) % len(active)]
        index = ring.index(opener)
    return [a for a in ring[index:] + ring[:index] if a in eligible]


def pass_key(message):
    return (message['round'], message['phase'], message['turn'])


def _excerpt(message):
    """Quote the speaker. A shortened quotation is never a new factual assertion."""
    text = ' '.join(message['text'].split())
    if len(text) > 180:
        text = text[:179].rsplit(' ', 1)[0] + '…'
    return {k: message[k] for k in ('sender', 'round', 'phase', 'turn')} | {'text': text}


_DISCUSSION_TOPICS = {
    'plant care': re.compile(r'\b(plant\w*|sow\w*|dose\w*|growth|health|seed\w*|irrigat\w*|harvest\w*)\b', re.I),
    'water supply': re.compile(r'\b(water|pond|rain|dry|request\w*|deliver\w*|liters?)\b', re.I),
    'agreements': re.compile(r'\b(agre\w*|contract\w*|propos\w*|offer|terms|cap|limit|sign\w*|c\d+)\b', re.I),
    'costs and income': re.compile(r'\b(fees?|costs?|profit|coins?|sold|bank|revenue)\b', re.I),
}


def _summarize(older, message):
    if not message['text'].strip():
        return
    sender = message['sender']
    previous = older.get(sender, {})
    topics = set(previous.get('topics', ()))
    topics.update(name for name, pattern in _DISCUSSION_TOPICS.items() if pattern.search(message['text']))
    quote = _excerpt(message)
    if previous and re.fullmatch(r'(ok(ay)?|thanks|thank you|understood)[.! ]*', quote['text'], re.I):
        quote = previous
    older[sender] = {**quote, 'topics': sorted(topics),
                     'statements': previous.get('statements', 0) + 1}


def retain_public_history(s):
    # Once a message leaves the dashboard window, keep one attributed excerpt
    # per speaker as background for later phases. Full messages are event records.
    if len(s['messages']) <= 200:
        return
    older = s.setdefault('past_discussion', {})
    s['archived_message_count'] = s.get('archived_message_count', 0) + len(s['messages'])-200
    for message in s['messages'][:-200]:
        _summarize(older, message)
    s['messages'] = s['messages'][-200:]


def _attribution(sender, aid):
    return 'unverified_own_statement' if sender == aid else 'unverified_peer_claim'


def _public_message(message, aid):
    published = {k: message[k] for k in ('round', 'phase', 'turn', 'sender', 'text')}
    published['source_type'] = _attribution(message['sender'], aid)
    # Action receipts carry real IDs and statuses. The register carries all terms.
    actions = [{'kind': result['action']['kind'], 'status': result['status'],
                'contract_id': result.get('contract_id') or result['action'].get('contract_id')}
               for result in message.get('contract_results', [])]
    if actions:
        published['agreement_actions'] = actions
    return published


def _followup_key(message, open_ids, aid, s):
    """Select relevant public quotes without inferring whether anyone answered."""
    mentioned = re.findall(r'\bc\d+\b', message['text'], re.I)
    receipts = [r['contract_id'] for r in message.get('contract_results', []) if r.get('contract_id')]
    for cid in [*receipts, *mentioned]:
        if cid.lower() in open_ids:
            return ('contract', cid.lower())
    if (message['round'], message['phase']) != (s['round'], s['phase']):
        return None
    text = message['text']
    addressed = re.search(rf'\bfarm\s+{aid}\b', text, re.I) or re.search(rf'\b{aid}\s*[:,]', text)
    named = re.findall(r'\bfarm\s+([a-e])\b', text, re.I) or re.findall(r'\b([A-E])\s*[:,]', text)
    group_question = re.search(r'\b(everyone|anyone|all farms|each farm|any farm|other farms|alle|jemand)\b', text, re.I)
    if '?' in text and (addressed or group_question or not named):
        return ('question', message['sender'], ' '.join(text.casefold().split()))
    # A closed contract reference is historical context, not a fresh open offer.
    if mentioned or receipts:
        return None
    shared = re.search(r'\b(we|each|all|everyone|per farm)\b', text, re.I)
    if (addressed or shared or message['sender'] == aid) and re.search(
            r'\b(offer|terms|propos\w*|cap|deal|limit|counteroffer|angebot|vorschlag)\b', text, re.I):
        return ('offer', message['sender'])
    return None


def public_discussion(s, aid):
    """Two recent, complete speaking passes and bounded older attributed excerpts."""
    history = s['messages']
    recent_keys = list(dict.fromkeys(pass_key(m) for m in history if m['round'] >= s['round']-1))[-2:]
    current, older = [], dict(s.get('past_discussion', {}))
    open_ids = {c['id'] for c in s['contracts'] if c['status'] == 'proposed' and aid in c['participants']}
    followups = {}
    current_topics = set()
    direct_quotes = set()
    full_quotes = set()
    for index, message in enumerate(history):
        topic = _followup_key(message, open_ids, aid, s)
        if pass_key(message) not in recent_keys:
            _summarize(older, message)
            if topic and message['text'].strip():
                followups[topic] = (index, message)
            continue
        current.append(_public_message(message, aid))
        current_topics.add(topic)
        direct_quotes.add((message['sender'], _excerpt(message)['text']))
        full_quotes.add((message['sender'], message['text']))
    candidates = sorted((item for topic, item in followups.items() if topic not in current_topics),
                        key=lambda item: (pass_key(item[1]), item[0]), reverse=True)
    selected = []
    for _, m in candidates:
        quote = (m['sender'], m['text'])
        if quote not in full_quotes:
            selected.append(_public_message(m, aid))
            full_quotes.add(quote)
            direct_quotes.add((m['sender'], _excerpt(m)['text']))
        if len(selected) == 2:
            break
    summary = [item | {'source_type': _attribution(item['sender'], aid)}
               for item in older.values() if (item['sender'], item['text']) not in direct_quotes]
    return {'messages': current, 'older_discussion': sorted(summary, key=pass_key),
            'followup_messages': sorted(selected, key=pass_key),
            'public_messages_outside_window': s.get('archived_message_count', 0) + len(history)-len(current)-len(selected)}


def turn_messages(s, aid):
    """Latest public contribution and most recent direct question since the farm last spoke."""
    history = [m for m in s['messages'] if (m['round'], m['phase']) == (s['round'], s['phase'])]
    latest = history[-1:]  # Empty at the start of each new discussion.
    address = re.compile(rf'\bfarm\s+{aid}\b|\b{aid}\s*[:,]', re.I)
    question = None
    for m in reversed(history):
        if m['sender'] == aid:
            break
        if '?' in m['text'] and address.search(m['text']):
            question = m
            break
    follow = [question] if question and question not in latest else []
    return latest, follow


def experience_topic(text):
    doses = re.findall(r'(\d+(?:\.\d+)?)\s*(?:L\b|liters?\b)', text, re.I)
    if _DISCUSSION_TOPICS['plant care'].search(text) or (doses and re.search(r'\b(happened|outcome|respond\w*)\b', text, re.I)):
        return 'plant', doses
    if _DISCUSSION_TOPICS['costs and income'].search(text):
        return 'accounts', []
    if _DISCUSSION_TOPICS['agreements'].search(text):
        return 'agreement', []
    return None, []


def turn_recall_query(s, aid):
    latest, direct = turn_messages(s, aid)
    reference = direct or latest
    if reference:
        kind, doses = experience_topic(reference[0]['text'])
        if kind == 'plant':
            return 'growth' + (' dose ' + doses[0] if doses else '')
        if kind:
            return kind
    return ''


def focus_public_turn(s, aid, obs):
    """Prepare the deciding farm's public context using its own observed records."""
    latest, follow = turn_messages(s, aid)
    selected = [*latest, *follow]
    text = ' '.join(m['text'] for m in (follow or latest))
    referenced = set(re.findall(r'\bc\d+\b', ' '.join(m['text'] for m in selected).lower()))
    referenced.update(a['contract_id'] for m in selected for a in m.get('contract_results', [])
                      if a.get('contract_id'))
    obs['agreements'].sort(key=lambda c: (c['id'] not in referenced,
        not (c['status'] == 'proposed' and aid in c['participants'] and aid not in c['signatures'])))
    own = obs['own_farm']
    recent = own['recent_plant_results']
    recalled = obs.pop('recalled_experiences')
    details = recalled + recent if s['agents'][aid].get('recall_query') else recent + recalled
    details.extend({'kind': 'agreement', **result} for result in obs.pop('own_agreement_results', []))
    kind, doses = experience_topic(text)
    candidates = [d for d in details if not kind or d.get('kind') == kind]
    detail = next((d for d in candidates if d.get('water_per_plant') in doses), next(iter(candidates), None))
    if obs.pop('focused_recall', False):
        detail = next(iter(recalled), None)
    own['recent_plant_results'] = []
    own.pop('cultivation_evidence', None)
    obs['older_discussion'] = [{k: item[k] for k in ('sender', 'topics', 'statements', 'source_type') if k in item}
                               for item in obs.get('older_discussion', [])]
    obs['public_messages_outside_window'] = s.get('archived_message_count', 0) + len(s['messages']) - len(selected)
    obs.pop('messages', None)
    obs.pop('followup_messages', None)
    obs['recalled_experiences'] = [detail] if detail else []
    obs['followup_messages'] = [_public_message(m, aid) for m in follow]
    obs['messages'] = [_public_message(m, aid) for m in latest]
