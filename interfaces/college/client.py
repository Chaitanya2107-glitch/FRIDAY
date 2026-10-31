"""Bounded loopback HTTP requests, called only from the window's worker thread."""
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener


class Error(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, base_url='http://127.0.0.1:8000', timeout=8):
        parsed = urlsplit(base_url)
        if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.username:
            raise ValueError('College Schedules connects only to the local FRIDAY backend.')
        self.base_url, self.timeout = base_url.rstrip('/'), timeout
        self.opener = build_opener(ProxyHandler({}))

    def request(self, method, path, body=None, data=None, timeout=None):
        headers = {'Accept': 'application/json'}
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        elif data is not None:
            headers['Content-Type'] = 'application/octet-stream'
        request = Request(self.base_url + '/api/v1/college/' + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                payload = json.loads(response.read())
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object')
                return payload
        except HTTPError as error:
            try:
                payload = json.loads(error.read())
            except ValueError:
                payload = {}
            message = payload.get('message') if isinstance(payload, dict) else None
            message = message or f'FRIDAY returned HTTP {error.code}.'
            if error.code == 404:
                message = 'Restart FRIDAY to load College Schedules, then Retry.'
            raise Error(message, error.code) from error
        except (URLError, TimeoutError, OSError) as error:
            raise Error('FRIDAY backend is not running or did not respond. Start FRIDAY, then Retry.') from error
        except (ValueError, TypeError) as error:
            raise Error('FRIDAY returned an unreadable response. Restart FRIDAY, then Retry.') from error

    def load(self, section):
        return self.request('GET', section)

    def save(self, section, identifier, value, revision):
        return self.request('PUT', section, {'id': identifier, 'value': value, 'revision': revision})

    def delete(self, section, identifier, revision):
        return self.request('DELETE', section, {'id': identifier, 'revision': revision})

    def move_date(self, identifier, day, start, revision):
        return self.request('POST', 'timetable/date', {'id': identifier, 'date': day, 'start': start, 'revision': revision})

    def upload(self, filename):
        file = Path(filename)
        with file.open('rb') as source:
            data = source.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise Error('Choose a file no larger than 10 MB.')
        return self.request('POST', 'uploads?' + urlencode({'filename': file.name}), data=data, timeout=30)

    def vision(self):
        return self.request('GET', 'uploads/vision')

    def extract(self, token, consent, section=''):
        return self.request('POST', 'uploads/' + token + '/extract', {'consent': consent, 'section': section}, timeout=120)

    def preview(self, token, rows, revision, mode='merge'):
        return self.request('POST', 'uploads/' + token + '/preview', {'rows': rows, 'revision': revision, 'mode': mode})

    def confirm(self, token, rows, revision, mode, review):
        return self.request('POST', 'uploads/' + token + '/confirm',
                            {'rows': rows, 'revision': revision, 'mode': mode, 'review': review})

    def discard(self, token):
        return self.request('DELETE', 'uploads/' + token + '/preview')

    def delete_upload(self, identifier, revision):
        return self.request('DELETE', 'uploads/' + identifier, {'id': identifier, 'revision': revision})
