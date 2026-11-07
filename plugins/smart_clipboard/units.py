"""Small offline conversion table, with optional Pint for installed unit names."""
import math
import re

from .maths import installed

# canonical -> (dimension, SI scale); temperatures use an affine conversion.
TABLE = {
    'mm': ('length', .001), 'cm': ('length', .01), 'm': ('length', 1),
    'km': ('length', 1000), 'in': ('length', .0254), 'ft': ('length', .3048),
    'yd': ('length', .9144), 'mi': ('length', 1609.344),
    'mg': ('mass', .000001), 'g': ('mass', .001), 'kg': ('mass', 1),
    'lb': ('mass', .45359237), 'oz': ('mass', .028349523125),
    'mL': ('volume', .001), 'L': ('volume', 1), 'gal': ('volume', 3.785411784),
    'cup': ('volume', .2365882365), 'm/s': ('speed', 1),
    'km/h': ('speed', 1 / 3.6), 'mph': ('speed', .44704),
    'B': ('data', 1), 'bit': ('data', .125), 'KB': ('data', 1e3),
    'MB': ('data', 1e6), 'GB': ('data', 1e9), 'TB': ('data', 1e12),
    'KiB': ('data', 1024), 'MiB': ('data', 1024**2), 'GiB': ('data', 1024**3),
    'C': ('temperature', 1), 'F': ('temperature', 1), 'K': ('temperature', 1),
}
ALIASES = {'mile': 'mi', 'miles': 'mi', 'meter': 'm', 'meters': 'm', 'metres': 'm',
           'kilometer': 'km', 'kilometers': 'km', 'kilometres': 'km', 'feet': 'ft',
           'foot': 'ft', 'inch': 'in', 'inches': 'in', 'yards': 'yd',
           'pound': 'lb', 'pounds': 'lb', 'lbs': 'lb', 'ounces': 'oz',
           'grams': 'g', 'kilograms': 'kg', 'liters': 'L', 'litres': 'L',
           'ml': 'mL', 'l': 'L', 'gallons': 'gal', 'cups': 'cup', 'kph': 'km/h',
           'bytes': 'B', 'byte': 'B', 'bits': 'bit', 'celsius': 'C',
           'fahrenheit': 'F', 'kelvin': 'K'}
DEFAULTS = {'length': ('mi', 'km'), 'mass': ('lb', 'kg'), 'volume': ('gal', 'L'),
            'speed': ('mph', 'km/h'), 'data': ('MiB', 'B'), 'temperature': ('F', 'C')}
PATTERN = re.compile(r'([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([A-Za-z°]+(?:/[A-Za-z]+)?)'
                     r'(?:\s+(?:to|in)\s+([A-Za-z°]+(?:/[A-Za-z]+)?))?')


class Units:
    def __init__(self):
        self.pint = None
        if installed('pint'):
            import pint
            self.pint = pint.UnitRegistry()

    def parse(self, text):
        match = PATTERN.fullmatch(text.strip())
        if not match:
            raise ValueError('Not a unit conversion.')
        value = float(match[1])
        source = ALIASES.get(match[2].lstrip('°').lower(), match[2].lstrip('°'))
        target = ALIASES.get((match[3] or '').lstrip('°').lower(), (match[3] or '').lstrip('°'))
        if source not in TABLE and (not self.pint or not target):
            raise ValueError('Unknown unit.')
        if not target:
            first, second = DEFAULTS[TABLE[source][0]]
            target = second if source == first else first
        if source in TABLE and target in TABLE:
            if TABLE[source][0] != TABLE[target][0]:
                raise ValueError('Incompatible units.')
        elif self.pint:
            self.pint.Quantity(value, source).to(target)
        else:
            raise ValueError('Unknown unit.')
        if not math.isfinite(value) or abs(value) > 1e30:
            raise ValueError('Amount too large.')
        return value, source, target

    def detect(self, text):
        try:
            self.parse(text)
            return .98
        except Exception:
            return 0.0

    def convert(self, text):
        value, source, target = self.parse(text)
        if source in {'C', 'F', 'K'}:
            kelvin = value if source == 'K' else value + 273.15 if source == 'C' else (value - 32) * 5 / 9 + 273.15
            if kelvin < 0:
                raise ValueError('Temperature below absolute zero.')
            result = kelvin if target == 'K' else kelvin - 273.15 if target == 'C' else (kelvin - 273.15) * 9 / 5 + 32
        elif self.pint:
            result = self.pint.Quantity(value, source).to(target).magnitude
        else:
            result = value * TABLE[source][1] / TABLE[target][1]
        return f'{result:.10g} {target}'
