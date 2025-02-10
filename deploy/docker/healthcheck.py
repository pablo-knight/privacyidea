#!/privacyidea/venv/bin/python
import requests
import os
import sys
import time

# Setze Default-Werte, falls die Umgebungsvariablen nicht vorhanden sind
HOST = os.getenv('PI_HOST', 'localhost')  # Alternative zu HOSTNAME, falls manuell gesetzt
PORT = os.getenv('PI_PORT', '8080')       # Standard-Port als Fallback
RETRY_COUNT = 3                            # Anzahl der Wiederholungen
TIMEOUT = 5                                # Sekunden pro Anfrage

BASE_URL = f"http://{HOST}:{PORT}"

def health_check():
    for attempt in range(RETRY_COUNT):
        try:
            response = requests.get(BASE_URL, timeout=TIMEOUT)
            if response.status_code == 200:
                print(f"[OK] Healthcheck erfolgreich - Status: {response.status_code}")
                return 0  # Erfolg
            else:
                print(f"[WARN] Unerwarteter Statuscode: {response.status_code}, Versuch {attempt+1}/{RETRY_COUNT}")
        except requests.ConnectionError:
            print(f"[ERROR] Keine Verbindung zu {BASE_URL}, Versuch {attempt+1}/{RETRY_COUNT}")
        except requests.Timeout:
            print(f"[ERROR] Timeout nach {TIMEOUT} Sekunden bei {BASE_URL}, Versuch {attempt+1}/{RETRY_COUNT}")
        except Exception as e:
            print(f"[ERROR] Unerwarteter Fehler: {str(e)}, Versuch {attempt+1}/{RETRY_COUNT}")

        time.sleep(2)  # Warte kurz, bevor der nächste Versuch erfolgt

    print(f"[CRITICAL] Healthcheck fehlgeschlagen nach {RETRY_COUNT} Versuchen.")
    sys.exit(1)  # Fehlerhafter Container-Zustand

if __name__ == "__main__":
    sys.exit(health_check())

