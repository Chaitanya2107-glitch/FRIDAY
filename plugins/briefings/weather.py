"""The sole optional network boundary; disabled unless coordinates are opted in."""
import math


def fetch(settings):
    if settings.get('briefings.weather', False) is not True:
        return ''
    latitude, longitude = settings.get('briefings.latitude'), settings.get('briefings.longitude')
    if (type(latitude) not in {int, float} or type(longitude) not in {int, float}
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        return ''
    try:
        import httpx
        # https://open-meteo.com/en/docs — no geocoding, redirects, key or provider fallback.
        with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client:
            response = client.get('https://api.open-meteo.com/v1/forecast', params={
                'latitude': latitude, 'longitude': longitude, 'current': 'temperature_2m,weather_code', 'forecast_days': 1})
            response.raise_for_status()
            if len(response.content) > 131072:
                return ''
            current = response.json()['current']
            temperature = current['temperature_2m']
            if type(temperature) not in {float, int} or not math.isfinite(temperature):
                return ''
            return f'Outside: {round(temperature)}°C.'
    except Exception:
        return ''  # Optional weather must fail silently, including malformed responses.
