/**
 * Ejemplo de bot de WhatsApp con whatsapp-web.js y ytpremiun-vip.
 *
 * Requisitos:
 *   npm install whatsapp-web.js qrcode-terminal
 *   npm install https://github.com/natsu-dev01/ytpremiun_vip
 *   Python 3.10+ con `requests` y ffmpeg instalado y en el PATH
 *
 * Uso en WhatsApp:
 *   !mp3 https://youtu.be/VIDEO
 *   !mp4 https://youtu.be/VIDEO
 *
 * El wrapper de Node.js ejecuta Python por dentro y devuelve un objeto con
 * `archivo`, `titulo`, `autor`, etc. No hay que analizar la terminal.
 */

"use strict";

const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const {
  descargarAudio,
  descargarVideo,
  verificar,
} = require("ytpremiun-vip");

const CARPETA = process.env.YTPREMIUN_CARPETA || "media";

async function main() {
  const estado = await verificar();
  if (!estado.ok) {
    console.error("ytpremiun-vip no está listo:", estado.error);
    process.exit(1);
  }
  console.log(`Python ${estado.python} | ytpremiun-vip ${estado.version}`);
  if (!estado.ffmpeg) {
    console.warn(
      "Aviso: no se encontró ffmpeg. MP3 y la unión de video+audio fallarán.",
    );
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

      const resultado =
        comando === "!mp3"
          ? await descargarAudio(url, {
              carpeta: CARPETA,
              formatoAudio: "mp3",
              calidadAudio: "192K",
            })
          : await descargarVideo(url, {
              carpeta: CARPETA,
              contenedor: "mp4",
            });

      const archivo = MessageMedia.fromFilePath(resultado.archivo);
      await message.reply(archivo, undefined, {
        caption: `${resultado.titulo}\n${resultado.autor}`,
      });
    } catch (error) {
      await message.reply(`No se pudo descargar: ${error.message}`);
    }
  });

  client.initialize();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
