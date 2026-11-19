"""Separate measured crop reports, ordinary speech, and explicitly chosen bluffs."""
import re


REPORT_TOKEN = '[[trial]]'
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
        return ['delivery fee', 'return fee', 'cash reserve', 'harvest income']
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


_CROP = re.compile(r'\b(?:plant\w*|seed\w*|trial\w*|experiment\w*|test\b|dose\w*|water\w*|irrigat\w*|'
                   r'grow\w*|grew|health\w*|surviv\w*|harvest\w*|crop\w*|yield\w*|soil|sow\w*|sown|liters?|litres?|'
                   r'pflanz\w*|setzling\w*|versuch\w*|wass\w*|wachs\w*)\b', re.I)
_DOSE = re.compile(r'\b\d+(?:[.,]\d+)?\s*(?:l|liters?|litres?)\b', re.I)
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
                      r'(?:is|are|were|was) (?:thriving|optimal|successful|dead)|'
                      r'growth (?:was|reached)|health (?:was|reached)|had (?:good|mixed|poor) results|'
                      r'gestorben|gewachsen|überlebt|gemessen|getestet|beobachtet)\b', re.I)
_EXPERIENCE = re.compile(r"\b(?:in (?:my|our) (?:trials?|experience|tests?)|in (?:one|a previous) trial|"
                         r"my results|our results|i've had (?:some |mixed )?success|"
                         r"i(?:'ve| have) been (?:using|testing|experimenting)|"
                         r'ich habe .{0,60}(?:getestet|gemessen|beobachtet))\b', re.I)
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
        if re.match(r'^(?:did|have|would|could|can|do|how|what|which|why|when)\b', part, re.I):
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
        if _EXPERIENCE.search(part) or _PERSONAL.search(part) or _OUTCOME.search(part):
            return True
        if _READING.search(part) and not re.search(r'\b(?:target|goal|aim|expect|predict|if|until)\b', part, re.I):
            return True
    return False


def grounded_text(text, report, limit, *, bluff=False):
    """Return None if a draft needs correction. Only exact source text expands."""
    # Keep the measurement a complete statement. Embedded fragments can reverse
    # its meaning or attach invented results to the trusted record.
    marker = re.compile(re.escape(report) + '|' + re.escape(REPORT_TOKEN))
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
        if after.strip() and not (after.lstrip()[0].isupper() or after.lstrip()[0] in '"“'):
            return None
        text = text[:match.start()] + report + after
    remainder = text.replace(report, '')
    if not bluff and describes_trial(remainder):
        return None
    return text if len(text) <= limit else None
