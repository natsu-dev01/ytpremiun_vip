# Guía de contribución

¡Gracias por querer mejorar **ytpremiun-vip**! Este proyecto es un descargador
de YouTube escrito desde cero, sin depender de yt-dlp. Tiene dos
implementaciones del mismo motor: Python (`ytpremiun_vip/`, paquete pip) y
Node.js (`lib/`, paquete npm).

## Antes de empezar

- No subas **cookies**, tokens, archivos `.env` ni contenido con derechos de
  autor.
- No se aceptan cambios que usen DRM, contenido privado o evasión de pagos.
- Para cambios grandes, abre primero una *issue* para acordar el enfoque.

## Entorno de desarrollo

Para el paquete Python:

```bash
git clone https://github.com/natsu-dev01/ytpremiun_vip.git
cd ytpremiun_vip

python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS

pip install -e .
```

Para el paquete npm solo necesitas Node.js 18 o superior; no hace falta crear
un entorno de Python:

```bash
npm install
```

Necesitas `ffmpeg` para probar la unión de video y audio y la conversión de
audio. Consulta el README para instalarlo.

## Tests

Todos los tests unitarios funcionan sin red:

```bash
npm test
python -m unittest discover -s tests -v
```

Antes de enviar un *pull request*:

1. Ejecuta la batería completa de tests de ambos paquetes.
2. Añade tests para el comportamiento nuevo o corregido.
3. Mantén los mensajes y la documentación en español.
4. No rompas la API pública de `ytpremiun_vip` ni de `ytpremiun-vip` sin
   justificarlo.

## Estilo

- Python 3.10 o superior, con anotaciones de tipos cuando aporten claridad.
- Node.js 18 o superior, CommonJS y sin dependencias obligatorias.
- Código y nombres internos en inglés; mensajes de usuario y documentación en
  español.
- Respeta el formato existente: 4 espacios en Python y 2 en JavaScript,
  comillas dobles, líneas de hasta 88 caracteres aproximadamente.
- Evita dependencias nuevas si se pueden resolver con la biblioteca estándar.

## Reportar errores

Incluye:

- Sistema operativo y versión de Python o Node.js.
- Versión de `ytpremiun-vip` (`python -m ytpremiun_vip --version` o
  `npx ytpremiun-vip --version`).
- URL de ejemplo (sin datos privados).
- Salida con `-v` si es un fallo de red o extracción.
- ¿Tienes ffmpeg instalado y en el `PATH`?

## Licencia de las contribuciones

Al enviar un cambio aceptas que se publique bajo la licencia **MIT** del
proyecto. Consulta [`LICENSE`](LICENSE).
