# SAI (Sistema de Alerta de Incendios)

## Descripción Técnica y Metodológica del Proyecto

### Fundamentos y Contexto Tecnológico (Junio 2024)

El proyecto SAI se inicia en junio de 2024 en respuesta al avance significativo en el desarrollo y la disponibilidad de modelos computacionales abiertos de visión artificial con prestaciones avanzadas y requisitos moderados de hardware computacional. Este salto tecnológico propició la posibilidad de diseñar un sistema eficiente y accesible para la detección temprana de incendios forestales, problemática persistente y crítica en nuestra región.

### Estudios Preliminares y Arquitectura del Sistema (Julio-Noviembre 2024)

Durante el periodo comprendido entre julio y noviembre de 2024, se realizaron exhaustivas investigaciones iniciales orientadas a evaluar diferentes modelos de inteligencia artificial open-source aplicables al reconocimiento visual automatizado y a seleccionar el hardware óptimo para soportar análisis inferencial en tiempo real. Se determinó la utilización del Raspberry Pi 4 como plataforma de procesamiento en los nodos periféricos (edge), dada su capacidad técnica suficiente para la adquisición de imágenes y su accesibilidad económica.

Entre agosto y noviembre de 2024, se consolidó la arquitectura modular definitiva, caracterizada por nodos edge equipados con múltiples cámaras IP gestionadas mediante un Raspberry Pi. Estos dispositivos capturan y transmiten imágenes hacia un servidor central específicamente configurado para realizar tareas intensivas de inferencia, liberando así de cargas computacionales significativas a los nodos locales.

### Desarrollo del Producto Mínimo Viable (Noviembre-Diciembre 2024)

En noviembre de 2024 se implementó exitosamente la primera rutina operativa en el servidor central diseñada para la recepción sistemática de imágenes desde los nodos edge. Paralelamente, se efectuaron validaciones con hardware provisional arrendado, confirmando la capacidad efectiva de los modelos open-source seleccionados para la detección visual inmediata de signos precoces de humo y fuego. En diciembre de 2024, se concretó el ensamblaje del servidor definitivo, equipado con una tarjeta gráfica RTX 3090, lo que permitió establecer un Producto Mínimo Viable (MVP) plenamente operativo.

### Implementación de la Plataforma de Automatización n8n (Febrero-Marzo 2025)

Durante febrero y marzo de 2025, los esfuerzos se centraron en el despliegue y configuración de la plataforma de automatización n8n, migrando y optimizando los flujos de trabajo existentes. Este avance permitió establecer lógicas de negocio más robustas, modulares y flexibles, facilitando futuras expansiones funcionales e integraciones multidimensionales del sistema.

### Creación del Repositorio Benchmark (Abril 2025)

En abril de 2025 se creó y activó el repositorio sai-benchmark con el fin de implementar un sistema de evaluación estandarizado y sistemático para monitorear y documentar la evolución y desempeño del proyecto. Este repositorio constituye una herramienta crítica para evaluar el rendimiento cuantitativo y cualitativo de los modelos utilizados y de los flujos de trabajo implementados.

### Estado Actual y Próximas Etapas (Mayo 2025)

En la actualidad, el proyecto se encuentra en fase de implementación inicial de nodos piloto en la provincia de Córdoba, Argentina. Se han establecido convenios con seis municipios, los cuales participarán gratuitamente durante el primer año en calidad de colaboradores activos en la evaluación del sistema. Dichos acuerdos prevén la opción de formalizar contratos de largo plazo al finalizar el periodo de prueba, sujeto a la validación y consolidación técnica del sistema.

La estructura técnica actual incluye:

* Instalaciones piloto compuestas por nodos edge basados en Raspberry Pi, cada uno equipado con cuatro cámaras IP para exteriores.
* Un servidor central dedicado, con GPU RTX 3090, para ejecutar los algoritmos de inferencia.
* Procedimientos iniciales operativos para la recepción y análisis básico de imágenes.

Las actividades previstas para 2025 contemplan:

* Completar la instalación y puesta en marcha de los nodos piloto en campo durante mayo de 2025.
* Recolección sistemática inicial de datos reales, destinados a validación empírica y ajuste inicial de los modelos inferenciales.
* Potencial ajuste fino y optimización de modelos basados en la retroalimentación obtenida de la implementación piloto.

### Objetivos Estratégicos y Desarrollo Futuro (Desde 2025 en adelante)

Con base en los resultados preliminares y sistemáticos derivados de la actual fase de pruebas piloto, el equipo proyecta avanzar en:

* **Optimización avanzada de capacidades de reconocimiento visual:** Implementación de mejoras continuas en modelos de aprendizaje automático y evaluación de dispositivos ópticos de mayor precisión y resolución.
* **Investigación y desarrollo en computación distribuida (edge computing):** Evaluación sistemática de la viabilidad técnica y operativa de modelos de inferencia ligeros ejecutables directamente en dispositivos edge.
* **Integración tecnológica multimodal:** Exploración inicial e implementación experimental de sensores adicionales (térmicos, infrarrojos, acústicos) para mejorar la precisión en la detección temprana y reducir significativamente las tasas de falsos positivos.
* **Automatización del pipeline de datos y entrenamiento dinámico:** Creación de un sistema automatizado para la recolección continua, curación y entrenamiento recurrente de modelos de aprendizaje automático, estableciendo así un ciclo sustentable de innovación tecnológica basada en evidencia empírica.

Este objetivo estratégico representa el núcleo fundamental del esfuerzo actual, orientado a sostener un proceso continuo de innovación basado en datos empíricos y retroalimentación cualificada por expertos.

Aunque el proyecto enfrenta desafíos, como la negativa en la obtención de financiación del Global Innovation Fund, el avance técnico sostenido y la colaboración estrecha con actores locales continúan fortaleciendo la viabilidad del sistema. El objetivo inmediato y concreto sigue siendo la validación operativa del sistema en escenarios reales y la generación del conocimiento crítico necesario para avanzar hacia soluciones tecnológicas robustas, escalables y universalmente accesibles.
