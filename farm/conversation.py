"""Public conversation history, repeated contributions and verifiable fee claims."""
from difflib import SequenceMatcher
from decimal import Decimal
import re
from .knowledge import return_cost
from .schema import PUBLIC_MESSAGE_LIMIT


_FEE = re.compile(r'\b(delivery|return|shipping|transport)\s+(?:fees?|costs?|charges?|rates?)\b')
_AMOUNT = r'(free|zero|\d+(?:[.,]\d+)?\s*coins?)\b'
_RATE = re.compile(r'^\s*,?\s*(?:which\s+)?(?:(?:is|are|was|were|has been|have been|stands at|amounts to|remains at|of|costs?|at|to)\s+)?'
                   r'(?:(?:currently|now|still|always|fixed at|set at|a fixed|only|exactly|flat)\s+)*' + _AMOUNT)
_CHANGE = (r'(?:increas(?:e[ds]?|ing)|decreas(?:e[ds]?|ing)|ris(?:e[sn]?|ing)|rose|hikes?|changes?|changed|'
           r'doubled|halved|raised|lowered|(?:go|went|gone) (?:up|down|from))')
_HISTORICAL_COMPARISON = re.compile(r'\b(?:higher|lower|greater|smaller|more|less|different)\s+than\s+'
                                    r'(?:(?:it|they|we|i)\s+)?(?:usual|normal|before|last|previously|earlier|'
                                    r'previous rounds?|used to|historical\w*)\b')
_PAYMENT = re.compile(r"\b(?:(?:i|we) (?:actually |just )?(?:paid|was charged|were charged)\s+(?:a |the |my |our )?"
                      r"(?:(?P<before>\d+(?:[.,]\d+)?) coins? (?:for|in|as) (?:a |the |my |our )?)?|"
                      r"(?:my|our) (?=\w+ (?:fees?|charges?) (?:was|were|came to)\b))"
                      r"(?P<kind>delivery|return|transport|shipping) (?:fees?|costs?|charges?)\b"
                      r"(?: (?:of |was |were |came to )?(?P<after>\d+(?:[.,]\d+)?) coins?)?")


def payment_conflict(text, s, aid):
    """Check a farm's own explicitly dated debit using its settled account."""
    for sentence in re.split(r'(?<=[.!?;])\s+|\n+', text.casefold()):
        date = re.search(r'\b(?:round (\d+)|(this|last|previous) round)\b', sentence)
        if not date or '?' in sentence or re.search(r'\b(?:total|since|cumulative|across|if)\b', sentence):
            continue
        number = int(date[1]) if date[1] else s['round'] - int(date[2] != 'this')
        if not 1 <= number <= len(s['history']):
            continue
        account = s['history'][number-1]['agents'][aid]
        for payment in _PAYMENT.finditer(sentence):
            value = payment['before'] or payment['after']
            kind = 'return' if payment['kind'] == 'return' else 'delivery'
            actual = Decimal(account[kind + '_fee']) / 100
            if value and Decimal(value.replace(',', '.')) != actual:
                return f"Your own round {number} {kind} charge was {actual} coins."
    return ''


def fee_claim_needs_review(text, config):
    """Check assertions about this game's fixed tariffs, including premises inside questions."""
    draft = text.casefold().replace('’', "'")
    previous_kind = None
    for clause in re.split(r'(?<=[.!?;])\s+|\n+|\s+(?:but|whereas)\s+', draft):
        # Water allocation is supplied by the game. There is no carrier selection
        # or market for a transport contract, even for a farm with free delivery.
        provider = re.search(r'\b(?:delivery|transport|shipping|water) (?:service|provider|carrier|supplier)s?\b', clause)
        if provider and not re.search(r"\b(?:no|not|cannot|can't|don't|doesn't|whether)\b", clause):
            asks_if_available = re.match(r'\s*(?:(?:is|are) there|(?:can|could|may) (?:we|i|a farm|farms) '
                                         r'(?:choose|select|switch|use)|does the game (?:offer|allow))\b', clause)
            if not (asks_if_available and clause.rstrip().endswith('?')):
                return True
        if previous_kind and not _FEE.search(clause):
            clause = re.sub(r'\b(the|this|that) (fee|rate)\b', rf'\1 {previous_kind} \2', clause)
        fees = list(_FEE.finditer(clause))
        kinds = {fee[1] for fee in fees}
        previous_kind = kinds.pop() if len(kinds) == 1 else None
        for index, fee in enumerate(fees):
            before = clause[fees[index-1].end() if index else 0:fee.start()]
            after = clause[fee.end():fees[index+1].start() if index+1 < len(fees) else None]
            actual = return_cost(config) if fee[1] == 'return' else config['delivery_fee_coins']
            if re.search(r'\b(?:aggregate|total|cumulative)\s+$', before):
                continue
            # A paid amount, prediction or open verification question is different from a tariff.
            open_question = '?' in clause and re.match(r"\s*(?:did|does|is|are|has|have|can|could|will|would)\b", clause)
            qualified = re.search(r"\b(?:if|whether|might|could|hypothetically|hasn't|haven't|didn't|no|never)\b"
                                  r"|\b(?:did|has|have|is|was|were) not\b", before)
            change = (re.match(rf'\s+(?:(?:was|were|has|have|had|been|recently|just|now)\s+)*{_CHANGE}\b', after)
                      or re.search(rf'\b(?:{_CHANGE})\s+(?:in|to)\s+(?:the |our )?$', before)
                      or re.search(r'\b(?:recent(?:ly)?|new(?:ly)?|now)\s+(?:higher|lower|raised|increased|reduced)\s+$', before)
                      or re.search(r'\b(?:higher|lower|increased|reduced)\s+$', before) and 'news' in clause)
            # "Can you explain the recent fee increase?" presupposes a change.
            presupposed = (re.search(r'\bwhy\b|\b(?:the|this|that|recent)\s+(?:recent\s+)?'
                                     r'(?:increase|decrease|rise|hike|change)\s+(?:in|to)\s+(?:the |our )?$', before) or
                           re.search(r'\b(?:the|a|this|that|recent)\s+(?:recent\s+)?$', before)
                           and re.match(r'\s+(?:increase|decrease|hike)\b', after))
            if (change or _HISTORICAL_COMPARISON.search(after)) and not qualified and (not open_question or presupposed):
                return True
            rate = _RATE.match(after)
            paid_amount = any(pay.start() <= fee.start() < pay.end() for pay in _PAYMENT.finditer(clause))
            if rate and not qualified and not open_question and not paid_amount:
                stated = 0 if rate[1] in ('free', 'zero') else Decimal(re.match(r'[\d.,]+', rate[1])[0].replace(',', '.'))
                no_event = re.search(r'\b(?:if|when|with|for)\s+(?:there is |we have |i have )?(?:a )?(?:no|zero)\b',
                                     after[rate.end():])
                if stated != actual and not (stated == 0 and no_event):
                    return True
                if actual and re.match(r'\s+(?:for each|per)\s+(?:lit(?:er|re)|plant)\b', after[rate.end():]):
                    return True
            if not actual or '?' in clause or re.search(r"\b(?:no|not|cannot|can't|don't|doesn't|never|if)\b", clause):
                continue
            if (re.search(r'\b(?:shar\w*|split\w*|pool\w*|waiv\w*|amortiz\w*)\s+(?:(?:the|our|their|my|these)\s+)?$', before)
                    or re.match(r"\s+(?:(?:can|will|may) be|are|is)\s+(?:shared|split|pooled|waived)\b", after)):
                return True
            if fee[1] != 'return' and re.search(r'\bavoid\w*\b.*\b(?:positive delivery|water is delivered)\b', after):
                return True
            if fee[1] != 'return':
                saving = (re.search(r'\b(?:avoid\w*|sav\w*|reduc\w*|optimi[sz]\w*|minimi[sz]\w*|'
                                    r'lower\w*|discount\w*|eliminat\w*)\s+'
                                    r'(?:(?:our|my|your|the|unnecessary)\s+)?$', before)
                          or re.match(r'\s+(?:low|lower|down)\b', after))
                fewer = re.search(r'\b(?:zero|skip\w*|fewer|less often|forgo\w*|forego\w*)\b', draft)
                if saving and not fewer:
                    return True
    return False


def unsupported_water_rule(text):
    for clause in re.split(r'(?<=[.!?;])\s+|\n+', text.casefold().replace('’', "'")):
        if re.search(r"\b(?:not|no|cannot|can't|whether)\b", clause) or clause.rstrip().endswith('?'):
            continue
        if re.search(r'\b(?:water loss(?:es)?|lost water|water (?:is |gets )?lost|losing water)\s+'
                     r'(?:in|during) (?:transport(?:ation)?|transit|shipping|delivery)\b', clause):
            return True
        for amount in re.findall(r'\b(?:order(?:ing)?|request(?:ing)?)\s+(?:exactly |just |only )?'
                                 r'(\d+[.,]\d+)\s*(?:l|liters?|litres?)\b', clause):
            value = Decimal(amount.replace(',', '.'))
            if value != value.to_integral_value():
                return True
    return False


def is_spoken_pass(text):
    sentences = _units(text)
    if not sentences:
        return False
    return all(re.fullmatch(r"(?:(?:i(?:'ll| will)|let me) pass(?: for now| this turn)?|"
                            r"(?:i(?:'m| am) considering the latest question\b[^.?!]*?\bbut )?i (?:have nothing new to (?:add|share)|"
                            r"(?:do not|don't) have any new information to (?:add|share)))[.!]?", sentence)
               for sentence in sentences)


_BOUND = re.compile(r'\bmax(?:imum)?[ _-]+(net|request)(?:[ _-]+(?:withdrawal|use|limit))?\s*'
                    r'(?:(?:of|is|was|at|to)\s+|[:=]\s*)?(\d+(?:[.,]\d+)?)\b')


def unsupported_agreement_terms(text, register=()):
    """Formal agreements can cap a farm's order or net water, both measured for the whole farm."""
    formal = r'\b(?:contracts?|agreements?|pacts?|deals?|proposals?|c\d+)\b'
    if not re.search(formal, text, re.I) and not _BOUND.search(text.casefold()):
        return False
    for sentence in re.split(r'(?<=[.!?;])\s+|\n+|,\s+(?=(?:not|without)\b)|\s+but\s+',
                             text.casefold().replace('’', "'")):
        for bound in _BOUND.finditer(sentence):
            key = 'max_' + bound[1]
            amount = Decimal(bound[2].replace(',', '.'))
            if (key == 'max_net' and re.search(r'\b(?:not a (?:standard|valid) unit|'
                                               r'must be (?:an integer|a whole (?:number|liter)))\b', sentence)):
                return True
            if key == 'max_request' and amount != amount.to_integral_value():
                return True
            # A new offer can have new terms. A stated existing bound has a public record.
            ids = re.findall(r'\bc\d+\b', sentence)
            old_terms = re.search(r'\b(?:our|your|the|this|signed|active) (?:current |existing |signed )?'
                                  r'(?:contract|agreement|proposal)\b', sentence)
            if not (ids or old_terms) or '?' in sentence or re.search(
                    r'\b(?:propose|suggest|instead|could|would|if|replace|change|not)\b', sentence):
                continue
            terms = [lim[key] for c in register
                     if (c['id'] in ids if ids else c['status'] in ('active', 'proposed'))
                     for lim in c['limits'] if lim.get(key) is not None]
            if all(Decimal(str(limit)) != amount for limit in terms):
                return True
        if re.search(r"\b(?:not|no|cannot|can't|never|whether)\b", sentence) or sentence.rstrip().endswith('?'):
            continue
        if not re.search(formal, sentence) and not re.match(r'\s*(?:it|its|these terms|the cap|the limit)\b', sentence):
            continue
        restriction = re.search(r'\b(?:cap(?:s|ped)?|limit(?:s|ed)?|restrict(?:s|ed)?|fix(?:es|ed)?|mandates?)\b', sentence)
        if not restriction:
            continue
        bound = sentence[restriction.end():]
        if re.match(r'\s+(?:(?:our|your|the|each farm.s|my)\s+)?(?:delivery|return|transport|shipping)\s+(?:fee|cost|charge)s?\b', bound):
            return True
        if re.search(r'\b(?:to|at|of)\s+\d+(?:[.,]\d+)?\s*(?:l|liters?|litres?)\s+(?:per|for each)\s+(?:plant|seedling)\b', bound):
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
    units = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+|,\s+but\s+(?=i(?:'d| would) like to\b)", text) if x.strip()]
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
        # Only strip conversational padding. Retain the action, addressee, quantities and polarity.
        padding = r"\b(?:please|perhaps|exactly|could you (?:please )?tell (?:me|us)|can you tell (?:me|us))\b"
        return words(re.sub(padding, '', current)) == words(re.sub(padding, '', previous))
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


def _generic_question(text):
    """Keep the addressee, topic and requested information when stripping conversational framing."""
    if '?' not in text or re.search(r'\d|\b(?:today|yesterday|since|this round|last round|this time)\b', text, re.I):
        return None
    parts = []
    for sentence in _units(text):
        if re.fullmatch(r"i(?:'ve| have) reviewed (?:the latest question|the previous message)"
                        r"(?: and (?:the )?published reply)?[.!]?", sentence):
            continue
        sentence = re.sub(r"^(?:i(?:'m| am) interested in learning more about|i(?:'d| would) like to know more about|"
                          r"i want to know more about)\b", "i ask about", sentence)
        if '?' not in sentence and not re.match(r"i(?:'d| would) like to (?:ask|know|discuss)\b|i want to know\b|i ask about\b", sentence):
            return None  # A new statement preceding the question can matter.
        sentence = re.sub(r'\b(?:for more (?:information|details) about|for details on)\b', 'about', sentence)
        sentence = re.sub(r'\b(?:can|could|would) you (?:please )?', 'can you ', sentence)
        parts.append(' '.join(re.findall(r"[\w']+", sentence)))
    return tuple(parts)


def _indirect_question(text):
    request = re.match(r"\s*i(?:'d| would) like to know (?:more about|if anyone has (?:any )?information (?:about|on)) "
                       r"(.+)", text.casefold().replace('’', "'"), re.S)
    if not request:
        return None
    subject = re.sub(r'\bupcoming weather forecast\b', 'weather forecast', request[1])
    subject = re.sub(r'(?:[.!?]\s*it|\s+and how it) (?:might|may|could) (?:affect|impact|influence)\b',
                     ' may affect', subject)
    return tuple(re.findall(r"[\w']+|[<>≤≥=]", subject))


def repeats_public_text(s, aid, text, own_reports=()):
    if not text.strip():
        return False
    history = [m for m in s['messages'] if (m['round'], m['phase']) == (s['round'], s['phase'])]
    # Two farms can each independently disclose an identical measured result.
    measured = any(report.startswith('In round ') and report in text for report in own_reports)
    commitment = re.match(r"\s*i (?:will|plan to|intend to) (?:order|request|sow|plant) \d+\b", text, re.I)
    if measured or commitment:
        history = [m for m in history if m['sender'] == aid]
    if classify_public_pass(history, [{'sender': aid, 'text': text}])['repeated_agents']:
        return True
    indirect = _indirect_question(text)
    if indirect and any(indirect == _indirect_question(m['text']) for m in history):
        return True
    question = _generic_question(text)
    return bool(question) and any(question == _generic_question(m['text']) for m in reversed(s['messages'])
                                  if m['round'] >= s['round'] - 2)


def changes_contracts(s, aid, decision):
    if decision.contracts:
        from copy import deepcopy
        from .contracts import apply_contract_action
        candidate = deepcopy(s)
        for action in decision.contracts:
            apply_contract_action(candidate, aid, action)
        return candidate['contracts'] != s['contracts']
    return False


def repeats_without_progress(s, aid, decision):
    return repeats_public_text(s, aid, decision.message) and not changes_contracts(s, aid, decision)


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
    'plant care': re.compile(r'\b(plant\w*|sow\w*|dose\w*|growth|health|seed\w*|irrigat\w*|harvest\w*|experiments?|trials?)\b', re.I),
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


def exchange_references(s, aid):
    history = [m for m in s['messages'] if (m['round'], m['phase']) == (s['round'], s['phase'])]
    last_own = next((m for m in reversed(history) if m['sender'] == aid and m['text'].strip()), None)
    position = next((i for i in range(len(history)-1, -1, -1) if '?' in history[i]['text']), None)
    refs = {}
    if last_own:
        refs['your_last_statement'] = _public_message(last_own, aid)
    if position is not None:
        question = history[position]
        refs['latest_question'] = _public_message(question, aid)
        topic, doses = experience_topic(question['text'])
        addressed = {farm.lower() for farm in re.findall(r'\bfarm\s+([a-e])\b', question['text'], re.I)}
        for m in history[position+1:]:
            if m['sender'] == question['sender'] or (addressed and m['sender'].lower() not in addressed):
                continue
            reply = re.split(r'(?<=[.!])\s+', m['text'])[0]
            other_topic, other_doses = experience_topic(reply)
            if (not reply.strip() or '?' in reply or (topic and topic != other_topic)
                    or (doses and other_doses and not set(doses) & set(other_doses))):
                continue
            refs['published_reply_to_consider'] = _public_message(m, aid)
            break
    return refs


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
    references = exchange_references(s, aid)
    if references:
        # Avoid repeating the text of the latest speaker already shown in messages.
        obs['exchange'] = {k: (dict(reference='messages:1', sender=v['sender']) if latest and
                                (v['turn'], v['sender']) == (latest[0]['turn'], latest[0]['sender']) else v)
                           for k, v in references.items()}
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
