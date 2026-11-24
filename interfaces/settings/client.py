"""Use the backend's configuration owners instead of writing files from Tk."""
from interfaces.tray import backend

Error = backend.BackendError


class Client:
    def _request(self, method, path, **kwargs):
        try:
            return backend._request(method, '/api/v1' + path, timeout=8, trust_env=False, **kwargs)
        except Error as error:
            if error.status == 404 and path.startswith('/customization/'):
                raise Error('Restart FRIDAY to load the new editor, then choose Reload.', 404) from error
            raise

    def load(self, section):
        return self._request('GET', '/customization/' + section)

    def model_mode(self, mode=None):
        path = '/customization/model'
        if mode is None:
            return self._request('GET', path)
        return self._request('PUT', path, json={'mode': mode})

    def status_report_time(self, time=None):
        path = '/customization/status-report'
        if time is None:
            return self._request('GET', path)
        return self._request('PUT', path, json={'time': time})

    def save(self, section, original, name, value, revision):
        return self._request('PUT', '/customization/' + section,
            json={'original': original, 'name': name, 'value': value, 'revision': revision})

    def delete(self, section, name, revision):
        return self._request('DELETE', '/customization/' + section, json={'name': name, 'revision': revision})
