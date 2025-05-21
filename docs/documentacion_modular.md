# Documentación Técnica Modular - Proyecto SAI

## Introducción Técnica General

🔥🌿💻 El Sistema de Alerta de Incendios (SAI) es una plataforma tecnológica distribuida orientada a la detección temprana de focos ígneos mediante el uso de modelos de visión computacional. Su implementación responde a la necesidad urgente de contar con sistemas de monitoreo permanentes en regiones vulnerables a incendios forestales, muchas veces remotas y con infraestructura limitada. Este sistema tiene como premisa la democratización del acceso a herramientas de vigilancia ambiental, aprovechando tecnologías abiertas y de bajo costo.

📡⚙️🌍 SAI se estructura de manera modular, permitiendo la escalabilidad e integración progresiva de tecnologías en función de las necesidades y recursos disponibles. Utiliza dispositivos de bajo consumo en el borde de red (edge) para la captura y transmisión de imágenes, y delega el análisis intensivo a un servidor central equipado con aceleración por GPU. Este diseño modular y distribuido no solo optimiza el uso de recursos, sino que también permite adaptarse a distintos entornos operativos, desde bosques remotos hasta zonas periurbanas.

🖼️🤖📲 Los objetivos principales son tres: capturar imágenes desde zonas remotas utilizando cámaras IP gestionadas por microcontroladores, analizarlas automáticamente mediante modelos de aprendizaje profundo, y emitir alertas en tiempo real utilizando canales confiables como Telegram. A pesar de su diseño robusto, el sistema enfrenta ciertas limitaciones, tales como conectividad intermitente en zonas rurales, condiciones ambientales extremas y la dependencia de infraestructura mínima de red y energía para su operación sostenida. Estas limitaciones son tomadas en cuenta en la arquitectura para asegurar una operación resiliente.

---

## Arquitectura General del Sistema

🏗️🧩📈 El sistema está estructurado principalmente en tres módulos clave: los nodos de borde (SAI-Cam), el servidor central (SAI-Server) y el servicio de inferencia (SAI-Inference). Cada uno de estos módulos cumple una función crítica y diferenciada dentro del flujo de detección y análisis. SAI-Cam se encarga de la adquisición de datos desde el entorno; SAI-Server centraliza la lógica operativa, incluyendo los flujos automatizados a través del framework n8n; y SAI-Inference ejecuta el análisis visual mediante modelos de aprendizaje profundo. Además, se incorpora un cuarto módulo complementario, SAI-Benchmark, que permite auditar el rendimiento del sistema en términos de precisión, sensibilidad y consistencia de los modelos inferenciales. Esta organización modular promueve una gestión clara, mantenible y escalable del sistema completo.

🔁🖼️🧠 Cada nodo edge se encarga de capturar imágenes desde su entorno y enviarlas al servidor central utilizando una red LAN o mediante túneles seguros. Estas imágenes se analizan en el módulo de inferencia y, si se detectan patrones asociados al fuego o al humo, se activa un flujo automatizado que notifica a los actores pertinentes y almacena los datos para su posterior análisis. La arquitectura está diseñada para operar con eficiencia y adaptabilidad, incluso en condiciones donde la conectividad o los recursos de red son limitados. Su topología distribuida garantiza tolerancia a fallos en nodos individuales.

---

## Componentes del Sistema

### Nodos Edge (SAI-Cam)

📷🔌🌦️ Los nodos edge son unidades de monitoreo instaladas en el terreno, basadas en una Raspberry Pi 4 conectada a cuatro cámaras IP exteriores. Estas unidades están protegidas por una carcasa resistente al clima y cuentan con alimentación mediante paneles solares, baterías o energía eléctrica local. Las cámaras están dispuestas de forma estratégica para cubrir 360° alrededor del punto de instalación. Esto permite maximizar la cobertura visual en un radio amplio sin necesidad de mecanismos móviles.

💽📤📡 A nivel de software, los nodos ejecutan un sistema Linux minimalista con servicios personalizados que toman capturas a intervalos configurables, empaquetan los datos con metadatos contextuales (como coordenadas GPS, timestamps y estado del dispositivo) y los envían a un endpoint público HTTPS protegido por SSL y autenticado mediante API Key. Las tareas de mantenimiento incluyen inspección física del hardware, validación del suministro eléctrico y actualizaciones periódicas de software mediante conexiones SSH seguras. Se prevé la incorporación futura de mecanismos de autodiagnóstico.

### Servidor Central (SAI-Server)

🧠🖥️🔐 El servidor central es el núcleo lógico del sistema. Está alojado en un entorno con conectividad estable y equipado con un procesador de 12.ª generación, 32 GB de RAM, una unidad SSD NVMe de alta velocidad y una GPU RTX 3090 para tareas de inferencia. Corre una distribución de Linux optimizada, y utiliza herramientas como Docker para contenerizar sus servicios y Nginx como proxy inverso para gestionar el tráfico entrante y saliente. Este servidor también aloja la base de datos de imágenes procesadas y logs de actividad.

📩📊📎 En este servidor se despliega la plataforma n8n en un contenedor Docker, configurada para recibir imágenes y activar los flujos de trabajo definidos. Estos flujos gestionan la integración con servicios externos (como bots de Telegram), el almacenamiento de registros, y la orquestación de las tareas internas. El servidor también mantiene políticas de seguridad estrictas que incluyen cifrado SSL/TLS, autenticación mediante llaves públicas y backups programados. Su arquitectura modular permite escalar horizontalmente

### Servicio de Inferencia (SAI-Inference)

👁️💡🚨 El módulo de inferencia es el encargado de ejecutar modelos de visión artificial capaces de identificar visualmente signos de incendio en las imágenes capturadas. Actualmente se utilizan modelos como Gemma3, Mistral Small 3.1 y Molmo 7B, ejecutados mediante el framework Ollama con optimizaciones de cuantización (q\_8) para eficiencia en GPU. Estos modelos han sido seleccionados por encontrarse en ese umbral en el que nos permite incorporar tecnología SOTA de visión corriendo en productos consumer.

🔎⚙️📊 El pipeline de inferencia incluye etapas de preprocesamiento de imágenes, ejecución del modelo y análisis de resultados. Las etiquetas generadas son asociadas a umbrales de probabilidad que permiten determinar si se activa una alerta o no. La administración de modelos incluye herramientas para cambiar de versión, evaluar desempeño y registrar estadísticas de precisión. El monitoreo se realiza continuamente y permite registrar métricas como tiempos de respuesta, uso de GPU y tasa de falsos positivos o negativos.

### Plataforma de Automatización (n8n)

🔁⚙️🧠 n8n es un motor de automatización de flujos de trabajo que permite definir acciones reactivas a eventos detectados por el sistema. Su integración en SAI ha sido clave para construir flujos robustos, legibles y fácilmente modificables sin necesidad de reescribir código base. Al tratarse de una herramienta low-code, facilita también la colaboración entre desarrolladores y operadores no técnicos.

🧩🌐📈 El sistema permite la edición de flujos mediante una interfaz gráfica accesible desde el navegador, con capacidades de versionado, ejecución en entorno seguro y pruebas unitarias. Se promueve el uso de buenas prácticas como la modularidad, el uso de nodos de control de errores, y la documentación interna de cada flujo. Además, se planea la creación de una librería de flujos reutilizables para distintos escenarios, como mantenimiento programado, simulaciones o integración con nuevas plataformas de mensajería.

### SAI-Benchmark

📊🧪📷 SAI-Benchmark es el subsistema dedicado a la evaluación comparativa del desempeño de los modelos utilizados. Utiliza un conjunto curado de imágenes con etiquetas verificadas por expertos, y permite evaluar objetivamente la precisión, sensibilidad y especificidad de cada combinación de modelo y prompt. Se considera una herramienta indispensable para garantizar la calidad y trazabilidad del sistema a lo largo del tiempo.

📉🔬📌 El procedimiento consiste en enviar las imágenes de prueba al módulo de inferencia, recolectar los resultados y compararlos con las etiquetas reales. Esto genera matrices de confusión y métricas clave como precisión, recall y F1-score. La herramienta es útil tanto para validar mejoras en el modelo como para detectar regresiones tras cambios en la lógica de inferencia. Se recomienda ejecutar el benchmark ante cualquier actualización de modelo, cambio de parámetros o inclusión de nuevos datos de entrenamiento. En fases futuras se contempla su integración directa en el pipeline de CI/CD del proyecto.

---

## Especificaciones Técnicas Adicionales

🔐🧰🖧 En cuanto a seguridad, SAI implementa comunicación encriptada mediante TLS entre cámaras y nodos edge, además de túneles VPN entre nodos y servidor central usando Zerotier. El acceso a servidores se realiza exclusivamente mediante llaves públicas, y se monitorea activamente la integridad de los servicios. Adicionalmente, se evalúa la incorporación de mecanismos de detección de intrusos (IDS) y autenticación multifactor para accesos administrativos.

🛠️📆📡 El mantenimiento del sistema incluye monitoreo diario de la disponibilidad, actualizaciones semanales de software mediante scripts Git automatizados, y diagnósticos remotos programados. Se dispone de registros centralizados y un manual de procedimientos de emergencia que cubre recuperación ante fallos, redundancia de datos y reinstalación rápida del sistema. Asimismo, se trabaja en una guía interactiva para facilitar el soporte técnico remoto en colaboración con los actores locales.

📘🤝🚀 Este manual técnico está diseñado para servir como referencia integral tanto para equipos de desarrollo como para operadores técnicos en campo, documentando los elementos fundamentales que componen el sistema SAI y ofreciendo las bases necesarias para su mantenimiento, expansión y mejora continua. La intención es que este documento se mantenga vivo y evolucione junto al sistema, reflejando nuevas lecciones aprendidas, cambios tecnológicos y la retroalimentación de usuarios en campo.
