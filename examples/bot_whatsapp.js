/**
 * Ejemplo de bot de WhatsApp con whatsapp-web.js y ytpremiun-vip.
 *
 * Requisitos:
 *   npm install whatsapp-web.js qrcode-terminal
 *   python -m pip install -e .
 *   ffmpeg instalado y en el PATH
 *
 * Uso en WhatsApp:
 *   !mp3 https://youtu.be/VIDEO
 *   !mp4 https://youtu.be/VIDEO
 *
 * El comando de Python se ejecuta con --json para recibir la ruta final del
 * archivo sin tener que analizar la salida de la terminal.
 */

const { execFile } = require("node:child_process");
const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");

const PYTHON = process.env.PYTHON || "python";
const CARPETA = process.env.YTPREMIUN_CARPETA || "media";

/**
 * Descarga una URL con ytpremiun-vip y devuelve el primer resultado.
 * @param {string} url
 * @param {{ audio?: boolean, formato?: string }} opciones
 */
function descargar(url, { audio = true, formato = "mp3" } = {}) {
  const args = ["-m", "ytpremiun_vip", "--json", "--no-playlist", "-P", CARPETA];
  if (audio) {
    args.push("-x", "--audio-format", formato);
  }
  args.push(url);

  return new Promise((resolve, reject) => {
    execFile(
      PYTHON,
      args,
      {
        windowsHide: true,
        maxBuffer: 32 * 1024 * 1024,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      },
      (error, stdout, stderr) => {
        if (error) {
          return reject(new Error(stderr.trim() || error.message));
        }
        try {
          const resultados = JSON.parse(stdout);
          const resultado = resultados[0];
          if (!resultado || !resultado.ok) {
            return reject(new Error(resultado?.error || "La descarga falló"));
          }
          resolve(resultado);
        } catch (parseError) {
          reject(
            new Error(
              `Salida no válida de Python: ${stdout || stderr}`.slice(0, 500),
            ),
          );
        }
      },
    );
  });
}

const client = new Client({ authStrategy: new LocalAuth() });

client.on("qr", (qr) => qrcode.generate(qr, { small: true }));
client.on("ready", () => console.log("Bot listo. Esperando comandos..."));

client.on("message", async (message) => {
  const texto = (message.body || "").trim();
  const [comando, url] = texto.split(/\s+/);
  if (!["!mp3", "!mp4"].includes(comando) || !url) {
    return;
  }

  try {
    await message.reply("Descargando, espera un momento...");
    const resultado = await descargar(url, { audio: comando === "!mp3" });
    const archivo = MessageMedia.fromFilePath(resultado.archivo);
    await message.reply(archivo, undefined, {
      caption: `${resultado.titulo}\n${resultado.autor}`,
    });
  } catch (error) {
    await message.reply(`No se pudo descargar: ${error.message}`);
  }
});

client.initialize();
