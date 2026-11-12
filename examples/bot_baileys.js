/**
 * Ejemplo de bot de WhatsApp con Baileys y ytpremiun-vip.
 *
 * Requisitos:
 *   npm install @whiskeysockets/baileys qrcode-terminal pino
 *   npm install https://github.com/natsu-dev01/ytpremiun_vip
 *   (Opcional) ffmpeg: npm install ffmpeg-static
 *
 * Uso en WhatsApp:
 *   !mp3 https://youtu.be/VIDEO
 *   !mp4 https://youtu.be/VIDEO
 *
 * No hace falta Python: ytpremiun-vip usa su motor nativo en JavaScript.
 * Baileys solo se encarga de recibir el comando y enviar el archivo resultante.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const {
  default: makeWASocket,
  DisconnectReason,
  useMultiFileAuthState,
} = require("@whiskeysockets/baileys");
const { Boom } = require("@hapi/boom");
const pino = require("pino");
const qrcode = require("qrcode-terminal");

const {
  descargarAudio,
  descargarVideo,
  verificar,
} = require("ytpremiun-vip");

const CARPETA = process.env.YTPREMIUN_CARPETA || "media";

function textoDelMensaje(mensaje) {
  const contenido = mensaje.message?.ephemeralMessage?.message || mensaje.message;
  return (
    contenido?.conversation ||
    contenido?.extendedTextMessage?.text ||
    contenido?.imageMessage?.caption ||
    contenido?.videoMessage?.caption ||
    ""
  );
}

function mimetypeAudio(archivo) {
  return path.extname(archivo).toLowerCase() === ".m4a"
    ? "audio/mp4"
    : "audio/mpeg";
}

async function iniciar() {
  const estado = await verificar();
  if (!estado.ok) {
    console.error("ytpremiun-vip no está listo:", estado.error);
    process.exit(1);
  }
  console.log(`Node ${estado.node} | ytpremiun-vip ${estado.version}`);
  if (!estado.ffmpeg) {
    console.warn(
      "Aviso: no se encontró ffmpeg. MP3 y la unión de video+audio fallarán.",
    );
  }

  const { state, saveCreds } = await useMultiFileAuthState("auth_info");
  const sock = makeWASocket({
    auth: state,
    logger: pino({ level: "silent" }),
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) qrcode.generate(qr, { small: true });

    if (connection === "close") {
      const codigo = new Boom(lastDisconnect?.error)?.output?.statusCode;
      if (codigo === DisconnectReason.loggedOut) {
        console.log("Sesión cerrada. Borra auth_info y vuelve a escanear el QR.");
      } else {
        console.log("Reconectando...");
        iniciar();
      }
    } else if (connection === "open") {
      console.log("Bot listo. Esperando comandos...");
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;

    for (const mensaje of messages) {
      if (!mensaje.message || mensaje.key.fromMe) continue;

      const texto = textoDelMensaje(mensaje).trim();
      const [comando, url] = texto.split(/\s+/);
      if (!["!mp3", "!mp4"].includes(comando) || !url) continue;

      const jid = mensaje.key.remoteJid;
      if (!jid) continue;

      try {
        await sock.sendMessage(jid, { text: "Descargando, espera..." });

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

        const datos = fs.readFileSync(resultado.archivo);
        const nombre = path.basename(resultado.archivo);

        if (comando === "!mp3") {
          await sock.sendMessage(jid, {
            audio: datos,
            mimetype: mimetypeAudio(resultado.archivo),
            fileName: nombre,
          });
        } else {
          await sock.sendMessage(jid, {
            video: datos,
            mimetype: "video/mp4",
            fileName: nombre,
            caption: `${resultado.titulo}\n${resultado.autor}`,
          });
        }
      } catch (error) {
        await sock.sendMessage(jid, {
          text: `No se pudo descargar: ${error.message}`,
        });
      }
    }
  });
}

iniciar().catch((error) => {
  console.error(error);
  process.exit(1);
});
