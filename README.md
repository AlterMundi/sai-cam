# sai-cam
### SAI cammera control and access.

###### Campost folder contains a single file thats forward images from cammera (USB or RTSP) to de SAI Firebot

## Para instalar y ejecutar el servicio:

1. Crea un directorio para el proyecto:
```bash
mkdir ~/camera_project
cd ~/camera_project
```

2. Copia todos los archivos anteriores en el directorio.

3. Ejecuta el script de instalación:
```bash
chmod +x install.sh
./install.sh
```

Este código incluye:

- Configuración mediante YAML
- Compresión de imágenes configurable
- Monitoreo de salud del sistema
- Almacenamiento local con sistema de reciclaje
- Manejo seguro de SSL/TLS
- Sistema de logs con rotación
- Gestión automática del almacenamiento
- Servicio systemd para ejecución automática
- Reinicio automático en caso de fallas

Para monitorear el servicio:
```bash
sudo systemctl status camera_service
sudo journalctl -u camera_service -f
```

Para modificar la configuración:
```bash
sudo nano /etc/camera_service/config.yaml
sudo systemctl restart camera_service
``` 
