"""Separate measured crop reports, ordinary speech, and explicitly chosen bluffs."""
import re
from .knowledge import return_cost
from .learning import coins
from .water_budget import liters_text


REPORT_TOKEN = '[[trial]]'
FEE_TOKEN = '[[fees]]'
WATER_TOKEN = '[[water]]'
PROFILE_NOTES = {
    'short_term': ('cash_plan', 'Use your balance, fees or expected receipts. What will you pay for or skip today, and why?'),
    'reciprocal': ('partner_plan', 'Use a specific open question, public claim or signed commitment. '
                   'What will you ask, offer or verify before relying on that farm? '
                   'For an independent check, say how you will do it yourself.'),
    'cunning_experimenter': ('experiment_plan', 'Which alternatives will you compare? Say what would change your '
                             'next move or what finding you would withhold.'),
}
REFLECTION_NOTES = {
    'short_term': 'What did you pay or earn? Which cost is still uncertain enough to change your next order?',
    'reciprocal': 'Which promise did you see kept or broken? If evidence is missing, what would establish trust? '
                  'Without contact, which advice or assumption could you check independently?',
    'cunning_experimenter': 'What did the comparison settle, what is still untested, and which result is worth concealing?',
}


def planning_choices(s, aid):
    profile = s['agents'][aid]['profile']
    if profile == 'short_term':
        cfg = s['config']
        fees = []
        if cfg.get('delivery_fee_coins', 20):
            fees.append('delivery fee')
        if return_cost(cfg):
            fees.append('return fee')
        return [*fees, 'cash reserve', 'harvest income']
    if profile == 'reciprocal':
        peers = s['public_active_agents'] if s['config']['communication'] else []
        return [*(f'Farm {p}' for p in peers if p != aid), 'independent check']
    return ['survival', 'growth', 'health', 'disclosure', 'defer experiment']


def trial_report(agent, observation):
    """Build the only shareable measurement from an executed, owner-scoped record."""
    own = observation['own_farm']
    rows = [*observation['recalled_experiences'], *own['recent_plant_results']]
    row = next((r for r in rows if r.get('kind') == 'plant' and
                all(k in r for k in ('round', 'count', 'water_per_plant', 'growth', 'health', 'outcome'))), None)
    if row is None:
        if agent.get('cultivation_trials'):
            return 'I have no matching plant result available for this reply.'
        return 'I have no measured plant results yet.'
    count = row['count']
    plants = 'seedling' if row.get('stage') == 'sown' else 'plant'
    growth, health = row['growth'], row['health']
    return (f"In round {row['round']} my group of {count} {plants}{'' if count == 1 else 's'} "
            f"received {row['water_per_plant']} L each. Growth {growth[0]} to {growth[1]}, "
            f"health {health[0]} to {health[1]}. Outcome: {row['outcome']}.")


def water_report(s, aid):
    if not s['history']:
        return 'I have no settled water account yet.'
    last = s['history'][-1]
    row = last.get('agents', {}).get(aid, {})
    if not {'delivered', 'used', 'returned', 'delivery_fee', 'return_fee'} <= row.keys():
        return 'I have no complete water account available for that round.'
    return (f"In round {last['round']} I received {liters_text(row['delivered'])} L, used "
            f"{liters_text(row['used'])} L and returned {liters_text(row['returned'])} L. "
            f"I paid {coins(row['delivery_fee'])} coins for delivery and {coins(row['return_fee'])} coins for returns.")


_CROP = re.compile(r'\b(?:plant\w*|seed\w*|trial\w*|experiment\w*|test\b|dose\w*|water\w*|irrigat\w*|'
                   r'grow\w*|grew|health\w*|surviv\w*|harvest\w*|crop\w*|yield\w*|soil|sow\w*|sown|liters?|litres?|'
                   r'pflanz\w*|setzling\w*|versuch\w*|wass\w*|wachs\w*)\b', re.I)
_DOSE = re.compile(r'\b\d+(?:[.,]\d+)?\s*(?:l|liters?|litres?)\b', re.I)
_OWN_WATER_PAST = re.compile(r"\b(?:i|we)(?:'ve| have| had| actually| also| already| just| previously)*\s+"
                             r"(?:received|ordered|requested|returned|used|consumed|withdrew)\b|"
                             r"\b(?:my|our) (?:last |previous )?(?:delivery|order|water use|water usage|return) "
                             r"(?:was|totalled|totaled|amounted to)\b", re.I)
_ON_HAND = re.compile(r"\b(?:i|we) (?:currently |still |now )?(?:have|hold) (?:only |about )?"
                      r"(\d+(?:[.,]\d+)?)\s*(?:l|liters?|litres?)\b(?: of water)?"
                      r"(?:\s+(?:available|left|remaining|in reserve|on hand)\b|\s*[.!?,;]|$)", re.I)
_READING = re.compile(r'\b(?:growth|health|survival|yield)\s*(?:of|was|at|=|:)?\s*\d|'
                      r'\d\s*%\s*(?:growth|health|survival|yield)\b', re.I)
_PERSONAL = re.compile(r"\b(?:i|we)(?:'ve|'d| have| had| also| already| actually| previously| personally|"
                       r" successfully| been| never| once| recently| first| only| still| am| are| was| were)*\s+"
                       r"(?:saw|seen|found|noticed|observed|measured|tested|tried|experimented|harvested|sowed|"
                       r"sown|planted|watered|irrigated|grew|achieved|recorded|obtained|used|ran|conducted|"
                       r"had (?:some |mixed |great |limited |good )?(?:success|results)|"
                       r"been (?:using|testing|experimenting)|recall|remember)\b", re.I)
_OUTCOME = re.compile(r'\b(?:died|grew|survived|thrived|wilted|failed|worked|yielded|showed|resulted|'
                      r'led to|increased|decreased|improved|produced|were planted|were watered|turned out|'
                      r'(?:is|are|were|was) (?:thriving|optimal|effective|successful|dead)|'
                      r'growth (?:was|reached)|health (?:was|reached)|had (?:good|mixed|poor) results|'
                      r'gestorben|gewachsen|überlebt|gemessen|getestet|beobachtet)\b', re.I)
_EXPERIENCE = re.compile(r"\b(?:in (?:my|our) (?:trials?|experience|tests?)|in (?:one|a previous) trial|"
                         r"my results|our results|i've had (?:some |mixed )?success|"
                         r"i(?:'ve| have) been (?:using|testing|experimenting)|"
                         r'ich habe .{0,60}(?:getestet|gemessen|beobachtet))\b', re.I)
_FINDING = re.compile(r'\b(?:comparison|experiment|trial|test|results?|data|evidence)\b.{0,65}?\b'
                      r'(?:settled|prov(?:ed|es)|confirm(?:ed|s)?|demonstrat(?:ed|es)|'
                      r'established|indicat(?:ed|es)|show(?:ed|s)?|reveal(?:ed|s)?)\b|'
                      r'\b(?:and|also) (?:found|measured|observed|tested|concluded) (?:that|how)\b', re.I)
_SOURCE = re.compile(r"^(?:according to (?:farm )?[a-e]\b|(?:farm )?[a-e] (?:said|claims?|reports?|"
                     r"reported|says|told|behauptet|sagt)|i heard (?:farm )?[a-e]\b)", re.I)
_UNCERTAIN = re.compile(r"^(?:if |what if |perhaps |maybe |suppose |hypothesis\b|i (?:suspect|hypothesize|"
                        r"wonder whether|wonder if)|i (?:have not|haven't|never) (?:yet )?(?:tested|observed|tried)|"
                        r"we (?:have not|haven't) (?:yet )?(?:tested|observed|tried)|ich vermute|falls )", re.I)


def describes_trial(text):
    """Detect narrative past experiments, including a claim preceding a question."""
    text = text.replace('’', "'")
    for part in re.split(r'(?<!\d)[.!?;]\s*|[.!?;](?!\d)\s*|\n| — |,\s*(?=(?:I|we|my|our)\b)|'
                         r'\b(?:but|however|and|whereas)\b[\s,]+(?=(?:I|we|my|our)\b)', text, flags=re.I):
        part = part.strip(' ,"“”')
        if not part or _SOURCE.search(part) or _UNCERTAIN.search(part):
            continue
        if re.match(r'^(?:did|does|do|has|have|would|will|could|can|is|are|was|were|should|how|what|which|why|when)\b', part, re.I):
            # A question can ask a peer about their measurements.
            if not re.search(r'\b(?:i|we|my|our)\b', part, re.I):
                continue
            if re.match(r'^(?:why|how|when) did\b', part, re.I) and re.search(
                    r'\b(?:my|our) .{0,60}\b(?:die|grow|thrive|wilt|fail|survive)\b', part, re.I):
                return True
            if not _PERSONAL.search(part):
                continue
        if not (_CROP.search(part) or _DOSE.search(part)):
            continue
        if _EXPERIENCE.search(part) or _PERSONAL.search(part) or _OUTCOME.search(part) or _FINDING.search(part):
            return True
        if _READING.search(part) and not re.search(r'\b(?:target|goal|aim|expect|predict|if|until)\b', part, re.I):
            return True
    return False


def describes_water_receipt(text):
    for sentence in re.split(r'(?<=[.!?;])\s+|\n+', text.replace('’', "'")):
        if not _DOSE.search(sentence) or not _OWN_WATER_PAST.search(sentence):
            continue
        if _SOURCE.search(sentence.strip()) or _UNCERTAIN.search(sentence.strip()):
            continue
        if re.match(r'^\s*(?:did|have|can|could|would)\b', sentence, re.I) and sentence.rstrip().endswith('?'):
            continue
        return True
    return False


def claims_unspent_water(text):
    # Public phase 2 precedes delivery. Public phase 7 follows automatic return of every unused liter.
    for clause in re.split(r'(?<=[.!?;])\s+|\n+', text):
        if re.search(r'\b(?:if|unless|suppose|might|would)\b', clause, re.I) or clause.rstrip().endswith('?'):
            continue
        if any(float(amount.replace(',', '.')) > 0 for amount in _ON_HAND.findall(clause)):
            return True
    return False


def expand_statement(text, token, report):
    # Keep the measurement a complete statement. Embedded fragments can reverse
    # its meaning or attach invented results to the trusted record.
    marker = re.compile(re.escape(report) + '|' + re.escape(token))
    matches = list(marker.finditer(text))
    if len(matches) > 1:
        return None
    if matches:
        match = matches[0]
        before, after = text[:match.start()].rstrip(), text[match.end():]
        if before and before[-1] not in '.!?;—':
            return None
        if after and not (after[0].isspace() or after[0] in '.!?;'):
            return None
        # An optional period after the placeholder already occurs in the report.
        if after.startswith('.'):
            after = after[1:]
        tail = after.lstrip()
        if tail and not (tail[0].isupper() or tail[0] in '"“' or tail.startswith((FEE_TOKEN, REPORT_TOKEN, WATER_TOKEN))):
            return None
        return text[:match.start()] + report + after
    return text


def grounded_text(text, report, limit, *, bluff=False, tariffs='', receipt=''):
    """Only complete source statements expand. Check the author's surrounding words separately."""
    sources = [(REPORT_TOKEN, report), (FEE_TOKEN, tariffs), (WATER_TOKEN, receipt)]
    for token, record in sources:
        if record:
            text = expand_statement(text, token, record)
            if text is None:
                return None
    remainder = text
    for _, record in sources:
        if record:
            remainder = remainder.replace(record, '')
    if receipt and claims_unspent_water(remainder):
        return None
    if not bluff and (describes_trial(remainder) or (receipt and describes_water_receipt(remainder))):
        return None
    return text if len(text) <= limit else None
