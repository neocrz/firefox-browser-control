import socket
import json
import time
import os
import base64
import datetime
import threading
import csv
import re
import ollama
import requests 

# CONFIGURATION
SERVER_ADDR = ('127.0.0.1', 8766)
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "files")
CSV_FILE = "uber_rides_log.csv"
INTERVAL_MINUTES = 7

# WEATHER CONFIGURATION
# Coordenadas da cidade base das corridas (Santos)
LATITUDE = -23.9549098
LONGITUDE = -46.3868865

os.makedirs(SAVE_DIR, exist_ok=True)

# Import routes from routes.py
from routes import routes

# Global state for communication
screenshot_received = threading.Event()
latest_image_path = None

def get_current_weather():
    """
    Open-Meteo API forecast.
    """
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&current=temperature_2m,precipitation,weather_code"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            current = data.get("current", {})
            return {
                "temperature": current.get("temperature_2m"),
                "precipitation": current.get("precipitation"), # Chuva em mm
                "weather_code": current.get("weather_code")    # Código (ex: 0=Céu limpo, 61=Chuva leve)
            }
    except Exception as e:
        print(f"[-] Erro ao buscar dados climáticos: {e}")
        
    # Retorna None caso haja falha (evita quebrar o script)
    return {"temperature": None, "precipitation": None, "weather_code": None}

def listen_for_responses(sock):
    """
    Listens continuously on the persistent socket connection.
    """
    global latest_image_path
    try:
        f = sock.makefile('r', encoding='utf-8')
        for line in f:
            if not line: break
            try:
                data = json.loads(line.strip())
                if data.get("action") == "screenshot_result":
                    img_data = data.get("data").split(",")[1]
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    latest_image_path = os.path.join(SAVE_DIR, f"uber_auto_{timestamp}.webp")
                    
                    with open(latest_image_path, "wb") as file:
                        file.write(base64.b64decode(img_data))
                    
                    screenshot_received.set() # Signal main thread
            except Exception as e:
                print(f"[-] Error parsing bridge response: {e}")
    except Exception as e:
        print(f"[FATAL] Listener thread disconnected: {e}")

def process_with_llm(image_path):
    """Sends image to LLM and parses JSON."""
    
    prompt = """
    Get the information from this image and return a json.
    you will only insert ride_id elements that are visible and in this set ("uber_x", "uber_moto", "comfort", "bag"). you will return inside a codeblock.
    you will check the price to fill price and you will check the number in the same line as "mins away" to fill wait_time_minutes
    example: ```json[
    {
        "ride_id": "uber_x", 
        "price": 0.00,
        "wait_time_minutes": 0
    },
    {
        "ride_id": "uber_moto",
        "price": 0.00,
        "wait_time_minutes": 0
    }
    ]
    ```
    IMPORTANT: Do NOT include trailing commas in your JSON output.
"""
    try:
        response = ollama.chat(
            model= 'qwen3.5:2b',
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [image_path]
            }],
        )
        content = response['message']['content']
        
        # Parse the JSON between the codeblocks
        match = re.search(r'```json\s*(\[.*?\])\s*```', content, re.DOTALL)
        if match:
            json_str = match.group(1)
            
            # SAFETY NET: Remove any accidental trailing commas before parsing
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*\]', ']', json_str)
            
            return json.loads(json_str)
        return None
    except Exception as e:
        print(f"[-] LLM Processing Error: {e}")
        return None

def save_to_csv(route_info, ride_data, weather_data):
    """Saves data into a CSV table, now including weather!"""
    file_exists = os.path.isfile(CSV_FILE)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            # Cabecalho atualizado
            writer.writerow(['timestamp', 'from', 'to', 'ride_id', 'price', 'wait_time_minutes', 'temperature_celsius', 'precipitation_mm', 'weather_code'])
        
        for item in ride_data:
            writer.writerow([
                timestamp,
                route_info['from'],
                route_info['to'],
                item.get('ride_id'),
                item.get('price'),
                item.get('wait_time_minutes'),
                weather_data.get('temperature'),
                weather_data.get('precipitation'),
                weather_data.get('weather_code')
            ])

def run_job(sock):
    """Runs a single iteration of navigating and taking screenshots."""
    print(f"\n[!] Cycle started at {datetime.datetime.now().strftime('%H:%M:%S')}")
    
    # 1. Pega o clima atual no início do ciclo
    weather_data = get_current_weather()
    print(f"[🌤️] Clima atual - Temp: {weather_data['temperature']}°C | Chuva: {weather_data['precipitation']}mm")
    
    for route in routes:
        print(f"[*] Route: {route['from']} -> {route['to']}")
        screenshot_received.clear()

        try:
            # 1. Navigate
            nav_msg = {"action": "navigate", "url": route['url']}
            sock.sendall((json.dumps(nav_msg) + '\n').encode('utf-8'))
            
            # 2. Wait for page load
            time.sleep(8)

            # 3. Request Screenshot
            ss_msg = {"action": "screenshot"}
            sock.sendall((json.dumps(ss_msg) + '\n').encode('utf-8'))

            # 4. Wait for listener to save file
            if screenshot_received.wait(timeout=15):
                print(f"[+] Screenshot saved. Analyzing with LLM...")
                data = process_with_llm(latest_image_path)
                
                if data:
                    # Passa os dados do clima para salvar no CSV
                    save_to_csv(route, data, weather_data)
                    print(f"[+] Data logged to CSV.")
                else:
                    print("[-] Failed to extract valid data from LLM response.")
            else:
                print("[-] Timeout: Bridge did not return screenshot.")
                
        except Exception as e:
            print(f"[-] Error communicating with browser during route: {e}")
            
        time.sleep(2) # Short pause between routes

def main():
    # 1. ESTABLISH PERSISTENT CONNECTION ONCE
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(SERVER_ADDR)
        print("[+] Connected to browser bridge.")
    except ConnectionRefusedError:
        print("[-] Connection failed. Is the browser extension/server running?")
        return

    # 2. START LISTENER ONCE
    threading.Thread(target=listen_for_responses, args=(sock,), daemon=True).start()

    print(f"Starting automation: Every {INTERVAL_MINUTES} minutes.")
    
    # 3. LOOP FOREVER USING THE SAME CONNECTION
    try:
        while True:
            start_time = time.time()
            
            run_job(sock)
            
            # Calculate precise sleep to maintain rhythm
            elapsed = time.time() - start_time
            sleep_duration = max(0, (INTERVAL_MINUTES * 60) - elapsed)
            
            print(f"[#] Cycle complete. Sleeping {round(sleep_duration/60, 2)} minutes...")
            time.sleep(sleep_duration)
    except KeyboardInterrupt:
        print("\n[!] Script stopped by user.")
    finally:
        sock.close() # Only close when the whole python script shuts down

if __name__ == "__main__":
    main()