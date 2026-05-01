import os
import json
import sqlite3
import pytz
import urllib.parse
import advisor
from datetime import datetime
from urllib.parse import parse_qs
from jinja2 import Environment, FileSystemLoader
from weather import get_forecast
from advisor import recommend

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, os.getenv("DB_PATH", "smags.db"))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
CSS_DIR = os.path.join(STATIC_DIR, "css")
LOCAL_TZ = pytz.timezone('America/Chicago')

ALL_METRICS = ["soil_moisture", "soil_temp", "air_humidity", "air_temp"]

jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

# --- DATABASE & COOKIE HELPERS ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_available_themes():
    """Scans static/css to populate the UI Museum dropdown."""
    try:
        if not os.path.exists(CSS_DIR):
            return ['green']
        files = [f.replace('.css', '') for f in os.listdir(CSS_DIR) if f.endswith('.css')]
        return sorted(files) if files else ['green']
    except Exception:
        return ['green']

def get_cookie(environ, key, default='false'):
    """Helper to parse cookies from the WSGI environment."""
    cookie_str = environ.get('HTTP_COOKIE', '')
    if not cookie_str:
        return default
    cookies = {}
    for item in cookie_str.split(';'):
        if '=' in item:
            k, v = item.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies.get(key, default)

def get_device_visibility(environ, sensor_id):
    """Helper to extract metric preferences from the user's cookie."""
    cookie_str = environ.get('HTTP_COOKIE', '')
    if 'device_visibility=' in cookie_str:
        try:
            raw_cookie = cookie_str.split('device_visibility=')[1].split(';')[0]
            import urllib.parse
            data = json.loads(urllib.parse.unquote(raw_cookie))
            return data.get(sensor_id, ALL_METRICS) 
        except:
            pass
    return ALL_METRICS

# --- ROUTE HANDLERS ---

def handle_favicon(environ, start_response):
    """Serves the SmaGS logo/favicon to the browser."""
    try:
        with open(os.path.join(BASE_DIR, 'favicon.ico'), 'rb') as f:
            data = f.read()
        start_response('200 OK', [('Content-Type', 'image/x-icon')])
        return [data]
    except FileNotFoundError:
        start_response('404 Not Found', [('Content-Type', 'text/plain')])
        return [b"Favicon not found"]


def handle_index(environ, start_response):
    """Main Dashboard Route - Updated to handle nested Cookie preferences."""
    consented = get_cookie(environ, 'cookie_consent', 'false') == 'true'
    theme = get_cookie(environ, 'theme', 'green') if consented else 'green'
    visibility_prefs = {}
    cookie_str = environ.get('HTTP_COOKIE', '')
    if 'device_visibility=' in cookie_str:
        try:
            raw_cookie = cookie_str.split('device_visibility=')[1].split(';')[0]
            visibility_prefs = json.loads(urllib.parse.unquote(raw_cookie))
        except Exception as e:
            print(f"Cookie Parse Error: {e}")
    conn = get_db()
    latest_data = conn.execute("""
        SELECT s.*, d.name 
        FROM sensor_data s
        LEFT JOIN devices d ON s.sensor_id = d.sensor_id
        ORDER BY s.timestamp DESC LIMIT 20
    """).fetchall()
    devices_raw = conn.execute("SELECT sensor_id, name, crop_type FROM devices").fetchall()
    conn.close()
    device_map = {}
    for d in devices_raw:
        s_id = d['sensor_id']
        sensor_config = visibility_prefs.get(s_id, {})
        
        user_visible = sensor_config.get("metrics", ALL_METRICS)
        user_unit = sensor_config.get("unit", "C") 

        device_map[s_id] = {
            "name": d['name'], 
            "visible_metrics": user_visible,
            "unit": user_unit
        }

    forecast = get_forecast()
    recomendations = {}
    seen_for_rec = set()
    for row in latest_data:
        sid=row['sensor_id']
        if sid in seen_for_rec:
            continue
        seen_for_rec.add(sid)
        current_crop = device_map.get(sid,{}).get('crop_type','generic')
        reading = {
            'soil_moisture': row['soil_moisture'],
            'soil_temp': row['soil_temp'],
            'air_temp': row['air_temp'],
            'air_humidity': row['air_humidity']
        }
        recomendations[sid] = recommend(reading, forecast, crop=current_crop)

    template = env.get_template("index.html")
    content = template.render(
        latest=latest_data, 
        device_map=device_map, 
        theme=theme,
        themes=get_available_themes(),
        all_metrics=ALL_METRICS,
        consented=consented,
        forecast=forecast,
        recomendations=recomendations
    ).encode("utf-8")

    start_response("200 OK", [("Content-Type", "text/html")])
    return [content]

def handle_devices(environ, start_response):
    consented = get_cookie(environ, 'cookie_consent', 'false') == 'true'
    theme = get_cookie(environ, 'theme', 'green') if consented else 'green'

    conn = get_db()
    device_rows = conn.execute("SELECT * FROM devices").fetchall()
    conn.close()
    
    device_list = []
    for row in device_rows:
        d = dict(row)
        raw_metrics = d.get('visible_metrics')
        if raw_metrics:
            try:
                d['visible_metrics'] = json.loads(raw_metrics)
            except:
                d['visible_metrics'] = ALL_METRICS
        else:
            d['visible_metrics'] = ALL_METRICS
            
        device_list.append(d)

    template = env.get_template('devices.html')
    crop_list = list(advisor.CROP_PROFILES.keys())
    content = template.render(
        devices=device_list, 
        crop_list=crop_list,
        theme=theme, 
        consented=consented
    ).encode("utf-8")

    start_response("200 OK", [("Content-Type", "text/html")])
    return [content]

def handle_sessions(environ, start_response):
    """Lists all monitoring sessions with summary stats."""
    conn = get_db()
    sessions = conn.execute("""
        SELECT s.*, 
               (SELECT COUNT(*) FROM sensor_data WHERE session_id = s.id) as reading_count,
               (SELECT MIN(timestamp) FROM sensor_data WHERE session_id = s.id) as start_time,
               (SELECT MAX(timestamp) FROM sensor_data WHERE session_id = s.id) as end_time
        FROM sessions s
        ORDER BY s.id DESC
    """).fetchall()
    current_session_id = sessions[0]['id'] if sessions else None
    conn.close()

    template = env.get_template("sessions.html")
    content = template.render(
        sessions=sessions,
        current_session_id=current_session_id,
        theme=get_cookie(environ, 'theme', 'green')
    ).encode("utf-8")

    start_response("200 OK", [("Content-Type", "text/html")])
    return [content]

def handle_set_theme(environ, start_response):
    """Handles theme updates via 303 Redirect."""
    try:
        content_length = int(environ.get('CONTENT_LENGTH', 0))
        post_data = environ['wsgi.input'].read(content_length).decode('utf-8')
        params = parse_qs(post_data)
        
        new_theme = params.get('theme', ['green'])[0]
        
        consented = get_cookie(environ, 'cookie_consent', 'false') == 'true'
        
        headers = [
            ("Location", "/?theme_updated=1"),
            ("Cache-Control", "no-cache, no-store, must-revalidate"),
            ("Pragma", "no-cache"),
            ("Expires", "0")
        ]
        
        if consented:
            headers.append((
                "Set-Cookie", 
                f"theme={new_theme}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"
            ))

        start_response("303 See Other", headers)
        return [b""]
    except Exception:
        start_response("303 See Other", [("Location", "/")])
        return [b""]

def handle_accept_cookies(environ, start_response):
    """Sets the consent cookie."""
    headers = [
        ("Location", "/"),
        ("Set-Cookie", "cookie_consent=true; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000")
    ]
    start_response("303 See Other", headers)
    return [b""]

def handle_api_data(environ, start_response):
    """Endpoint for ESP32/Pi sensor nodes with Session Healing and Auto-Registration."""
    if environ.get('REQUEST_METHOD') != 'POST':
        start_response("405 Method Not Allowed", [("Content-Type", "text/plain")])
        return [b"Method Not Allowed"]
    
    try:
        length = int(environ.get('CONTENT_LENGTH', 0))
        data = json.loads(environ['wsgi.input'].read(length))
        
        mac = data.get("mac_address") or data.get("sensor_id")
        
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT sensor_id FROM devices WHERE sensor_id = ?", (mac,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO devices (sensor_id, name) VALUES (?, ?)", 
                           (mac, f"New Sensor ({mac[-5:]})"))

        cursor.execute("SELECT id FROM sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            session_id = row[0]
        else:
            cursor.execute("INSERT INTO sessions (status) VALUES ('active')")
            session_id = cursor.lastrowid

        ts = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO sensor_data 
            (session_id, sensor_id, soil_moisture, soil_temp, air_humidity, air_temp, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session_id, mac, data["soil_moisture"], data["soil_temp"], 
              data["air_humidity"], data["air_temp"], ts))

        conn.commit()
        conn.close()

        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps({"status": "success", "session": session_id}).encode("utf-8")]

    except Exception as e:
        print(f"API Error: {e}")
        start_response("400 Bad Request", [("Content-Type", "text/plain")])
        return [str(e).encode("utf-8")]
    

def handle_update_device(environ, start_response):
    if environ.get('REQUEST_METHOD') == 'POST':
        try:
            request_body_size = int(environ.get('CONTENT_LENGTH', 0))
            request_body = environ['wsgi.input'].read(request_body_size).decode('utf-8')
            from urllib.parse import parse_qs
            params = parse_qs(request_body)
            sensor_id = params.get('sensor_id', [None])[0]
            new_name = params.get('name', ['Unnamed Sensor'])[0]
            if sensor_id:
                conn = get_db()
                new_crop = params.get('crop_type',['generic'])[0]
                conn.execute("""
                    UPDATE devices 
                    SET name = ?, crop_type = ?
                    WHERE sensor_id = ?
                """, (new_name, new_crop, sensor_id))
                conn.commit()
                conn.close()
            start_response("303 See Other", [("Location", "/devices")])
            return [b""]
        except Exception as e:
            print(f"Error updating device name: {e}")
            start_response("500 Internal Server Error", [("Content-Type", "text/plain")])
            return [str(e).encode('utf-8')]
    start_response("405 Method Not Allowed", [("Content-Type", "text/plain")])
    return [b"Method Not Allowed"]

def handle_sensor_history(environ, start_response):
    """API Endpoint for Chart.js historical data."""
    path = environ.get('PATH_INFO', '')
    sensor_id = path.split('/')[-1]
    params = parse_qs(environ.get('QUERY_STRING', ''))
    hours = int(params.get('hours', [24])[0])
    
    conn = get_db()
    query = """
        SELECT timestamp, soil_moisture, soil_temp, air_humidity, air_temp 
        FROM sensor_data 
        WHERE sensor_id = ? AND timestamp >= datetime('now', ?) 
        ORDER BY timestamp ASC
    """
    history = conn.execute(query, (sensor_id, f'-{hours} hours')).fetchall()
    conn.close()

    content = json.dumps([dict(row) for row in history]).encode('utf-8')
    start_response("200 OK", [("Content-Type", "application/json")])
    return [content]

def handle_delete_session(environ, start_response):
    """Deletes a session and cascades to delete all sensor_data points."""
    if environ.get('REQUEST_METHOD') == 'POST':
        try:
            length = int(environ.get('CONTENT_LENGTH', 0))
            post_data = parse_qs(environ['wsgi.input'].read(length).decode('utf-8'))
            session_id = post_data.get('session_id', [None])[0]

            if session_id:
                conn = get_db()
                conn.execute("DELETE FROM sensor_data WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                conn.commit()
                conn.close()

            start_response("303 See Other", [("Location", "/sessions")])
            return [b""]
        except Exception as e:
            print(f"Delete Error: {e}")
            
    start_response("303 See Other", [("Location", "/sessions")])
    return [b""]

# --- MAIN WSGI APP ---

def application(environ, start_response):
    path = environ.get('PATH_INFO', '/')

    # Routing Logic
    if path == "/":
        return handle_index(environ, start_response)
    elif path == "/favicon.ico":
        return handle_favicon(environ, start_response)
    elif path == "/set_theme":
        return handle_set_theme(environ, start_response)
    elif path == "/accept_cookies":
        return handle_accept_cookies(environ, start_response)
    elif path == "/api/data":
        return handle_api_data(environ, start_response)
    elif path == "/devices":
        return handle_devices(environ, start_response)
    elif path == "/update_device":
        return handle_update_device(environ, start_response)
    elif path.startswith("/api/history/"):
        return handle_sensor_history(environ, start_response)
    elif path == "/sessions":
        return handle_sessions(environ, start_response)
    elif path == "/delete_session":
        return handle_delete_session(environ, start_response)
    
    # Static File Server
    elif path.startswith("/static/"):
        file_path = os.path.join(BASE_DIR, path.lstrip("/"))
        if os.path.exists(file_path) and os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                content = f.read()
            
            mime = "text/plain"
            if path.endswith(".css"): mime = "text/css"
            elif path.endswith(".js"): mime = "application/javascript"
            elif path.endswith(".png"): mime = "image/png"
            elif path.endswith(".jpg") or path.endswith(".jpeg"): mime = "image/jpeg"
            
            start_response("200 OK", [("Content-Type", mime)])
            return [content]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"404 - Not Found"]