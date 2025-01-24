import cv2
import requests
import time
import sys
import argparse
import logging
from typing import Optional, Union
from dataclasses import dataclass

# Configuración del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class CameraConfig:
    """Clase para manejar la configuración de la cámara"""
    source: Union[int, str]  # Puede ser un número para USB o URL para RTSP
    type: str  # 'usb' o 'rtsp'
    prompt: Optional[str] = None  # prompt opcional para el LLM
    retry_interval: int = 5  # segundos entre intentos de reconexión
    reconnect_attempts: int = 3  # número de intentos de reconexión

class CameraCapture:
    def __init__(
        self,
        microservice_url: str,
        capture_interval: int,
        camera_config: CameraConfig
    ):
        """
        Inicializa el capturador de cámara
 
        Args:
            microservice_url: URL del microservicio para subir imágenes
            capture_interval: Intervalo entre capturas en segundos
            camera_config: Configuración de la cámara
        """
        self.microservice_url = microservice_url
        self.capture_interval = capture_interval
        self.camera_config = camera_config
        self.cap: Optional[cv2.VideoCapture] = None

    def initialize_camera(self) -> bool:
        """Inicializa la conexión con la cámara"""
        try:
            self.cap = cv2.VideoCapture(self.camera_config.source)

           # Configuraciones específicas para RTSP
            if self.camera_config.type == 'rtsp':
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                
            if not self.cap.isOpened():
                logger.error(f"No se pudo abrir la cámara: {self.camera_config.source}")
                return False
                
            logger.info(f"Cámara inicializada correctamente: {self.camera_config.source}")
            return True
            
        except Exception as e:
            logger.error(f"Error al inicializar la cámara: {e}")
            return False

    def capture_frame(self) -> Optional[bytes]:
        """Captura un frame de la cámara y lo convierte a bytes"""
        try:
            if not self.cap or not self.cap.isOpened():
                return None

            # Para cámaras RTSP, es buena práctica descartar algunos frames
            if self.camera_config.type == 'rtsp':
                for _ in range(2):  # Descarta 2 frames
                    self.cap.grab()

            ret, frame = self.cap.read()
            if not ret:
                logger.warning("No se pudo capturar el frame")
                return None

            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                logger.warning("No se pudo codificar el frame a JPEG")
                return None

            return buffer.tobytes()

        except Exception as e:
            logger.error(f"Error al capturar frame: {e}")
            return None

    def upload_image(self, image_data: bytes) -> bool:
        """Sube la imagen al microservicio"""
        try:
            # Create form data including both the image and prompt
            files = {'image': ('image.jpg', image_data, 'image/jpeg')}
            data = {}
            if self.camera_config.prompt is not None:
                data['prompt'] = self.camera_config.prompt

            response = requests.post(
                self.microservice_url,
                files=files,
                data=data,  # Include the data dictionary with the prompt
                timeout=10
            )

            if response.status_code != 200:
                logger.error(f"Error al enviar imagen. Código: {response.status_code}")
                return False

            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Error en la petición HTTP: {e}")
            return False

    def run(self):
        """Ejecuta el bucle principal de captura"""
        while True:
            try:
                if not self.cap or not self.cap.isOpened():
                    for attempt in range(self.camera_config.reconnect_attempts):
                        logger.info(f"Intento de reconexión {attempt + 1}")
                        if self.initialize_camera():
                            break
                        time.sleep(self.camera_config.retry_interval)
                    else:
                        logger.error("No se pudo reconectar con la cámara")
                        break

                image_data = self.capture_frame()
                if image_data:
                    self.upload_image(image_data)

                time.sleep(self.capture_interval)

            except KeyboardInterrupt:
                logger.info("Programa terminado por el usuario")
                break
            except Exception as e:
                logger.error(f"Error en el bucle principal: {e}")
                time.sleep(self.camera_config.retry_interval)

        if self.cap:
            self.cap.release()

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Camera service for SAI')
    parser.add_argument('--prompt', type=str, help='Optional prompt for LLM analysis')
    args = parser.parse_args()

    # Ejemplo de configuración para cámara USB
    usb_config = CameraConfig(
        source=0,  # Primera cámara USB
        type='usb',
        prompt=args.prompt  # Pass optional prompt from command line
    )

    # Ejemplo de configuración para cámara RTSP
#        source="rtsp://admin:AZFPBR@10.128.72.78:554/Streaming/Channels/101",
    rtsp_config = CameraConfig(
        source="""rtsp://admin:Saicam1!@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0""",
	type='rtsp',
        prompt=args.prompt  # Pass optional prompt from command line
    )

    # Usa la configuración que necesites
    camera = CameraCapture(
        microservice_url='https://sai.altermundi.net/firebot/upload-image',
        capture_interval=120,
        camera_config=rtsp_config  # o usb_config
#        camera_config=usb_config  # o usb_config
    )

    camera.run()

if __name__ == '__main__':
    main()
