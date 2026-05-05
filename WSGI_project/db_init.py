import sqlite3
import os

# Update this path if your db is located elsewhere
DB_PATH = "smags.db"

def setup_database():
    # Force a fresh start by removing the old file if it exists
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
            print(f"Cleared existing {DB_PATH} for a fresh start.")
        except PermissionError:
            print(f"Error: Could not delete {DB_PATH}. Ensure the app isn't running.")
            return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("--- Initializing Blank SmaGS Database ---")

    # 1. Create Devices Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            sensor_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            visible_metrics TEXT DEFAULT '["soil_moisture", "soil_temp", "air_humidity", "air_temp"]',
            temp_unit TEXT DEFAULT 'F',
            crop_type TEXT DEFAULT 'generic'
        )
    ''')

    # 2. Create Sessions Table
    # Used to group data logs into specific timeframes or growing seasons
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time DATETIME DEFAULT (datetime('now', 'localtime')),
            end_time DATETIME,
            status TEXT DEFAULT 'active'
        )
    ''')

    # 3. Create Sensor Data Table
    # The main log for all incoming ESP32 transmissions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            sensor_id TEXT,
            air_temp REAL,
            air_humidity REAL,
            soil_temp REAL,
            soil_moisture REAL,
            timestamp DATETIME DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (sensor_id) REFERENCES devices(sensor_id)
        )
    ''')

    # 4. Create an initial active session
    cursor.execute("INSERT INTO sessions (status) VALUES ('active')")

    conn.commit()
    conn.close()
    print("Success: Blank database initialized.")

if __name__ == "__main__":
    setup_database()