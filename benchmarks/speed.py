"""Mide la velocidad de descarga de un formato concreto (uso interno).

Ejemplo:
    python benchmarks/speed.py URL 140 --connections 6
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ytpremiun_vip import obtener_info  # noqa: E402
from ytpremiun_vip.http import DEFAULT_CONNECTIONS, HttpClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("itag", type=int)
    parser.add_argument("--label", default="")
    parser.add_argument("--connections", type=int, default=DEFAULT_CONNECTIONS)
    args = parser.parse_args()

    info = obtener_info(args.url)
    fmt = next(fmt for fmt in info.formats if fmt.itag == args.itag)
    temp = Path(__file__).resolve().parent / "bench_tmp"
    temp.mkdir(exist_ok=True)
    destino = temp / f"{info.id}.f{fmt.itag}.{fmt.ext}"
    destino.unlink(missing_ok=True)

    http = HttpClient(timeout=30, retries=3)
    inicio = time.perf_counter()
    tam = http.stream_download(
        fmt.url,
        destino,
        expected_size=fmt.filesize,
        headers={
            "User-Agent": http.session.headers["User-Agent"],
            "Referer": "https://www.youtube.com/",
        },
        connections=args.connections,
    )
    segundos = time.perf_counter() - inicio
    mib = tam / (1024 * 1024)
    etiqueta = args.label or f"{info.id} itag {fmt.itag} {fmt.ext} {fmt.resolution}"
    print(
        f"{etiqueta}: {mib:.1f} MiB en {segundos:.2f}s "
        f"= {mib / segundos:.2f} MiB/s "
        f"({tam * 8 / segundos / 1_000_000:.1f} Mbps)"
    )
    destino.unlink(missing_ok=True)
    try:
        temp.rmdir()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
