"""Interfaz de línea de comandos de ytpremiun_vip."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .downloader import Downloader, Options, Result
from .errors import YtPremiunVipError
from .http import DEFAULT_CONNECTIONS
from .utils import dedupe, read_batch_file


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytpremiun-vip",
        description=(
            "Descargador de YouTube propio (sin yt-dlp): video MP4, audio "
            "MP3/M4A, playlists, subtítulos y colas de descarga."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python -m ytpremiun_vip \"https://youtu.be/VIDEO\"\n"
            "  python -m ytpremiun_vip -x --audio-format mp3 URL\n"
            "  python -m ytpremiun_vip -f \"bv*[height<=1080]+ba\" URL\n"
            "  python -m ytpremiun_vip -F URL\n"
            "  python -m ytpremiun_vip --write-subs --sub-langs es,en URL\n"
            "  python -m ytpremiun_vip -a urls.txt -P descargas\n"
            "  python -m ytpremiun_vip --download-archive historial.txt PLAYLIST\n"
        ),
    )

    parser.add_argument("urls", nargs="*", help="Una o más URLs de YouTube")
    parser.add_argument(
        "-a", "--batch-file",
        help="Archivo de texto con una URL por línea (# para comentarios)",
    )
    parser.add_argument(
        "-P", "--paths", default="downloads",
        help="Carpeta de salida (por defecto: downloads)",
    )
    parser.add_argument(
        "-o", "--output",
        default="%(title)s [%(id)s].%(ext)s",
        help=(
            "Plantilla de nombre. Campos: %%(title)s, %%(id)s, %%(ext)s, "
            "%%(uploader)s, %%(playlist_index)03d... "
            "(por defecto: %%(title)s [%%(id)s].%%(ext)s)"
        ),
    )
    parser.add_argument(
        "-f", "--format", dest="format_spec", default=None,
        help=(
            "Selector de formato: best, bv*+ba, bestaudio, 137+140, "
            "bv*[height<=1080]+ba, etc. (por defecto: bv*+ba/b)"
        ),
    )
    parser.add_argument(
        "-F", "--list-formats", action="store_true",
        help="Muestra los formatos disponibles y no descarga",
    )
    parser.add_argument(
        "-x", "--extract-audio", dest="audio_only", action="store_true",
        help="Descarga solo el audio",
    )
    parser.add_argument(
        "--audio-format", default="mp3",
        choices=["mp3", "m4a", "opus", "wav", "flac", "best"],
        type=str.lower,
        help="Formato de audio de salida (por defecto: mp3)",
    )
    parser.add_argument(
        "--audio-quality", default="192K",
        help="Bitrate de audio, por ejemplo 128K, 192K, 320K (por defecto: 192K)",
    )
    parser.add_argument(
        "--merge-output-format", default="mp4",
        choices=["mp4", "mkv", "webm"],
        type=str.lower,
        help="Contenedor al unir video+audio (por defecto: mp4)",
    )
    parser.add_argument(
        "--write-subs", "--subs", dest="write_subs", action="store_true",
        help="Descarga subtítulos",
    )
    parser.add_argument(
        "--sub-langs", default=None,
        help="Idiomas de subtítulos: es,en o all (por defecto: idioma del audio)",
    )
    parser.add_argument(
        "--sub-format", default="srt",
        choices=["srt", "vtt", "xml"],
        type=str.lower,
        help="Formato de subtítulos (por defecto: srt)",
    )
    parser.add_argument(
        "--write-auto-subs", action="store_true",
        help="Incluye subtítulos automáticos (ASR)",
    )
    parser.add_argument(
        "--playlist", dest="playlist", action="store_true", default=True,
        help="Descarga playlists completas (opción por defecto)",
    )
    parser.add_argument(
        "--no-playlist", dest="playlist", action="store_false",
        help="Si la URL tiene lista, descarga solo ese video",
    )
    parser.add_argument(
        "--playlist-items", default=None,
        help="Elementos de la playlist: 1-5,8,10-",
    )
    parser.add_argument(
        "--max-downloads", type=int, default=None,
        help="Máximo de videos a descargar en esta ejecución",
    )
    parser.add_argument(
        "--download-archive", default=None,
        help="Archivo para recordar IDs ya descargados y no repetirlos",
    )
    parser.add_argument(
        "--restrict-filenames", action="store_true",
        help="Nombres de archivo solo ASCII",
    )
    parser.add_argument(
        "--force-overwrites", action="store_true",
        help="Sobrescribe archivos existentes",
    )
    parser.add_argument(
        "--keep-files", action="store_true",
        help="Conserva los archivos temporales de video/audio",
    )
    parser.add_argument(
        "--no-progress", action="store_true",
        help="Oculta la barra de progreso",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Modo silencioso")
    parser.add_argument("-v", "--verbose", action="store_true", help="Modo detallado")
    parser.add_argument(
        "--retries", type=int, default=5,
        help="Reintentos por descarga (por defecto: 5)",
    )
    parser.add_argument(
        "--connections", "--conexiones", dest="connections", type=int,
        default=DEFAULT_CONNECTIONS,
        help=(
            "Conexiones en paralelo para cada descarga (por defecto: "
            f"{DEFAULT_CONNECTIONS}). Usa 1 para el modo secuencial"
        ),
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=1,
        help=(
            "Videos que se descargan a la vez en playlists o listas de URLs "
            "(por defecto: 1). Prueba 2-4 si tu conexión lo permite"
        ),
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0,
        help="Timeout de red en segundos (por defecto: 20)",
    )
    parser.add_argument("--proxy", default=None, help="Proxy HTTP/SOCKS")
    parser.add_argument(
        "--cookies", default=None,
        help="Archivo de cookies en formato Netscape",
    )
    parser.add_argument(
        "--print-json", action="store_true",
        help="Muestra los metadatos JSON del video",
    )
    parser.add_argument(
        "--json", dest="json_result", action="store_true",
        help=(
            "Imprime un JSON con el resultado de las descargas (rutas, estado "
            "y errores). Ideal para bots; silencia la salida normal"
        ),
    )
    parser.add_argument(
        "--flat-playlist", action="store_true",
        help="Solo imprime las URLs de la playlist, sin descargar",
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="Muestra qué se descargaría, sin descargar",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _resultado_dict(result: Result) -> dict:
    """Convierte un Result interno en un diccionario serializable."""
    job = result.job
    info = result.info
    estados = {"ok": "ok", "skipped": "omitido", "failed": "fallido"}
    estado = estados.get(result.status, result.status)
    return {
        "ok": estado in {"ok", "omitido"},
        "estado": estado,
        "id": job.video_id,
        "url": job.url,
        "titulo": info.title if info else (job.entry_title or job.video_id),
        "autor": info.author if info else "",
        "duracion": info.length_seconds if info else 0,
        "archivo": str(result.paths[0]) if result.paths else None,
        "archivos": [str(path) for path in result.paths],
        "error": result.error,
        "playlist_id": job.playlist_id,
        "playlist_titulo": job.playlist_title,
        "playlist_indice": job.playlist_index,
    }


def _error_dict(url: str, error: Exception) -> dict:
    """Representa una URL que ni siquiera se pudo interpretar."""
    return {
        "ok": False,
        "estado": "fallido",
        "id": "",
        "url": url,
        "titulo": "",
        "autor": "",
        "duracion": 0,
        "archivo": None,
        "archivos": [],
        "error": str(error),
        "playlist_id": None,
        "playlist_titulo": None,
        "playlist_indice": None,
    }


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    json_mode = bool(args.json_result)

    inputs = list(args.urls)
    if args.batch_file:
        try:
            inputs = read_batch_file(args.batch_file) + inputs
        except OSError as exc:
            print(f"ERROR: no se pudo leer {args.batch_file}: {exc}", file=sys.stderr)
            return 2
    inputs = dedupe(inputs)
    if not inputs:
        parser.error("Indica al menos una URL o usa -a/--batch-file")

    options = Options(
        output_template=args.output,
        paths=Path(args.paths),
        format_spec=args.format_spec,
        audio_only=args.audio_only,
        audio_format=args.audio_format,
        audio_quality=args.audio_quality,
        merge_output_format=args.merge_output_format,
        write_subs=args.write_subs,
        sub_langs=args.sub_langs,
        sub_format=args.sub_format,
        write_auto_subs=args.write_auto_subs,
        playlist=args.playlist,
        playlist_items=args.playlist_items,
        max_downloads=args.max_downloads,
        archive=Path(args.download_archive) if args.download_archive else None,
        restrict_filenames=args.restrict_filenames,
        force_overwrites=args.force_overwrites,
        keep_files=args.keep_files,
        quiet=args.quiet or json_mode,
        no_progress=args.no_progress or json_mode,
        verbose=args.verbose,
        retries=args.retries,
        timeout=args.timeout,
        connections=args.connections,
        jobs=args.jobs,
        proxy=args.proxy,
        cookies=Path(args.cookies) if args.cookies else None,
        list_formats=args.list_formats,
        print_json=args.print_json,
        flat_playlist=args.flat_playlist,
        simulate=args.simulate,
    )

    try:
        downloader = Downloader(options)
        jobs, errors = downloader.discover(inputs)

        if json_mode:
            salida = [_error_dict(raw, error) for raw, error in errors]
        else:
            for raw, error in errors:
                print(f"ERROR {raw}: {error}", file=sys.stderr)
            salida = []

        if not jobs:
            if json_mode:
                print(json.dumps(salida, ensure_ascii=False, indent=2))
            else:
                print("No hay nada que descargar.", file=sys.stderr)
            return 1

        if args.flat_playlist:
            if json_mode:
                print(
                    json.dumps(
                        {
                            "urls": [job.url for job in jobs],
                            "errores": [
                                {"url": raw, "error": str(error)}
                                for raw, error in errors
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                for job in jobs:
                    print(job.url)
            return 1 if errors else 0

        results = downloader.run(jobs)

        if json_mode:
            salida.extend(_resultado_dict(result) for result in results)
            print(json.dumps(salida, ensure_ascii=False, indent=2))
            return 0 if all(item["ok"] for item in salida) else 1

        ok = sum(1 for result in results if result.status == "ok")
        skipped = sum(1 for result in results if result.status == "skipped")
        failed = sum(1 for result in results if result.status == "failed")

        print(
            f"\nResumen: {ok} correctos, {skipped} omitidos, {failed} fallidos"
        )
        for result in results:
            if result.status == "failed":
                print(f"  ✗ {result.job.url}: {result.error}", file=sys.stderr)

        return 0 if failed == 0 and not errors else 1
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.", file=sys.stderr)
        return 130
    except YtPremiunVipError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
