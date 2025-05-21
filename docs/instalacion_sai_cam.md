# Guía de Instalación Nodos Edge (SAI-Cam) 🔧🌐📷

Esta guía detalla paso a paso la instalación y configuración del nodo edge SAI-Cam basado en Raspberry Pi 4, incluyendo la instalación del software requerido y configuración inicial para la conectividad mediante Zerotier. 🛠️📡📝

---

## Requisitos previos 📦🔌🧰

* Raspberry Pi 4
* 4 cámaras IP exteriores
* Fuente de energía (panel solar, baterías, o energía local)
* Tarjeta MicroSD (mínimo 32 GB)
* Switch PoE
* Carcasa resistente a la intemperie
* Conexión Ethernet para acceso a Internet

---

## Instalación Física 🧱📷📍

1. **Montaje del Hardware:** 🛠️📦🔧

   * Ensambla la Raspberry Pi dentro de la carcasa estanca.
   * Conecta las 4 cámaras IP al switch PoE.
   * Conecta el switch PoE a la Raspberry Pi mediante cable Ethernet.
   * Conecta la entrada Ethernet para acceso a Internet al switch PoE.
   * Monta la carcasa en un poste elevado asegurando una cobertura visual de 360°.

2. **Fuente de Energía:** 🔋☀️🔌

   * Instala y conecta tu solución energética asegurando estabilidad en el suministro.

---

## Instalación y Configuración del Software 💻⚙️📡

### 1. Preparación de Raspberry Pi OS 🧠🧾🚀

Para comenzar, descarga e instala la última versión de Raspberry Pi OS Lite utilizando la herramienta oficial [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Una vez completada la instalación y arrancado el sistema, realiza una actualización básica del entorno ejecutando los siguientes comandos: 🖥️🔄💡

```bash
sudo apt update
sudo apt upgrade
```

Esto asegurará que el sistema operativo esté completamente actualizado antes de instalar componentes adicionales. Luego, habilita el acceso remoto mediante SSH, define un usuario con credenciales seguras y asigna un nombre de host único y reconocible que facilite su identificación y administración remota en redes con múltiples dispositivos. 🔐🧑‍💻🌍

### 2. Configuración de Red 🌐📶🧭

* Asegúrate de que la Raspberry Pi tiene acceso a Internet a través de la conexión Ethernet. Zerotier gestionará la conectividad remota sin necesidad de una IP fija. 🌍🔗🔒

### 3. Instalación y Configuración de Zerotier 🛰️🧷🧩

Si aún no tienes una red en Zerotier, deberás crearla previamente desde la plataforma web de Zerotier, o bien utilizar otra solución de VPN para gestionar remotamente tu dispositivo. Recuerda que esto facilita la gestión remota, aunque no impide el funcionamiento autónomo del nodo. 🛜🧑‍💼📡

Ejecuta en terminal:

```bash
curl -s https://install.zerotier.com | sudo bash
sudo zerotier-cli join [Network-ID]
```

* Autoriza el dispositivo en el panel de control de Zerotier. ✅🔐🌐

### 4. Instalación del Software SAI-Cam 🧾📥🧠

* Clona el repositorio del software SAI-Cam:

```bash
git clone https://github.com/AlterMundi/sai-cam.git
cd sai-cam/scripts
```

* Instala dependencias y servicios personalizados:

```bash
chmod +x install.sh
sudo ./install.sh
```

### 5. Configuración del Endpoint Público 🔐🌍📤

* Abre el archivo de configuración `config.ini` dentro del directorio de instalación.
* Añade la URL del endpoint público HTTPS protegido por SSL y tu API Key asignada.

Ejemplo:

```ini
[Server]
endpoint=https://your.endpoint.com
apikey=tu-api-key
```

---

## Validación y Operación Inicial 🔎🖥️✅

* Reinicia la Raspberry Pi para asegurar que todos los servicios se ejecutan correctamente: 🔁🔌🎯

```bash
sudo reboot
```

* Verifica la operación monitoreando logs en: 📋📡📊

```bash
journalctl -u sai-cam.service -f
```

---

## Mantenimiento Regular 🛠️🔄📆

* Monitorea regularmente la salud del sistema. 🔎💡🧩
* Realiza actualizaciones periódicas vía SSH con la siguiente práctica recomendada:

```bash
sudo apt update
sudo apt upgrade
```

* En caso de fallos o inconsistencias, se recomienda reinstalar el software completo siguiendo estos pasos:

```bash
sudo apt update
sudo apt upgrade
git clone https://github.com/AlterMundi/sai-cam.git
cd sai-cam/scripts
chmod +x install.sh
sudo ./install.sh
```

¡Tu nodo edge SAI-Cam está ahora configurado y operativo! 🟢🎉📡
