"""Unexecuted farm drafts whose next model choice is bounded by remaining water."""
from fractions import Fraction

from .schema import Decision, water
from .water_budget import dose_pattern, liters_text


def _object(properties, required):
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': required}


def _cancel_schema():
    return _object({'cancel': {'type': 'boolean', 'enum': [True]}}, ['cancel'])


def _records(rows):
    if len(rows) <= 20:
        return rows
    columns = list(rows[0])
    return {'columns': columns, 'rows': [[r[k] for k in columns] for r in rows]}


class FarmBudgetDraft:
    """Keep/revise/omit choices come from the model; this class only does accounting."""
    def __init__(self, state, aid, proposed):
        self.available = Fraction(state['agents'][aid]['delivered'])
        self.remaining = self.available
        self.query = state['agents'][aid]['recall_query']
        self.group_counts = {g['id']: g['count'] for g in state['agents'][aid]['plants']}
        self.pending = {}
        for prefix, category, allocations in (('n', 'new_plants', proposed.new_plants),
                                               ('i', 'irrigation', proposed.irrigation)):
            for i, allocation in enumerate(allocations):
                self.pending[f'{prefix}{i}'] = {'allocation_id': f'{prefix}{i}', 'category': category,
                                               'group_id': getattr(allocation, 'group_id', None),
                                               'count': allocation.count, 'water_per_plant': allocation.water_per_plant}
        self.selected = []

    def max_count(self, row):
        return min(row['count'], self.group_counts.get(row['group_id'], 0)) if row['category']=='irrigation' else row['count']

    def keepable(self):
        return [key for key, row in self.pending.items() if row['count'] <= self.max_count(row)
                and row['count'] * water(row['water_per_plant']) <= self.remaining]

    def selection_schema(self):
        variants = []
        if self.keepable():
            variants.append(_object({'keep_id': {'type': 'string', 'enum': self.keepable()}}, ['keep_id']))
        revisable = [key for key, row in self.pending.items() if self.max_count(row)]
        if revisable:
            variants.append(_object({'revise_id': {'type': 'string', 'enum': revisable}}, ['revise_id']))
        variants.append(_object({'finish': {'type': 'boolean', 'enum': [True]}}, ['finish']))
        return {'oneOf': variants}

    def read_selection(self, value):
        if type(value) is not dict:
            raise ValueError('Return a selection object.')
        if set(value)=={'finish'} and value['finish'] is True:
            return value
        if set(value)=={'keep_id'} and type(value['keep_id']) is str and value['keep_id'] in self.keepable():
            return value
        if (set(value)=={'revise_id'} and type(value['revise_id']) is str and value['revise_id'] in self.pending
                and self.max_count(self.pending[value['revise_id']])):
            return value
        raise ValueError(f"Choose keep_id from {self.keepable()}, revise_id from remaining entries, or finish=true. "
                         f"Only {liters_text(self.remaining)} L remain. No choice was applied.")

    def count_schema(self, key):
        return {'oneOf': [_object({'count': {'type': 'integer', 'minimum': 1,
                                            'maximum': self.max_count(self.pending[key])}}, ['count']),
                          _cancel_schema()]}

    def read_count(self, key, value):
        if type(value) is dict and set(value)=={'cancel'} and value['cancel'] is True:
            return value
        if (type(value) is dict and set(value)=={'count'} and type(value['count']) is int
                and 1 <= value['count'] <= self.max_count(self.pending[key])):
            return value
        raise ValueError('Choose an available positive count, or cancel=true.')

    def dose_schema(self, count):
        return {'oneOf': [_object({'water_per_plant': {'type': 'string',
                                  'pattern': dose_pattern(self.remaining/count)}}, ['water_per_plant']),
                          _cancel_schema()]}

    def read_dose(self, count, value):
        if type(value) is dict and set(value)=={'cancel'} and value['cancel'] is True:
            return value
        if (type(value) is dict and set(value)=={'water_per_plant'} and type(value['water_per_plant']) is str
                and count * water(value['water_per_plant']) <= self.remaining):
            return value
        raise ValueError(f'This count must fit the remaining {liters_text(self.remaining)} L, or choose cancel=true.')

    def commit(self, key, count, dose):
        row = self.pending[key]
        if type(count) is not int or not 1 <= count <= self.max_count(row):
            raise ValueError('Invalid allocation count; draft unchanged.')
        spent = count * water(dose)
        if spent > self.remaining:
            raise ValueError('Allocation exceeds remaining draft budget; draft unchanged.')
        self.selected.append({**row, 'count': count, 'water_per_plant': dose})
        self.remaining -= spent
        if row['category']=='irrigation':
            self.group_counts[row['group_id']] -= count
        del self.pending[key]

    def cancel(self, key):
        del self.pending[key]

    def omit_implicit_zero_irrigation(self):
        """With no water left, unselected existing plants get zero by normal rules."""
        if self.remaining == 0:
            for key in list(self.pending):
                if self.pending[key]['category']=='irrigation':
                    del self.pending[key]

    def details(self, selected_key=None, selected_count=None):
        rows = [{**row, 'subtotal_liters': liters_text(row['count'] * water(row['water_per_plant'])),
                 'max_selectable_count': self.max_count(row),
                 'keep_affordable': key in self.keepable()} for key, row in self.pending.items()]
        return {'available_liters': liters_text(self.available), 'remaining_liters': liters_text(self.remaining),
                'used_liters': liters_text(self.available-self.remaining), 'proposed_allocations': _records(rows),
                'selected_allocations': _records(self.selected), 'current_allocation_id': selected_key,
                'current_count': selected_count,
                'notice': 'Private unexecuted draft. Unselected new plants are not sown; unselected existing plants receive zero. '
                          'Finish returns unused water under normal rules. No physical actions occur until the full plan is accepted.'}

    def decision(self):
        new, existing = [], []
        for row in self.selected:
            entry = {'count': row['count'], 'water_per_plant': row['water_per_plant']}
            if row['category']=='irrigation':
                existing.append({**entry, 'group_id': row['group_id']})
            else:
                new.append(entry)
        # A rejected plan's private claims were never accepted either. Keep current
        # notes until a later normal decision updates them from executed outcomes.
        return Decision(new_plants=new, irrigation=existing, recall_query=self.query)
