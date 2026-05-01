import requests
import json
import time
import random

# The URL where your app is running locally
API_URL = "http://127.0.0.1:8080/api/data" #"http://smags.engbert.online/api/data"

# Mimic the MAC addresses of your greenhouse sensors
SENSORS = [
    {"mac": "AA", "name": "North Bench"},
    {"mac": "DD:EE:FF:44:55:66", "name": "South Seedlings"}
]

def generate_sensor_data(mac):
    """Generates realistic greenhouse sensor values."""
    return {
        "mac_address": mac,
        "soil_moisture": random.randint(30, 80),
        "soil_temp": round(random.uniform(18.0, 24.0), 1),
        "air_humidity": random.randint(40, 90),
        "air_temp": round(random.uniform(20.0, 28.0), 1)
    }

def main():
    print(f"Starting fake data broadcast to {API_URL}...")
    print("Press Ctrl+C to stop.")
    
    try:
        while True:
            for sensor in SENSORS:
                data = generate_sensor_data(sensor["mac"])
                try:
                    response = requests.post(API_URL, json=data, timeout=5)
                    if response.status_code == 200:
                        print(f"[SUCCESS] Sent data for {sensor['name']} ({sensor['mac']})")
                    else:
                        print(f"[ERROR] Server returned {response.status_code}")
                except requests.exceptions.ConnectionError:
                    print("[FAILED] Could not connect to the server. Is run.py moving?")
            
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nStopping data broadcast.")

if __name__ == "__main__":
    main()