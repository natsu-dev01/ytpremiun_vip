"""Prueba de extremo a extremo con audio y video largos (uso interno).

Descarga MP3 y MP4 de 1 h y 2 h, mide el tiempo total (incluye ffmpeg) y
borra los archivos al terminar.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ytpremiun_vip import Opciones, descargar_audio, descargar_video  # noqa: E402

BASE = Path(__file__).resolve().parent / "bench_tmp"

CASOS = [
    ("1h MP3 192K", "audio", "https://www.youtube.com/watch?v=Wimkqo8gDZ0", {}),
    (
        "1h MP4 360p",
        "video",
        "https://www.youtube.com/watch?v=Wimkqo8gDZ0",
        {"formato": "bv*[height<=360]+ba"},
    ),
    ("2h MP3 192K", "audio", "https://www.youtube.com/watch?v=WLcljbREoZM", {}),
    (
        "2h MP4 144p",
        "video",
        "https://www.youtube.com/watch?v=WLcljbREoZM",
        {"formato": "bv*[height<=144]+ba"},
    ),
]


def main() -> int:
    if BASE.exists():
        shutil.rmtree(BASE)
    BASE.mkdir(parents=True)

    for etiqueta, tipo, url, extra in CASOS:
        carpeta = BASE / etiqueta.replace(" ", "_")
        opciones = Opciones(
            carpeta=carpeta,
            conexiones=6,
            progreso=False,
            silencioso=True,
            **extra,
        )
        inicio = time.perf_counter()
        if tipo == "audio":
            resultado = descargar_audio(
                url, opciones=opciones, formato_audio="mp3", calidad_audio="192K"
            )
        else:
            resultado = descargar_video(url, opciones=opciones, contenedor="mp4")
        segundos = time.perf_counter() - inicio
        archivo = resultado.archivo
        tam = archivo.stat().st_size if archivo and archivo.exists() else 0
        print(
            f"{etiqueta}: {segundos:.2f}s | {tam / 1048576:.1f} MiB | "
            f"{archivo.name if archivo else 'sin archivo'}"
        )
        shutil.rmtree(carpeta, ignore_errors=True)

    shutil.rmtree(BASE, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
