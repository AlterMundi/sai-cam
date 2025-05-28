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

Para comenzar, descarga e instala la última versión de Raspberry Pi OS Lite utilizando la herramienta oficial [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Una vez completada la instalación y arrancado el sistema, habilita el acceso remoto mediante SSH, define un usuario con credenciales seguras y asigna un nombre de host único y reconocible que facilite su identificación y administración remota en redes con múltiples dispositivos. 🔐🧑‍💻🌍

### 2. Configuración de Red 🌐📶🧭

* Asegúrate de que la Raspberry Pi tiene acceso a Internet a través de la conexión Ethernet. Zerotier gestionará la conectividad remota sin necesidad de una IP fija. 🌍🔗🔒

### 3. Actualización del Sistema 🔄💡

Realiza una actualización básica del entorno ejecutando los siguientes comandos: 🖥️🔄💡

```bash
sudo apt update
sudo apt upgrade
sudo apt install git
```

Esto asegurará que el sistema operativo esté completamente actualizado y que Git esté disponible antes de instalar componentes adicionales.

### 4. Instalación y Configuración de Zerotier 🛰️🧷🧩

Si aún no tienes una red en Zerotier, deberás crearla previamente desde la plataforma web de Zerotier, o bien utilizar otra solución de VPN para gestionar remotamente tu dispositivo. Recuerda que esto facilita la gestión remota, aunque no impide el funcionamiento autónomo del nodo. 🛜🧑‍💼📡

Ejecuta en terminal:

```bash
curl -s https://install.zerotier.com | sudo bash
sudo zerotier-cli join [Network-ID]
```

* Autoriza el dispositivo en el panel de control de Zerotier. ✅🔐🌐

### 5. Instalación del Software SAI-Cam 🧾📥🧠

* Clona el repositorio del software SAI-Cam:

```bash
git clone https://github.com/AlterMundi/sai-cam.git
cd sai-cam
```

* Configura el archivo `config.yaml` con las necesidades específicas del nodo a instalar:

```bash
nano config/config.yaml
```

Edita los parámetros necesarios como:
- URL del endpoint público HTTPS
- API Key asignada
- Configuración de cámaras
- Otros parámetros específicos del nodo

* Instala dependencias y servicios personalizados:

```bash
cd scripts
chmod +x install.sh
sudo ./install.sh
```

### 6. Reconfiguración Posterior 🔄⚙️📝

Si necesitas modificar la configuración después de la instalación inicial o después de actualizar a una nueva versión del software, puedes usar la opción `--configure-only`:

```bash
sudo ./install.sh --configure-only
```

Esta opción permite:
- Aplicar cambios realizados en el archivo `config.yaml`
- Reconfigurar servicios sin reinstalar dependencias
- Actualizar configuración tras descargar una nueva versión del repositorio

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
git pull  # si ya tienes el repositorio clonado
# o git clone https://github.com/AlterMundi/sai-cam.git si es una instalación nueva
cd sai-cam/scripts
chmod +x install.sh
sudo ./install.sh
```

¡Tu nodo edge SAI-Cam está ahora configurado y operativo! 🟢🎉📡
