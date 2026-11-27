"""Lobby Advanced Rules controls for boundary mutators (#97, mutators master #46 item 10).

The lobby sends a boundary override with the ``rules`` action (``boundary={...}``, or ``None`` to
return to the map's defaults). The host merges it over the map's ``mutators.boundary`` and fixes the
result at match start (T3BackEndServer#115). Settings and per-game defaults:
T3BackEndServer docs/BOUNDARY_LAYER.md.
"""

import tkinter as tk
from tkinter import ttk

try:
    from community_maps import validated_boundary
except ImportError:  # Starter updates do not replace community_maps.py; the host validates instead.
    def validated_boundary(value):
        if not isinstance(value, dict) or not value:
            raise ValueError('Invalid boundary settings.')
        return dict(value)

MODES = (('ignore', 'Ignore the boundary'), ('block', 'Block players and flag'),
         ('flag_only', 'Flag-only'), ('damage', 'Damage after grace time'))
MODE_LABEL = dict(MODES)
ON_OFF = ((True, 'On'), (False, 'Off'))

# key, label, choices as (value, text). Numbers offer common values; the field also accepts typing.
FIELDS = (
    ('mode', 'Boundary mode', MODES),
    ('warn_players', 'Warn players on crossing', ON_OFF),
    ('flag_rule', 'Flag outside', (('drop', 'Drop at the line'), ('return_after', 'Return home after a delay'),
                                   ('none', 'Nothing'))),
    ('flag_return_delay_s', 'Flag return delay (s)', tuple((n, str(n)) for n in (1, 3, 5, 10, 15, 30, 45, 60))),
    ('flag_pickup_outside', 'Flag pickup from outside', ON_OFF),
    ('grace_s', 'Grace time before damage (s)', tuple((n, str(n)) for n in (0, 2, 4, 5, 10, 15, 30))),
    ('alert_interval_s', 'Alert interval (s)', tuple((n, str(n)) for n in (0.5, 1, 1.5, 2, 3))),
    ('damage_per_s', 'Damage per second (share of Light health)',
     tuple((n, f'{n:g}') for n in (0.025, 0.05, 0.075, 0.1, 0.25, 1))),
    ('vehicles', 'Vehicles outside', (('ignore', 'Ignore'), ('destroy', 'Destroy'))),
    ('apply_flight_ceiling', 'Apply flight ceiling', ON_OFF),
    ('apply_kill_floor', 'Apply kill floor', ON_OFF),
)
NUMBERS = {'flag_return_delay_s': int, 'grace_s': float, 'alert_interval_s': float, 'damage_per_s': float}


def text_for(key, value):
    choices = dict(next(field[2] for field in FIELDS if field[0] == key))
    return choices.get(value, f'{value:g}' if isinstance(value, float) else str(value))


def summary(settings):
    """Short description of boundary settings, e.g. 'Flag-only · warn · flag home after 5 s'."""
    if not settings:
        return "the map's own rules"
    parts = [MODE_LABEL.get(settings.get('mode'), 'Map mode')]
    if settings.get('warn_players'):
        parts.append('warn')
    rule = settings.get('flag_rule')
    if rule == 'return_after':
        parts.append(f"flag home after {settings.get('flag_return_delay_s', '?')} s")
    elif rule == 'drop':
        parts.append('flag drops at the line')
    if settings.get('mode') == 'damage':
        parts.append(f"{settings.get('grace_s', 0):g} s grace")
    if settings.get('vehicles') == 'destroy':
        parts.append('vehicles destroyed')
    return ' · '.join(parts)


def effective(default, override):
    merged = {**(default or {}), **(override or {})}
    return merged or None


def mode_values(default):
    """Combobox values: the map default first, then each mode."""
    return (f'Map default ({summary(default)})', *(label for _, label in MODES))


def mode_selection(default, override):
    mode = (override or {}).get('mode')
    return mode_values(default)[0] if mode is None else MODE_LABEL[mode]


def with_mode(override, index):
    """New override after choosing combobox entry ``index`` (0 is the map default mode)."""
    result = dict(override or {})
    if index == 0:
        result.pop('mode', None)
    else:
        result['mode'] = MODES[index - 1][0]
    return result or None


def parse_field(key, text, default_label):
    """Turn one dialog field into a value, or None for 'Map default'. Raises ValueError."""
    if text == default_label or not text.strip():
        return None
    choices = {label: value for value, label in next(field[2] for field in FIELDS if field[0] == key)}
    if text in choices:
        return choices[text]
    if key in NUMBERS:
        number = float(text)
        return int(number) if NUMBERS[key] is int and number.is_integer() else number
    raise ValueError(f'Choose a value for {key.replace("_", " ")}.')


def override_from_fields(values, default):
    """Build and validate the override from {key: text}. Returns a dict, or None when all are defaults."""
    override = {}
    for key, label, _ in FIELDS:
        value = parse_field(key, values.get(key, ''), default_label(key, default))
        if value is not None:
            override[key] = value
    if not override:
        return None
    merged = effective(default, override)
    validated_boundary(merged)  # The whole result must be valid, e.g. return_after needs a delay.
    return validated_boundary(override)


def default_label(key, default):
    if default and key in default:
        return f'Map default ({text_for(key, default[key])})'
    return 'Map default'


class BoundaryDialog:
    """Modal dialog with every boundary setting; each can stay on the map default."""

    def __init__(self, parent, default, override, apply):
        self.default, self.apply = default or {}, apply
        self.window = window = tk.Toplevel(parent)
        window.title('Boundary settings')
        window.transient(parent.winfo_toplevel())
        window.resizable(False, False)
        body = ttk.Frame(window, padding=14)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=f"Map default: {summary(default)}", wraplength=420).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        self.fields = {}
        for row, (key, label, choices) in enumerate(FIELDS, 1):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=2)
            values = (default_label(key, self.default), *(text for _, text in choices))
            box = ttk.Combobox(body, values=values, width=30, state='normal' if key in NUMBERS else 'readonly')
            current = (override or {}).get(key)
            box.set(values[0] if current is None else text_for(key, current))
            box.grid(row=row, column=1, sticky='w', pady=2)
            self.fields[key] = box
        self.error = tk.StringVar(window)
        ttk.Label(body, textvariable=self.error, foreground='#c0392b', wraplength=420).grid(
            row=len(FIELDS) + 1, column=0, columnspan=2, sticky='w', pady=(6, 0))
        actions = ttk.Frame(body)
        actions.grid(row=len(FIELDS) + 2, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        ttk.Button(actions, text='Reset to map default', command=self.reset).pack(side='left')
        ttk.Button(actions, text='Apply', command=self.submit).pack(side='right')
        ttk.Button(actions, text='Cancel', command=window.destroy).pack(side='right', padx=6)

    def values(self):
        return {key: box.get() for key, box in self.fields.items()}

    def reset(self):
        for key, box in self.fields.items():
            box.set(default_label(key, self.default))

    def submit(self):
        try:
            override = override_from_fields(self.values(), self.default)
        except ValueError as error:
            self.error.set(str(error))
            return
        self.window.destroy()
        self.apply(override)
