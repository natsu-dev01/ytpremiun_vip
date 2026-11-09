"""Tests de la API de librería para bots."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from ytpremiun_vip.api import (
    Descarga,
    Opciones,
    _ajustar,
    descargar,
    descargar_audio,
    descargar_playlist,
    descargar_video,
    listar_formatos,
    obtener_info,
)
from ytpremiun_vip.downloader import Job, Result
from ytpremiun_vip.errors import ExtractionError, YtPremiunVipError
from ytpremiun_vip.innertube import Format, VideoInfo

VIDEO = "jNQXAC9IVRw"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO}"


def make_info() -> VideoInfo:
    fmt = Format(
        itag=140,
        url="https://example.com/a",
        mime_type="audio/mp4",
        ext="m4a",
        vcodec=None,
        acodec="mp4a.40.2",
        width=None,
        height=None,
        fps=None,
        bitrate=128000,
        audio_bitrate=128.0,
        quality_label=None,
        audio_quality="AUDIO_QUALITY_MEDIUM",
        filesize=1000,
        duration=19.0,
        has_video=False,
        has_audio=True,
        is_progressive=False,
        source_client="visionos",
    )
    return VideoInfo(
        id=VIDEO,
        title="Demo",
        author="Canal",
        channel_id="UC1",
        length_seconds=19,
        view_count=10,
        description="desc",
        keywords=[],
        thumbnails=[],
        upload_date="20050424",
        is_live=False,
        default_audio_language="es",
        formats=[fmt],
        subtitles=[],
        source_client="visionos",
        webpage_url=VIDEO_URL,
    )


def job(video_id: str = VIDEO, **kwargs) -> Job:
    return Job(video_id=video_id, url=f"https://youtu.be/{video_id}", **kwargs)


class FakeDownloader:
    """Sustituto de Downloader que no toca la red."""

    instances: list["FakeDownloader"] = []

    def __init__(self, options):
        self.options = options
        self.inputs: list[str] = []
        FakeDownloader.instances.append(self)

    def discover(self, inputs):
        self.inputs = list(inputs)
        return [job()], []

    def run(self, jobs):
        resultados = []
        for item in jobs:
            if item.video_id == "falla":
                resultados.append(
                    Result(job=item, status="failed", error="error de prueba")
                )
                continue
            ext = "mp3" if self.options.audio_only else "mp4"
            path = self.options.paths / f"{item.video_id}.{ext}"
            resultados.append(
                Result(job=item, status="ok", paths=[path], info=make_info())
            )
        return resultados


class OpcionesTests(unittest.TestCase):
    def test_defaults_para_bot(self):
        options = Opciones().a_options()
        self.assertEqual(options.paths, Path("downloads"))
        self.assertTrue(options.quiet)
        self.assertTrue(options.no_progress)
        self.assertEqual(options.audio_format, "mp3")
        self.assertEqual(options.merge_output_format, "mp4")
        self.assertFalse(options.audio_only)

    def test_mapea_todas_las_rutas_y_banderas(self):
        opciones = Opciones(
            carpeta="media",
            solo_audio=True,
            formato_audio="m4a",
            calidad_audio="320K",
            contenedor="mkv",
            subtitulos=True,
            idiomas_subtitulos="es,en",
            subtitulos_auto=True,
            elementos_playlist="1-2",
            max_descargas=2,
            historial="historial.txt",
            cookies="cookies.txt",
            nombres_ascii=True,
            sobrescribir=True,
            conservar_temporales=True,
            reintentos=2,
            timeout=5,
            proxy="http://proxy",
        )
        options = opciones.a_options()
        self.assertEqual(options.paths, Path("media"))
        self.assertTrue(options.audio_only)
        self.assertEqual(options.audio_format, "m4a")
        self.assertEqual(options.audio_quality, "320K")
        self.assertEqual(options.merge_output_format, "mkv")
        self.assertTrue(options.write_subs)
        self.assertEqual(options.sub_langs, "es,en")
        self.assertTrue(options.write_auto_subs)
        self.assertEqual(options.playlist_items, "1-2")
        self.assertEqual(options.max_downloads, 2)
        self.assertEqual(options.archive, Path("historial.txt"))
        self.assertEqual(options.cookies, Path("cookies.txt"))
        self.assertTrue(options.restrict_filenames)
        self.assertTrue(options.force_overwrites)
        self.assertTrue(options.keep_files)
        self.assertEqual(options.retries, 2)
        self.assertEqual(options.timeout, 5)
        self.assertEqual(options.proxy, "http://proxy")

    def test_trabajos_paralelos(self):
        options = Opciones(trabajos=3).a_options()
        self.assertEqual(options.jobs, 3)
        self.assertEqual(Opciones().a_options().jobs, 1)

    def test_ajustar_no_muta_la_configuracion_original(self):
        base = Opciones(carpeta="original")
        ajustada = _ajustar(base, carpeta="nueva")
        self.assertEqual(base.carpeta, "original")
        self.assertEqual(ajustada.carpeta, "nueva")


class DescargarTests(unittest.TestCase):
    def setUp(self):
        FakeDownloader.instances.clear()

    def test_descargar_audio_usa_solo_audio_y_una_url(self):
        with patch("ytpremiun_vip.api.Downloader", FakeDownloader):
            resultado = descargar_audio(VIDEO_URL, carpeta="media")
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.id, VIDEO)
        self.assertEqual(resultado.titulo, "Demo")
        self.assertEqual(resultado.archivo, Path("media") / f"{VIDEO}.mp3")
        fake = FakeDownloader.instances[-1]
        self.assertEqual(fake.inputs, [VIDEO_URL])
        self.assertTrue(fake.options.audio_only)
        self.assertFalse(fake.options.playlist)
        self.assertEqual(fake.options.paths, Path("media"))

    def test_opciones_se_respetan_si_no_se_pasa_override(self):
        with patch("ytpremiun_vip.api.Downloader", FakeDownloader):
            resultado = descargar_audio(
                VIDEO_URL, opciones=Opciones(formato_audio="m4a", calidad_audio="320K")
            )
        self.assertTrue(resultado.ok)
        fake = FakeDownloader.instances[-1]
        self.assertEqual(fake.options.audio_format, "m4a")
        self.assertEqual(fake.options.audio_quality, "320K")

    def test_descargar_video_fuerza_solo_el_video(self):
        with patch("ytpremiun_vip.api.Downloader", FakeDownloader):
            resultado = descargar_video(f"{VIDEO_URL}&list=PL123")
        self.assertTrue(resultado.ok)
        fake = FakeDownloader.instances[-1]
        self.assertFalse(fake.options.audio_only)
        self.assertFalse(fake.options.playlist)

    def test_descargar_playlist_activa_playlist_y_limites(self):
        class FakePlaylist(FakeDownloader):
            def discover(self, inputs):
                self.inputs = list(inputs)
                return [job(), job("otro")], []

        with patch("ytpremiun_vip.api.Downloader", FakePlaylist):
            resultados = descargar_playlist(
                "https://www.youtube.com/playlist?list=PL123",
                elementos_playlist="1-2",
                max_descargas=2,
            )
        self.assertEqual(len(resultados), 2)
        self.assertTrue(all(resultado.ok for resultado in resultados))
        options = FakePlaylist.instances[-1].options
        self.assertTrue(options.playlist)
        self.assertEqual(options.playlist_items, "1-2")
        self.assertEqual(options.max_downloads, 2)

    def test_descargar_varias_urls_y_conservar_fallos(self):
        class FakeConDatos(FakeDownloader):
            def discover(self, inputs):
                self.inputs = list(inputs)
                return (
                    [job(), job("falla")],
                    [("mala", ExtractionError("url mala"))],
                )

        with patch("ytpremiun_vip.api.Downloader", FakeConDatos):
            resultados = descargar([VIDEO_URL, "mala"])

        self.assertEqual(len(resultados), 3)
        # Primero se informan las URLs que ni siquiera se pudieron interpretar.
        self.assertEqual(resultados[0].estado, "fallido")
        self.assertIn("url mala", resultados[0].error or "")
        self.assertEqual(resultados[1].estado, "ok")
        self.assertEqual(resultados[2].estado, "fallido")
        self.assertFalse(resultados[2].ok)
        self.assertEqual(FakeConDatos.instances[-1].inputs, [VIDEO_URL, "mala"])

    def test_un_fallo_en_descarga_individual_lanza_excepcion(self):
        class FakeFalla(FakeDownloader):
            def discover(self, inputs):
                return [job("falla")], []

        with patch("ytpremiun_vip.api.Downloader", FakeFalla):
            with self.assertRaises(YtPremiunVipError) as ctx:
                descargar_audio(VIDEO_URL)
        self.assertIn("error de prueba", str(ctx.exception))

    def test_descarga_omitida_sigue_siendo_exito(self):
        class FakeOmitida(FakeDownloader):
            def run(self, jobs):
                return [
                    Result(
                        job=jobs[0],
                        status="skipped",
                        paths=[Path("existente.mp3")],
                        info=make_info(),
                    )
                ]

        with patch("ytpremiun_vip.api.Downloader", FakeOmitida):
            resultado = descargar_audio(VIDEO_URL)
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.estado, "omitido")
        self.assertEqual(resultado.archivo, Path("existente.mp3"))

    def test_descarga_a_dict(self):
        descarga = Descarga(
            id=VIDEO,
            url=VIDEO_URL,
            titulo="Demo",
            archivos=[Path("a.mp3"), Path("a.es.srt")],
            playlist_id="PL1",
            playlist_indice=1,
        )
        data = descarga.to_dict()
        self.assertTrue(data["ok"])
        self.assertEqual(data["archivo"], "a.mp3")
        self.assertEqual(data["archivos"], ["a.mp3", "a.es.srt"])
        self.assertEqual(data["playlist_id"], "PL1")


class MetadatosTests(unittest.TestCase):
    def test_obtener_info_rechaza_url_solo_playlist(self):
        with self.assertRaises(ExtractionError):
            obtener_info("https://www.youtube.com/playlist?list=PL123")

    def test_obtener_info_y_listar_formatos(self):
        info = make_info()
        with patch("ytpremiun_vip.api.HttpClient"):
            with patch("ytpremiun_vip.api.InnertubeClient") as cliente:
                cliente.return_value.get_video.return_value = info
                obtenida = obtener_info(VIDEO_URL)
                tabla = listar_formatos(VIDEO_URL)
        self.assertEqual(obtenida.id, VIDEO)
        self.assertIn("140", tabla)
        self.assertIn("audio", tabla)


if __name__ == "__main__":
    unittest.main()
