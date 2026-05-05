import os
import json
import time
import hashlib
import urllib.request
from dotenv import load_dotenv

import advisor as rule_advisor

load_dotenv()

_cache = {}
_TTL = 600

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")

PROMPT = """You are a greenhouse advisor. Given a sensor reading, local weather forecast, and the crop being grown, give one short actionable recommendation.

Sensor reading:
- Soil moisture: {soil_moisture}%
- Soil temperature: {soil_temp}°C
- Air temperature: {air_temp}°C
- Air humidity: {air_humidity}%

Crop: {crop}

Forecast next 24h:
{forecast_summary}

Respond with ONLY a JSON object with these exact fields:
- level: one of "ok", "info", "warn", "critical"
- message: a single sentence under 110 characters with the action to take

No markdown, no extra text, just the JSON object."""

def _key_for(reading, crop):
    return hashlib.sha1(json.dumps([reading, crop], sort_keys=True).encode()).hexdigest()[:10]

def _summarize_forecast(forecast):
    if not forecast:
        return "No forecast data available."
    parts = forecast.get('periods', [])[:3]
    if not parts:
        return "No forecast data available."
    lines = []
    for p in parts:
        pop = (p.get('probabilityOfPrecipitation') or {}).get('value')
        pop_s = f", precip {pop}%" if pop is not None else ""
        lines.append(f"- {p.get('name','?')}: {p.get('temperature')}°{p.get('temperatureUnit','F')}{pop_s} — {p.get('shortForecast','')}")
    return "\n".join(lines)

def _call_llm(prompt):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.4,
        "max_tokens": 200
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def recommend(reading, forecast, crop='arugula'):
    cache_key = _key_for(reading, crop)
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached['t'] < _TTL:
        return cached['data']

    try:
        prompt = PROMPT.format(
            soil_moisture=reading.get('soil_moisture'),
            soil_temp=reading.get('soil_temp'),
            air_temp=reading.get('air_temp'),
            air_humidity=reading.get('air_humidity'),
            crop=crop,
            forecast_summary=_summarize_forecast(forecast)
        )
        resp = _call_llm(prompt)
        text = resp['choices'][0]['message']['content']
        result = json.loads(text)
        level = result.get('level')
        message = result.get('message')
        if level not in ('ok', 'info', 'warn', 'critical') or not message:
            raise ValueError(f"invalid response: {result}")
        clean = {'level': level, 'message': message}
        _cache[cache_key] = {'t': now, 'data': clean}
        return clean
    except Exception as e:
        print(f"LLM advisor fallback: {e}")
        return rule_advisor.recommend(reading, forecast, crop)
