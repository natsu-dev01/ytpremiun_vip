/**
 * Wrapper de Node.js para ytpremiun-vip.
 *
 * No reimplementa el descargador: ejecuta el paquete Python incluido en este
 * mismo paquete con `python -m ytpremiun_vip --json`. Así el bot puede usar
 * promesas y objetos, sin analizar la salida de la terminal a mano.
 *
 * Requisitos:
 *   - Python 3.10 o superior en el PATH (o en YTPREMIUN_PYTHON).
 *   - El paquete Python `requests`.
 *   - ffmpeg para unir video+audio y convertir audio.
 */

"use strict";

const { execFile } = require("node:child_process");
const path = require("node:path");

const RAIZ = __dirname;

const PYTHON_INFO = `
import json, sys
from ytpremiun_vip import Opciones, obtener_info
opciones = json.loads(sys.argv[2] or "{}")
print(json.dumps(obtener_info(sys.argv[1], opciones=Opciones(**opciones)).to_dict(), ensure_ascii=False))
`;

const PYTHON_FORMATOS = `
import json, sys
from ytpremiun_vip import Opciones, listar_formatos
opciones = json.loads(sys.argv[2] or "{}")
print(listar_formatos(sys.argv[1], opciones=Opciones(**opciones)))
`;

const PYTHON_VERIFICAR = `
import json, sys

resultado = {"ok": False}
resultado["python"] = sys.version.split()[0]

try:
    import requests
    resultado["requests"] = requests.__version__
except Exception as exc:
    resultado["error"] = "Falta el paquete Python requests: " + str(exc)
    print(json.dumps(resultado, ensure_ascii=False))
    sys.exit(0)

try:
    import ytpremiun_vip
    resultado["version"] = ytpremiun_vip.__version__
    resultado["ok"] = True
except Exception as exc:
    resultado["error"] = "No se pudo importar ytpremiun_vip: " + str(exc)

try:
    from ytpremiun_vip.media import find_ffmpeg
    resultado["ffmpeg"] = find_ffmpeg()
except Exception:
    resultado["ffmpeg"] = None

print(json.dumps(resultado, ensure_ascii=False))
`;

class YtPremiunError extends Error {
  constructor(mensaje, { codigo = null, stderr = "", resultados = [] } = {}) {
    super(mensaje);
    this.name = "YtPremiunError";
    this.codigo = codigo;
    this.stderr = stderr;
    this.resultados = resultados;
  }
}

function pythonBin() {
  return process.env.YTPREMIUN_PYTHON || process.env.PYTHON || "python";
}

function entornoPython() {
  const existente = process.env.PYTHONPATH;
  return {
    ...process.env,
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
    PYTHONPATH: existente ? `${RAIZ}${path.delimiter}${existente}` : RAIZ,
  };
}

function ejecutar(args) {
  return new Promise((resolve) => {
    execFile(
      pythonBin(),
      args,
      {
        encoding: "utf8",
        windowsHide: true,
        maxBuffer: 64 * 1024 * 1024,
        env: entornoPython(),
      },
      (error, stdout, stderr) => {
        resolve({ error, stdout: stdout || "", stderr: stderr || "" });
      },
    );
  });
}

function extraerJson(texto) {
  const limpio = (texto || "").trim();
  if (!limpio) return null;
  try {
    return JSON.parse(limpio);
  } catch {
    // Algunas versiones de Python pueden añadir avisos antes del JSON.
    const inicio = limpio.search(/[[{]/);
    if (inicio < 0) return null;
    const cierre = limpio[inicio] === "[" ? "]" : "}";
    const fin = limpio.lastIndexOf(cierre);
    if (fin <= inicio) return null;
    try {
      return JSON.parse(limpio.slice(inicio, fin + 1));
    } catch {
      return null;
    }
  }
}

function mensajeError({ error, stderr }) {
  if (error && error.code === "ENOENT") {
    return (
      "No se encontró Python. Instala Python 3.10 o superior y asegúrate " +
      "de que el comando `python` funciona, o define YTPREMIUN_PYTHON con " +
      "la ruta al ejecutable."
    );
  }
  const detalle = (stderr || "").trim();
  if (/No module named ['"]?requests/.test(detalle)) {
    return (
      "Falta el paquete Python `requests`. Instálalo con: " +
      "python -m pip install requests"
    );
  }
  if (/No module named ['"]?ytpremiun_vip/.test(detalle)) {
    return (
      "No se pudo importar el paquete Python ytpremiun_vip. Revisa que el " +
      "paquete npm esté completo o instala la versión Python con: " +
      "python -m pip install git+https://github.com/natsu-dev01/ytpremiun_vip.git"
    );
  }
  return detalle || (error && error.message) || "La operación falló.";
}

async function ejecutarJson(args) {
  const salida = await ejecutar(args);
  const datos = extraerJson(salida.stdout);
  if (datos === null) {
    throw new YtPremiunError(mensajeError(salida), {
      codigo: salida.error ? salida.error.code : null,
      stderr: salida.stderr,
    });
  }
  return datos;
}

function normalizarUrls(urls) {
  const lista = Array.isArray(urls) ? urls : [urls];
  const limpias = lista
    .filter((url) => typeof url === "string")
    .map((url) => url.trim())
    .filter(Boolean);
  if (limpias.length === 0) {
    throw new YtPremiunError("Indica al menos una URL de YouTube.");
  }
  return limpias;
}

function opcionesPython(opciones = {}) {
  const salida = {};
  if (opciones.cookies) salida.cookies = String(opciones.cookies);
  if (opciones.proxy) salida.proxy = String(opciones.proxy);
  if (opciones.timeout != null) salida.timeout = Number(opciones.timeout);
  if (opciones.reintentos != null) salida.reintentos = Number(opciones.reintentos);
  return JSON.stringify(salida);
}

function _buildArgs(urls, opciones = {}, modo = "generic") {
  const lista = normalizarUrls(urls);
  const args = [
    "-m",
    "ytpremiun_vip",
    "--json",
    "-P",
    String(opciones.carpeta || "downloads"),
  ];

  const soloAudio = modo === "audio" || opciones.soloAudio === true;
  if (soloAudio) {
    args.push(
      "-x",
      "--audio-format",
      String(opciones.formatoAudio || opciones.audioFormat || "mp3"),
    );
    if (opciones.calidadAudio || opciones.audioQuality) {
      args.push(
        "--audio-quality",
        String(opciones.calidadAudio || opciones.audioQuality),
      );
    }
  } else {
    if (opciones.formato) args.push("-f", String(opciones.formato));
    if (opciones.contenedor) {
      args.push("--merge-output-format", String(opciones.contenedor));
    }
  }

  const playlistPorDefecto = modo === "generic" || modo === "playlist";
  const playlist =
    opciones.playlist === undefined ? playlistPorDefecto : opciones.playlist;
  args.push(playlist ? "--playlist" : "--no-playlist");

  if (opciones.elementosPlaylist) {
    args.push("--playlist-items", String(opciones.elementosPlaylist));
  }
  if (opciones.maxDescargas != null) {
    args.push("--max-downloads", String(opciones.maxDescargas));
  }
  if (opciones.historial) {
    args.push("--download-archive", String(opciones.historial));
  }
  if (opciones.subtitulos) {
    args.push("--write-subs");
    if (opciones.idiomasSubtitulos) {
      args.push("--sub-langs", String(opciones.idiomasSubtitulos));
    }
    if (opciones.formatoSubtitulos) {
      args.push("--sub-format", String(opciones.formatoSubtitulos));
    }
  }
  if (opciones.subtitulosAuto) args.push("--write-auto-subs");
  if (opciones.nombresAscii) args.push("--restrict-filenames");
  if (opciones.sobrescribir) args.push("--force-overwrites");
  if (opciones.conservarTemporales) args.push("--keep-files");
  if (opciones.reintentos != null) {
    args.push("--retries", String(opciones.reintentos));
  }
  if (opciones.timeout != null) {
    args.push("--timeout", String(opciones.timeout));
  }
  if (opciones.proxy) args.push("--proxy", String(opciones.proxy));
  if (opciones.cookies) args.push("--cookies", String(opciones.cookies));

  args.push(...lista);
  return args;
}

function errorDesdeResultado(resultado) {
  return new YtPremiunError(resultado?.error || "La descarga falló.", {
    resultados: resultado ? [resultado] : [],
  });
}

/**
 * Descarga una o varias URLs y devuelve un resultado por video.
 * No lanza excepción si falla un elemento: revisa `resultado.ok`.
 */
async function descargar(urls, opciones = {}) {
  return ejecutarJson(_buildArgs(urls, opciones, "generic"));
}

/** Descarga un video con audio y lanza YtPremiunError si falla. */
async function descargarVideo(url, opciones = {}) {
  const resultados = await ejecutarJson(_buildArgs(url, opciones, "video"));
  const resultado = resultados[0];
  if (!resultado || !resultado.ok) throw errorDesdeResultado(resultado);
  return resultado;
}

/** Descarga el audio de un video y lanza YtPremiunError si falla. */
async function descargarAudio(url, opciones = {}) {
  const resultados = await ejecutarJson(_buildArgs(url, opciones, "audio"));
  const resultado = resultados[0];
  if (!resultado || !resultado.ok) throw errorDesdeResultado(resultado);
  return resultado;
}

/** Descarga una playlist completa o los elementos indicados. */
async function descargarPlaylist(url, opciones = {}) {
  return ejecutarJson(_buildArgs(url, opciones, "playlist"));
}

/** Obtiene los metadatos de un video sin descargarlo. */
async function obtenerInfo(url, opciones = {}) {
  const datos = await ejecutarJson([
    "-c",
    PYTHON_INFO,
    String(url),
    opcionesPython(opciones),
  ]);
  return datos;
}

/** Devuelve la tabla de formatos disponibles como texto. */
async function listarFormatos(url, opciones = {}) {
  const salida = await ejecutar([
    "-c",
    PYTHON_FORMATOS,
    String(url),
    opcionesPython(opciones),
  ]);
  if (salida.error && !salida.stdout.trim()) {
    throw new YtPremiunError(mensajeError(salida), {
      codigo: salida.error ? salida.error.code : null,
      stderr: salida.stderr,
    });
  }
  return salida.stdout.trim();
}

/**
 * Comprueba Python, requests, el paquete ytpremiun_vip y ffmpeg.
 * Devuelve { ok, python, requests, version, ffmpeg, error }.
 */
async function verificar() {
  return ejecutarJson(["-c", PYTHON_VERIFICAR]);
}

module.exports = {
  YtPremiunError,
  descargar,
  descargarAudio,
  descargarVideo,
  descargarPlaylist,
  obtenerInfo,
  listarFormatos,
  verificar,
  _buildArgs,
};
