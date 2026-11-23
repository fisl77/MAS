"""Public water accounting and syntactic bounds, without biological information."""
from fractions import Fraction

from .schema import water


WATER_BUDGET_GUIDE = """New plants and existing plants share ONE water supply. Compute each entry as
count * water_per_plant, then ADD entries from BOTH arrays. Each new planting consumes
its count times its chosen dose even when the irrigation array is empty.
Sowing and simultaneous dose comparisons are optional: postpone them when your chosen
treatments cannot fit this delivery. Changing notes or writing "0" instead of "0.0"
does not release water used by another entry. Never assume extra water can be ordered now."""


def liters_text(value):
    value = Fraction(value)
    milli = value * 1000
    if milli.denominator != 1:
        return str(value)
    sign = '-' if milli < 0 else ''
    whole, part = divmod(abs(milli.numerator), 1000)
    return sign + str(whole) + ('.' + f'{part:03d}'.rstrip('0') if part else '')


def _alternatives(parts):
    return parts[0] if len(parts) == 1 else '(' + '|'.join(parts) + ')'


def _fixed_digits_at_most(upper, first_min=0):
    digit, rest = int(upper[0]), upper[1:]
    if not rest:
        return str(digit) if digit == first_min else f'[{first_min}-{digit}]'
    parts = []
    if digit > first_min:
        prefix = str(first_min) if digit-1 == first_min else f'[{first_min}-{digit-1}]'
        parts.append(prefix + ('[0-9]' if len(rest) == 1 else f'[0-9]{{{len(rest)}}}'))
    parts.append(str(digit) + _fixed_digits_at_most(rest))
    return _alternatives(parts)


def _integers_at_most(upper):
    if upper == 0:
        return '0'
    digits = str(upper)
    parts = ['0']
    for width in range(1, len(digits)):
        parts.append('[1-9]' + ('' if width == 1 else '[0-9]' if width == 2 else f'[0-9]{{{width-1}}}'))
    parts.append(_fixed_digits_at_most(digits, 1))
    return _alternatives(parts)


def dose_pattern(delivered):
    """Canonical decimal strings up to the full delivery, with at most 3 places.

    Every plant count is positive, so an individual dose cannot exceed the whole
    delivery. All doses within that physical bound remain representable.
    """
    available_milli = max(0, int(Fraction(delivered) * 1000))
    whole, part = divmod(available_milli, 1000)
    parts = []
    if whole:
        parts.append(_integers_at_most(whole-1) + r'(\.[0-9]{1,3})?')
    if not part:
        tail = r'(\.0{1,3})?'
    else:
        fractions = [_fixed_digits_at_most(str(part // (10 ** (3-width))).zfill(width))
                     for width in (1, 2, 3)]
        tail = r'(\.' + _alternatives(fractions) + ')?'
    parts.append(str(whole) + tail)
    return '^' + _alternatives(parts) + '$'


def allocation_report(delivered, new_plants, irrigation):
    entries = []
    totals = {}
    for field, allocations in (('new_plants', new_plants), ('irrigation', irrigation)):
        subtotal = Fraction(0)
        for index, entry in enumerate(allocations):
            dose = water(entry.water_per_plant)
            used = entry.count * dose
            row = {'path': f'{field}[{index}]', 'count': entry.count,
                   'water_per_plant_liters': liters_text(dose), 'subtotal_liters': liters_text(used)}
            if field == 'irrigation':
                row['group_id'] = entry.group_id
            entries.append(row)
            subtotal += used
        totals[field] = subtotal
    used = sum(totals.values(), Fraction(0))
    available = Fraction(delivered)
    return {'available_liters': liters_text(available),
            'new_plants_liters': liters_text(totals['new_plants']),
            'existing_plants_liters': liters_text(totals['irrigation']),
            'total_liters': liters_text(used),
            'excess_liters': liters_text(max(Fraction(0), used-available)), 'entries': entries}


def exact_fit_edits(report, target, trials):
    """Calculate optional sub-liter changes using this farm's own tested doses when possible."""
    delta = Fraction(target) - water(report['total_liters'])
    if not 0 < abs(delta) < 1:
        return []
    healthy_doses = {'existing_plants': set(), 'new_plants': set()}
    for trial in trials:
        if trial['healthy_productive_plants']:
            healthy_doses[trial['kind']].add(trial['water_per_plant'])
    edits = []
    for row in report['entries']:
        old_dose = water(row['water_per_plant_liters'])
        stage = 'existing_plants' if 'group_id' in row else 'new_plants'
        known = healthy_doses[stage]
        for dose in sorted(known | {old_dose + delta, old_dose + delta / row['count']}):
            if dose < 0 or dose == old_dose or (dose * 1000).denominator != 1:
                continue
            count = delta / (dose - old_dose)
            if count.denominator == 1 and 0 < count <= row['count']:
                edits.append({'row': row['path'], 'change_count': int(count),
                              'old_L_each': liters_text(old_dose), 'new_L_each': liters_text(dose),
                              'own_healthy_growth_seen_at_new_dose': dose in known})
    return sorted(edits, key=lambda x: not x['own_healthy_growth_seen_at_new_dose'])[:3]


class WaterBudgetError(ValueError):
    def __init__(self, report):
        self.report = report
        positive = [x for x in report['entries'] if x['subtotal_liters'] != '0']
        breakdown = '; '.join(f"{x['path']}: {x['count']} * {x['water_per_plant_liters']} = {x['subtotal_liters']} L"
                              for x in positive[:8])
        message = (f"Combined farm-water total {report['total_liters']} L exceeds your delivery of "
                   f"{report['available_liters']} L by {report['excess_liters']} L. "
                   f"NEW plants consume {report['new_plants_liters']} L; EXISTING plants consume "
                   f"{report['existing_plants_liters']} L. Both arrays share ONE water supply. "
                   f"Breakdown: {breakdown}. Change actual counts/doses or remove allocations until the combined total fits.")
        if report['available_liters'] == '0':
            message += ' With zero delivery, every dose must be the string "0"; empty action arrays are allowed.'
        super().__init__(message)
