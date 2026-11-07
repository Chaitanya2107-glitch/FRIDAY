"""Rule-based offline detectors and transformations; no automatic external I/O."""
import colorsys
from datetime import datetime, timezone
import json
import math
import os
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
import webbrowser

from .maths import MathActions, installed, math_score
from .registry import Action
from .units import Units
from .windows import local_path


def url(text):
    if len(text) > 8192 or re.search(r'[\s\x00-\x1f\x7f]', text):
        return None
    try:
        value = urlsplit(text)
        if value.scheme not in {'http', 'https'} or not value.hostname or value.username or value.password:
            return None
        value.port  # Reject invalid/out-of-range ports.
        return value
    except ValueError:
        return None


def clean_url(text):
    value = url(text)
    if value is None:
        raise ValueError('Not a web link.')
    query = [(k, v) for k, v in parse_qsl(value.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid', 'si', 'dclid', 'msclkid'}]
    return urlunsplit(value._replace(query=urlencode(query)))


def color(text):
    value = text.strip()
    if re.fullmatch(r'#[a-fA-F0-9]{3,4}|#[a-fA-F0-9]{6}(?:[a-fA-F0-9]{2})?', value):
        value = value[1:]
        if len(value) in {3, 4}:
            value = ''.join(c * 2 for c in value)
        channels = tuple(int(value[i:i + 2], 16) for i in range(0, len(value), 2))
        rgb, alpha = channels[:3], channels[3] / 255 if len(channels) == 4 else 1
    else:
        match = re.fullmatch(r'(rgb|hsl)\(\s*([\d.]+)\s*,\s*([\d.]+)(%?)\s*,\s*([\d.]+)(%?)\s*\)', value, re.I)
        if not match:
            raise ValueError('Not a color.')
        a, b, c = map(float, (match[2], match[3], match[5]))
        if match[1].lower() == 'rgb':
            if match[4] or match[6] or any(v < 0 or v > 255 or not v.is_integer() for v in (a, b, c)):
                raise ValueError('Invalid RGB color.')
            rgb = tuple(map(int, (a, b, c)))
        else:
            if not (0 <= a <= 360 and 0 <= b <= 100 and 0 <= c <= 100 and match[4] and match[6]):
                raise ValueError('Invalid HSL color.')
            rgb = tuple(round(v * 255) for v in colorsys.hls_to_rgb(a / 360, c / 100, b / 100))
        alpha = 1
    h, light, saturation = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    hexadecimal = '#' + ''.join(f'{v:02X}' for v in rgb)
    if alpha != 1:
        hexadecimal += f'{round(alpha * 255):02X}'
    return f'{hexadecimal} · rgb({rgb[0]}, {rgb[1]}, {rgb[2]}) · hsl({h * 360:.0f}, {saturation * 100:.0f}%, {light * 100:.0f}%)'


def json_value(text):
    # Scalar strings/numbers/booleans are deliberately too ambiguous to classify.
    if not text.lstrip().startswith(('{', '[')) or len(text) > 65536:
        raise ValueError('Not a JSON object or array.')
    def reject(value):
        raise ValueError('Nonfinite JSON value.')
    value = json.loads(text, parse_constant=reject)
    return value


def format_json(text):
    return json.dumps(json_value(text), indent=2, ensure_ascii=False, allow_nan=False)


def timestamp(text):
    if re.fullmatch(r'\d{10}|\d{13}', text):
        return datetime.fromtimestamp(int(text) / (1000 if len(text) == 13 else 1), timezone.utc)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[Zz]|[+-]\d{2}:\d{2})?)?', text):
        raise ValueError('Not an ISO date.')
    value = datetime.fromisoformat(text.upper().replace('Z', '+00:00'))
    # ISO input without an offset is interpreted in the PC's local timezone.
    return value.astimezone() if value.tzinfo is None else value


def time_result(text):
    value = timestamp(text)
    return f"Local: {value.astimezone():%Y-%m-%d %H:%M:%S %Z} · UTC: {value.astimezone(timezone.utc):%Y-%m-%d %H:%M:%S}"


def counts(text):
    return f'{len(text.split())} words · {len(text)} characters'


def valid(function, text):
    try:
        return function(text) is not None
    except Exception:
        return False


class Dictionary:
    def __init__(self):
        self.wordnet = None
        if installed('nltk'):
            try:
                from nltk.corpus import wordnet
                wordnet.ensure_loaded()  # Local corpus only; never nltk.download().
                self.wordnet = wordnet
            except Exception:
                pass

    def define(self, text):
        senses = self.wordnet.synsets(text.lower().replace(' ', '_')) if self.wordnet else []
        return senses[0].definition() if senses else 'No entry in the installed offline dictionary.'


def open_url(text):
    if not url(text):
        raise ValueError('Not a web link.')
    if not webbrowser.open(text):
        raise ValueError('Browser unavailable.')


def search_word(text):
    if not re.fullmatch(r"[A-Za-z][A-Za-z'-]{0,29}(?: [A-Za-z][A-Za-z'-]{0,29})?", text):
        raise ValueError('Not a word.')
    if not webbrowser.open('https://www.google.com/search?q=' + quote('define ' + text)):
        raise ValueError('Browser unavailable.')


def open_path(text, containing=False):
    path = local_path(text)
    if path is None:
        raise ValueError('Local path unavailable.')
    os.startfile(str(path.parent if containing else path))


def populate(registry, api):
    maths, units, dictionary = MathActions(api), Units(), Dictionary()
    registry.register('math', lambda t: math_score(t, maths.symbolic()),
                      [Action('evaluate', 'Evaluate', maths.run), Action('solve', 'Solve', maths.run)], maths.preview)
    registry.register('units', units.detect, [Action('convert', 'Convert', units.convert)], units.convert)
    registry.register('url', lambda t: .99 if url(t) else 0,
                      [Action('open', 'Open', open_url), Action('clean', 'Copy clean link', clean_url)],
                      lambda t: 'Web link · Open or copy without tracking parameters.')
    registry.register('color', lambda t: .99 if valid(color, t) else 0,
                      [Action('color', 'Show color', color)], color)
    registry.register('json', lambda t: .98 if valid(json_value, t) else 0,
                      [Action('format', 'Format', format_json)], lambda t: 'Valid JSON · Format and copy back.')
    registry.register('timestamp', lambda t: .99 if valid(timestamp, t) else 0,
                      [Action('time', 'Show times', time_result)], time_result)
    registry.register('path', lambda t: .99 if local_path(t) else 0,
                      [Action('open', 'Open', open_path),
                       Action('folder', 'Open containing folder', lambda t: open_path(t, True))],
                      lambda t: 'Existing local path · Open or show its containing folder.')
    registry.register('word', lambda t: .82 if re.fullmatch(r"[A-Za-z][A-Za-z'-]{0,29}(?: [A-Za-z][A-Za-z'-]{0,29})?", t) else 0,
                      [Action('define', 'Define', dictionary.define)] if dictionary.wordnet else
                      [Action('search', 'Search online', search_word)],
                      lambda t: 'Offline definition available.' if dictionary.wordnet else 'No offline dictionary · Search online on request.')
    if installed('periodictable'):
        import periodictable
        def formula(t):
            if len(t) > 80 or not re.fullmatch(r'(?:[A-Z][a-z]?\d{0,3}){2,20}', t):
                raise ValueError('Not a chemical formula.')
            mass = periodictable.formula(t).mass
            if not math.isfinite(mass) or mass <= 0:
                raise ValueError('Invalid molar mass.')
            return f'{mass:.6g} g/mol'
        registry.register('chem_formula', lambda t: .96 if valid(formula, t) else 0,
                          [Action('mass', 'Molar mass', formula)], formula)
    registry.register('long_text', lambda t: .81 if len(t) > 300 else 0, [], counts)
