from onvif import ONVIFCamera
import requests
from requests.auth import HTTPDigestAuth
from pathlib import Path
import os

# 🧠 Configuración de la cámara (configurable via environment variables)
CAMERA_IP = os.getenv('CAMERA_IP', '192.168.1.100')  # Example IP
CAMERA_PORT = int(os.getenv('CAMERA_PORT', '8000'))
USERNAME = os.getenv('CAMERA_USERNAME', 'admin')
PASSWORD = os.getenv('CAMERA_PASSWORD', 'your_password_here')  # CHANGE THIS!

def get_snapshot():
    try:
        print("🧩 Conectando a la cámara ONVIF...")
        cam = ONVIFCamera(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD, '/opt/sai-cam/venv/lib/python3.4/site-packages/wsdl/')

        # Get Hostname
        resp = cam.devicemgmt.GetHostname()
        print ('My camera`s hostname: ' + str(resp.Name))

        # Get system date and time
        dt = cam.devicemgmt.GetSystemDateAndTime()
        tz = dt.TimeZone
        year = dt.UTCDateTime.Date.Year
        hour = dt.UTCDateTime.Time.Hour

        print("🎛️ Obteniendo el servicio de medios...")
        media_service = cam.create_media_service()

        print("📺 Obteniendo perfiles disponibles...")
        profiles = media_service.GetProfiles()
        if not profiles:
            print("❌ No se encontraron perfiles.")
            return
        
        # print (profiles)

        profile = profiles[0]  # Usamos el primero disponible

        print(f"📸 Solicitando snapshot URI para el perfil: {profile.Name}...")
        snapshot_uri = media_service.GetSnapshotUri({'ProfileToken': profile.token})
        url = snapshot_uri.Uri
        print(f"✅ Snapshot URI: {url}")

        print("⬇️ Descargando imagen...")
        # response = requests.get(url, auth=(USERNAME, PASSWORD))
        # response = requests.get(url, auth=requests.auth.HTTPBasicAuth(USERNAME, PASSWORD))
        response = requests.get(url, auth=HTTPDigestAuth(USERNAME, PASSWORD))
        if response.status_code == 200:
            img_path = Path("snapshot.jpg")
            img_path.write_bytes(response.content)
            print(f"🖼️ Imagen guardada en {img_path.resolve()}")
        else:
            print(f"⚠️ Falló la descarga del snapshot: {response.status_code}")
            print(response)

    except Exception as e:
        print(f"🚨 Error: {e}")

if __name__ == "__main__":
    get_snapshot()
