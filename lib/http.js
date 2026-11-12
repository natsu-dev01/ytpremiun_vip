/**
 * Cliente HTTP nativo (sin dependencias): reintentos, cookies, proxy,
 * descargas reanudables por rangos y varias conexiones en paralelo.
 */

"use strict";

const http = require("node:http");
const https = require("node:https");
const net = require("node:net");
const tls = require("node:tls");
const zlib = require("node:zlib");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");

const {
  NetworkError,
  DownloadError,
  RangeNotSupportedError,
} = require("./errors");

const DEFAULT_USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/131.0.0.0 Safari/537.36";

const RANGE_SIZE = 1024 * 1024;
const PARALLEL_RANGE_SIZE = 2 * 1024 * 1024;
const DEFAULT_CONNECTIONS = 6;
const DEFAULT_CHUNK_SIZE = 1024 * 1024;

const CONTENT_RANGE_RE = /bytes\s+(\d+)-(\d+)\/(\d+|\*)/i;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function contentRangeTotal(value) {
  if (!value) return null;
  const match = CONTENT_RANGE_RE.exec(String(value));
  if (!match || match[3] === "*") return null;
  const total = Number.parseInt(match[3], 10);
  return Number.isFinite(total) ? total : null;
}

async function exists(filePath) {
  try {
    await fsp.access(filePath, fs.constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

async function readAll(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks);
}

function decompress(stream, encoding) {
  const value = String(encoding || "").toLowerCase();
  if (value.includes("gzip")) return stream.pipe(zlib.createGunzip());
  if (value.includes("deflate")) return stream.pipe(zlib.createInflate());
  if (value.includes("br")) return stream.pipe(zlib.createBrotliDecompress());
  return stream;
}

class CookieJar {
  constructor() {
    /** @type {Map<string, Array<{name: string, value: string, path: string}>>} */
    this.byDomain = new Map();
  }

  loadFile(filePath) {
    const absolute = path.resolve(String(filePath));
    if (!fs.existsSync(absolute)) {
      throw new Error(`No existe el archivo de cookies: ${absolute}`);
    }
    const text = fs.readFileSync(absolute, "utf8");
    let count = 0;
    for (let line of text.split(/\r?\n/)) {
      line = line.trim();
      if (!line || line.startsWith("#")) continue;
      const fields = line.split("\t");
      if (fields.length < 7) continue;
      const domain = fields[0].replace(/^\.+/, "").toLowerCase();
      const cookiePath = fields[2] || "/";
      const name = fields[5];
      const value = fields[6];
      if (!domain || !name) continue;
      this._store(domain, { name, value, path: cookiePath });
      count += 1;
    }
    return count;
  }

  _store(domain, cookie) {
    const key = String(domain || "").toLowerCase().replace(/^\.+/, "");
    if (!key) return;
    let list = this.byDomain.get(key);
    if (!list) {
      list = [];
      this.byDomain.set(key, list);
    }
    const existing = list.findIndex(
      (item) => item.name === cookie.name && item.path === cookie.path,
    );
    if (existing >= 0) list[existing] = cookie;
    else list.push(cookie);
  }

  setCookieHeader(header, hostname) {
    if (!header) return;
    const first = String(header).split(";", 1)[0];
    const index = first.indexOf("=");
    if (index <= 0) return;
    const name = first.slice(0, index).trim();
    const value = first.slice(index + 1).trim();
    if (!name) return;

    let domain = String(hostname || "").toLowerCase();
    let cookiePath = "/";
    for (const part of String(header).split(";").slice(1)) {
      const [rawKey, ...rest] = part.split("=");
      const key = rawKey.trim().toLowerCase();
      const rawValue = rest.join("=").trim();
      if (key === "domain" && rawValue) domain = rawValue.replace(/^\.+/, "").toLowerCase();
      else if (key === "path" && rawValue) cookiePath = rawValue;
    }
    this._store(domain, { name, value, path: cookiePath });
  }

  header(urlObject) {
    const hostname = String(urlObject.hostname || "").toLowerCase();
    const pathname = urlObject.pathname || "/";
    const selected = [];
    for (const [domain, cookies] of this.byDomain) {
      if (hostname !== domain && !hostname.endsWith(`.${domain}`)) continue;
      for (const cookie of cookies) {
        if (!pathname.startsWith(cookie.path || "/")) continue;
        selected.push(`${cookie.name}=${cookie.value}`);
      }
    }
    return selected.join("; ");
  }
}

class HttpClient {
  constructor({
    timeout = 20.0,
    retries = 5,
    proxy = null,
    cookies = null,
  } = {}) {
    this.timeout = Number(timeout) || 20;
    this.retries = Math.max(0, Number.parseInt(retries, 10) || 0);
    this.proxy = proxy ? String(proxy) : null;
    this.jar = new CookieJar();
    if (cookies) this.jar.loadFile(cookies);

    this._httpAgent = new http.Agent({ keepAlive: true, maxSockets: 16 });
    this._httpsAgent = new https.Agent({ keepAlive: true, maxSockets: 16 });
    this._closed = false;
  }

  close() {
    if (this._closed) return;
    this._closed = true;
    this._httpAgent.destroy();
    this._httpsAgent.destroy();
  }

  _proxyUrl() {
    if (!this.proxy) return null;
    try {
      const parsed = new URL(this.proxy);
      if (!["http:", "https:"].includes(parsed.protocol)) {
        throw new NetworkError(
          `Proxy no soportado: ${parsed.protocol}. Usa un proxy HTTP o HTTPS.`,
        );
      }
      return parsed;
    } catch (error) {
      if (error instanceof NetworkError) throw error;
      throw new NetworkError(`Proxy no válido: ${this.proxy}`);
    }
  }

  _baseHeaders(urlObject, headers) {
    const finalHeaders = {
      "User-Agent": DEFAULT_USER_AGENT,
      "Accept-Encoding": "identity",
      ...headers,
    };
    const cookie = this.jar.header(urlObject);
    if (cookie) {
      finalHeaders.Cookie = finalHeaders.Cookie
        ? `${finalHeaders.Cookie}; ${cookie}`
        : cookie;
    }
    return finalHeaders;
  }

  _connectTunnel(proxy, target) {
    return new Promise((resolve, reject) => {
      const proxyPort = proxy.port || (proxy.protocol === "https:" ? 443 : 80);
      const targetPort = target.port || (target.protocol === "https:" ? 443 : 80);
      const connectOptions = {
        host: proxy.hostname,
        port: Number(proxyPort),
      };
      const socket =
        proxy.protocol === "https:"
          ? tls.connect({ ...connectOptions, servername: proxy.hostname })
          : net.connect(connectOptions);

      let buffer = Buffer.alloc(0);
      let settled = false;

      const cleanup = () => {
        socket.removeListener("data", onData);
        socket.removeListener("error", onError);
      };
      const fail = (error) => {
        if (settled) return;
        settled = true;
        cleanup();
        socket.destroy();
        reject(error);
      };
      const onError = (error) => fail(error);
      const onData = (chunk) => {
        buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
        const marker = buffer.indexOf("\r\n\r\n");
        if (marker < 0) {
          if (buffer.length > 64 * 1024) {
            fail(new NetworkError("Respuesta del proxy demasiado grande."));
          }
          return;
        }
        const header = buffer.slice(0, marker).toString("latin1");
        const status = Number.parseInt(header.split(" ")[1] || "0", 10);
        const extra = buffer.slice(marker + 4);
        if (status !== 200) {
          fail(
            new NetworkError(
              `El proxy rechazó la conexión (HTTP ${status || "?"}).`,
            ),
          );
          return;
        }
        settled = true;
        cleanup();
        socket.pause();
        if (extra.length) socket.unshift(extra);
        resolve(socket);
      };

      socket.on("error", onError);
      socket.on("data", onData);
      const ready = proxy.protocol === "https:" ? "secureConnect" : "connect";
      socket.once(ready, () => {
        const auth = proxy.username
          ? `Proxy-Authorization: Basic ${Buffer.from(
              `${decodeURIComponent(proxy.username)}:${decodeURIComponent(
                proxy.password || "",
              )}`,
            ).toString("base64")}\r\n`
          : "";
        socket.write(
          `CONNECT ${target.hostname}:${targetPort} HTTP/1.1\r\n` +
            `Host: ${target.hostname}:${targetPort}\r\n` +
            auth +
            "\r\n",
        );
      });
    });
  }

  async _createRequest(urlObject, method, headers, body, readTimeout) {
    const proxy = this._proxyUrl();
    const isHttps = urlObject.protocol === "https:";

    if (proxy && isHttps) {
      const tunnel = await this._connectTunnel(proxy, urlObject);
      const secure = tls.connect({
        socket: tunnel,
        servername: urlObject.hostname,
      });
      await new Promise((resolve, reject) => {
        secure.once("secureConnect", resolve);
        secure.once("error", reject);
      });
      return http.request({
        host: urlObject.hostname,
        port: Number(urlObject.port || 443),
        path: `${urlObject.pathname}${urlObject.search}`,
        method,
        headers,
        createConnection: () => secure,
      });
    }

    if (proxy) {
      const proxyPort = proxy.port || (proxy.protocol === "https:" ? 443 : 80);
      const transport = proxy.protocol === "https:" ? https : http;
      return transport.request({
        host: proxy.hostname,
        port: Number(proxyPort),
        path: urlObject.href,
        method,
        headers: { ...headers, Host: urlObject.host },
        agent: proxy.protocol === "https:" ? this._httpsAgent : this._httpAgent,
      });
    }

    return (isHttps ? https : http).request(urlObject, {
      method,
      headers,
      agent: isHttps ? this._httpsAgent : this._httpAgent,
    });
  }

  _requestOnce(urlObject, { method, headers, body, readTimeout }) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const fail = (error) => {
        if (settled) return;
        settled = true;
        reject(error);
      };

      this._createRequest(urlObject, method, headers, body, readTimeout)
        .then((request) => {
          const timeoutMs = Math.max(1000, readTimeout * 1000);
          request.setTimeout(timeoutMs, () => {
            request.destroy(new Error("Tiempo de espera agotado"));
          });
          request.on("error", (error) => fail(error));
          request.on("response", (response) => {
            settled = true;
            resolve(response);
          });
          if (body) request.write(body);
          request.end();
        })
        .catch(fail);
    });
  }

  async _singleRequest(urlString, options = {}) {
    const {
      method = "GET",
      headers = {},
      body = null,
      readTimeout = Math.max(this.timeout, 30),
    } = options;
    const urlObject = new URL(urlString);
    const finalHeaders = this._baseHeaders(urlObject, headers);
    if (body !== null && finalHeaders["Content-Length"] === undefined) {
      finalHeaders["Content-Length"] = Buffer.byteLength(body);
    }

    const response = await this._requestOnce(urlObject, {
      method,
      headers: finalHeaders,
      body,
      readTimeout,
    });

    const setCookies = response.headers["set-cookie"];
    if (Array.isArray(setCookies)) {
      for (const cookie of setCookies) {
        this.jar.setCookieHeader(cookie, urlObject.hostname);
      }
    }

    return { response, urlObject };
  }

  async _followingRedirects(urlString, options = {}, redirects = 5) {
    const { response, urlObject } = await this._singleRequest(urlString, options);

    const status = response.statusCode || 0;
    if ([301, 302, 303, 307, 308].includes(status)) {
      const location = response.headers.location;
      response.resume();
      if (!location || redirects <= 0) return response;
      const next = new URL(location, urlObject);
      let method = options.method || "GET";
      let body = options.body ?? null;
      if (status === 303 || ((status === 301 || status === 302) && method === "POST")) {
        method = "GET";
        body = null;
      }
      return this._followingRedirects(
        next.toString(),
        { ...options, method, body },
        redirects - 1,
      );
    }
    return response;
  }

  async _request(urlString, options = {}) {
    const attempts = Math.max(0, options.retries ?? this.retries) + 1;
    let lastError = null;
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        const response = await this._followingRedirects(urlString, options);
        const status = response.statusCode || 0;
        if ([429, 500, 502, 503, 504].includes(status) && attempt < attempts) {
          response.resume();
          await sleep(Math.min(0.6 * 2 ** (attempt - 1), 5) * 1000);
          continue;
        }
        return response;
      } catch (error) {
        lastError = error;
      }
      if (attempt < attempts) {
        await sleep(Math.min(0.6 * 2 ** (attempt - 1), 5) * 1000);
      }
    }
    throw new NetworkError(`Error de red: ${lastError?.message || lastError}`);
  }

  _ensureOk(response, urlString) {
    const status = response.statusCode || 0;
    if (status >= 400) {
      response.resume();
      throw new NetworkError(`HTTP ${status}: ${urlString}`);
    }
    return response;
  }

  async getText(urlString, { headers = {}, encoding = "utf-8" } = {}) {
    const response = this._ensureOk(
      await this._request(urlString, { headers }),
      urlString,
    );
    const stream = decompress(response, response.headers["content-encoding"]);
    const data = await readAll(stream);
    return data.toString(encoding);
  }

  async getBytes(urlString, { headers = {} } = {}) {
    const response = this._ensureOk(
      await this._request(urlString, { headers }),
      urlString,
    );
    const stream = decompress(response, response.headers["content-encoding"]);
    return readAll(stream);
  }

  async postJson(urlString, payload, { headers = {} } = {}) {
    const body = Buffer.from(JSON.stringify(payload), "utf8");
    const response = this._ensureOk(
      await this._request(urlString, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body,
      }),
      urlString,
    );
    const stream = decompress(response, response.headers["content-encoding"]);
    const data = await readAll(stream);
    try {
      return JSON.parse(data.toString("utf8"));
    } catch (error) {
      throw new NetworkError(`Respuesta no válida de YouTube: ${urlString}`);
    }
  }

  async _probeRanges(urlString, headers) {
    try {
      const response = await this._followingRedirects(urlString, {
        headers: { ...headers, Range: "bytes=0-0" },
      });
      const status = response.statusCode || 0;
      if (status === 206) {
        const total = contentRangeTotal(response.headers["content-range"]);
        response.resume();
        return { total, ranges: true };
      }
      if (status === 200) {
        const length = Number.parseInt(response.headers["content-length"], 10);
        response.resume();
        return { total: Number.isFinite(length) ? length : null, ranges: false };
      }
      response.resume();
    } catch {
      // Sin sondeo se intenta la descarga normal.
    }
    return { total: null, ranges: false };
  }

  async _fetchRange(
    urlString,
    start,
    end,
    { headers = {}, attempts = 1 } = {},
  ) {
    let lastError = null;
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        const response = await this._followingRedirects(urlString, {
          headers: { ...headers, Range: `bytes=${start}-${end}` },
        });
        const status = response.statusCode || 0;

        if (status === 200) {
          response.resume();
          throw new RangeNotSupportedError(
            "El servidor ignoró la cabecera Range y devolvió el archivo completo.",
          );
        }
        if (status === 416) {
          response.resume();
          throw new DownloadError("El servidor no tiene datos para este archivo.");
        }
        if (status !== 206) {
          response.resume();
          if ([401, 403, 404, 410].includes(status)) {
            throw new DownloadError(
              `El servidor rechazó la descarga (HTTP ${status}). ` +
                "El enlace puede haber caducado; vuelve a intentarlo.",
            );
          }
          throw new DownloadError(`HTTP ${status} al descargar el archivo`);
        }

        return await readAll(response);
      } catch (error) {
        if (error instanceof RangeNotSupportedError) throw error;
        if (
          error instanceof DownloadError &&
          /rechazó|no tiene datos/.test(error.message)
        ) {
          throw error;
        }
        lastError = error;
      }
      if (attempt < attempts) {
        await sleep(Math.min(2 ** (attempt - 1), 10) * 1000);
      }
    }
    throw new DownloadError(
      `No se pudo descargar el bloque ${start}-${end}: ${
        lastError?.message || lastError
      }`,
    );
  }

  _loadState(statePath, total, rangeSize, count) {
    const completed = new Set();
    if (!fs.existsSync(statePath)) return completed;
    try {
      const data = JSON.parse(fs.readFileSync(statePath, "utf8"));
      if (data.total !== total || data.chunk_size !== rangeSize) {
        return completed;
      }
      for (const rawIndex of data.completed || []) {
        const index = Number.parseInt(rawIndex, 10);
        if (Number.isFinite(index) && index >= 0 && index < count) {
          completed.add(index);
        }
      }
    } catch {
      return new Set();
    }
    return completed;
  }

  async _saveState(statePath, total, rangeSize, completed) {
    const payload = JSON.stringify({
      total,
      chunk_size: rangeSize,
      completed: [...completed].sort((a, b) => a - b),
    });
    const temporary = `${statePath}.tmp`;
    await fsp.writeFile(temporary, payload, "utf8");
    await fsp.rename(temporary, statePath).catch(async () => {
      await fsp.rm(statePath, { force: true });
      await fsp.rename(temporary, statePath);
    });
  }

  async _parallelDownload(
    urlString,
    destination,
    part,
    total,
    {
      progress = null,
      headers = {},
      chunkSize = DEFAULT_CHUNK_SIZE,
      connections = DEFAULT_CONNECTIONS,
      attempts = 1,
    } = {},
  ) {
    const rangeSize = PARALLEL_RANGE_SIZE;
    const count = Math.ceil(total / rangeSize);
    const statePath = `${part}.state`;

    let completed = this._loadState(statePath, total, rangeSize, count);

    // Varios workers guardan el estado a la vez. Serializamos las escrituras
    // para que no compartan el mismo archivo .tmp y se pierda el progreso.
    let saveChain = Promise.resolve();
    const persistState = () => {
      const snapshot = new Set(completed);
      saveChain = saveChain
        .catch(() => {})
        .then(() => this._saveState(statePath, total, rangeSize, snapshot));
      return saveChain;
    };

    if (!(await exists(part))) {
      completed = new Set();
      await fsp.writeFile(part, Buffer.alloc(0), { flag: "a" });
    } else if (!(await exists(statePath))) {
      const done = (await fsp.stat(part)).size;
      completed = new Set();
      const completeChunks = Math.min(count, Math.floor(done / rangeSize));
      for (let index = 0; index < completeChunks; index += 1) {
        completed.add(index);
      }
      if (done >= total) {
        for (let index = 0; index < count; index += 1) completed.add(index);
      }
    }

    const chunkLength = (index) => {
      const start = index * rangeSize;
      return Math.min(total, start + rangeSize) - start;
    };

    let doneBytes = [...completed].reduce(
      (sum, index) => sum + chunkLength(index),
      0,
    );
    if (progress) progress(doneBytes, total);

    const pending = [];
    for (let index = 0; index < count; index += 1) {
      if (!completed.has(index)) pending.push(index);
    }

    if (pending.length === 0) {
      await fsp.rm(destination, { force: true });
      await fsp.rename(part, destination);
      await fsp.rm(statePath, { force: true });
      if (progress) progress(total, total);
      return total;
    }

    await persistState();

    const workers = Math.min(Math.max(1, connections), pending.length);
    let nextIndex = 0;
    let stopped = false;
    const errors = [];
    let savedAt = 0;

    const worker = async () => {
      let handle = null;
      try {
        handle = await fsp.open(part, "r+");
        while (!stopped) {
          const position = nextIndex;
          nextIndex += 1;
          if (position >= pending.length) return;
          const index = pending[position];
          const start = index * rangeSize;
          const end = Math.min(total - 1, start + rangeSize - 1);
          const data = await this._fetchRange(urlString, start, end, {
            headers,
            attempts,
          });
          const expected = end - start + 1;
          if (data.length !== expected) {
            throw new DownloadError(
              `Bloque incompleto: ${data.length} de ${expected} bytes`,
            );
          }
          await handle.write(data, 0, data.length, start);
          completed.add(index);
          doneBytes += expected;
          if (progress) progress(doneBytes, total);

          const now = Date.now();
          if (now - savedAt >= 1000 || completed.size === count) {
            savedAt = now;
            await persistState();
          }
        }
      } catch (error) {
        stopped = true;
        errors.push(error);
      } finally {
        if (handle) await handle.close().catch(() => {});
      }
    };

    await Promise.all(Array.from({ length: workers }, () => worker()));

    if (errors.length > 0) {
      await persistState().catch(() => {});
      throw errors[0];
    }

    if (completed.size < count) {
      await persistState().catch(() => {});
      throw new DownloadError(
        "La descarga quedó incompleta; vuelve a intentarlo para reanudar.",
      );
    }

    await fsp.rm(destination, { force: true });
    await fsp.rename(part, destination);
    await fsp.rm(statePath, { force: true });
    if (progress) progress(total, total);
    return total;
  }

  async _writeChunks(handle, stream, startPosition, onChunk) {
    let position = startPosition;
    for await (const chunk of stream) {
      if (!chunk || chunk.length === 0) continue;
      const buffer = Buffer.from(chunk);
      await handle.write(buffer, 0, buffer.length, position);
      position += buffer.length;
      onChunk(buffer.length);
    }
  }

  async _sequentialDownload(
    urlString,
    destination,
    part,
    total,
    {
      progress = null,
      headers = {},
      resume = true,
      rangeSize = RANGE_SIZE,
      attempts = 1,
    } = {},
  ) {
    let done = 0;
    const partExists = await exists(part);
    if (resume && partExists) {
      done = (await fsp.stat(part)).size;
    } else if (partExists) {
      await fsp.rm(part, { force: true });
    }

    if (total !== null && done > total) {
      await fsp.rm(part, { force: true });
      done = 0;
    }
    if (total !== null && done >= total) {
      if (await exists(part)) {
        await fsp.rm(destination, { force: true });
        await fsp.rename(part, destination);
      }
      if (progress) progress(total, total);
      return total;
    }

    let failures = 0;
    let completed = false;
    let lastError = null;

    while (true) {
      const end =
        total !== null
          ? Math.min(done + rangeSize - 1, total - 1)
          : done + rangeSize - 1;

      let response = null;
      try {
        response = await this._followingRedirects(urlString, {
          headers: { ...headers, Range: `bytes=${done}-${end}` },
        });
        const status = response.statusCode || 0;

        if (status === 416) {
          response.resume();
          if (done === 0) {
            throw new DownloadError(
              "El servidor no tiene datos para este archivo.",
            );
          }
          completed = true;
          break;
        }
        if (![200, 206].includes(status)) {
          response.resume();
          if ([401, 403, 404, 410].includes(status)) {
            throw new DownloadError(
              `El servidor rechazó la descarga (HTTP ${status}). ` +
                "El enlace puede haber caducado; vuelve a intentarlo.",
            );
          }
          throw new DownloadError(`HTTP ${status} al descargar el archivo`);
        }

        if (status === 206 && total === null) {
          total = contentRangeTotal(response.headers["content-range"]);
        }
        if (status === 200 && done > 0) done = 0;

        const requestStart = done;
        const requested = end - requestStart + 1;
        let received = 0;
        if (progress) progress(done, total);

        const handle = await fsp.open(part, done > 0 ? "r+" : "w");
        try {
          await this._writeChunks(handle, response, done, (size) => {
            done += size;
            received += size;
            if (progress) progress(done, total);
          });
        } finally {
          await handle.close();
        }

        if (status === 200) {
          if (total !== null && done < total) {
            throw new DownloadError(
              `Descarga incompleta: ${done} de ${total} bytes`,
            );
          }
          if (total === null) total = done;
          completed = true;
          break;
        }

        if (received === 0) {
          throw new DownloadError(
            "El servidor devolvió una respuesta vacía; vuelve a intentarlo.",
          );
        }
        if (total !== null) {
          if (done >= total) {
            completed = true;
            break;
          }
        } else if (received < requested) {
          total = done;
          completed = true;
          break;
        }

        failures = 0;
        continue;
      } catch (error) {
        if (
          error instanceof DownloadError &&
          /HTTP 4|rechazó|no tiene datos/.test(error.message)
        ) {
          throw error;
        }
        lastError = error;
      }

      try {
        done = (await fsp.stat(part)).size;
      } catch {
        done = 0;
      }
      if (total !== null && done >= total) {
        completed = true;
        break;
      }

      failures += 1;
      if (failures >= attempts) break;
      await sleep(Math.min(2 ** (failures - 1), 10) * 1000);
    }

    if (!completed || !(await exists(part))) {
      throw new DownloadError(
        `No se pudo descargar después de ${attempts} intentos: ${
          lastError?.message || lastError || "error desconocido"
        }`,
      );
    }

    await fsp.rm(destination, { force: true });
    await fsp.rename(part, destination);
    const finalSize = (await fsp.stat(destination)).size;
    if (total === null) total = finalSize;
    if (progress) progress(finalSize, total);
    return finalSize;
  }

  /**
   * Descarga a un .part y renombra al terminar.
   *
   * Con `connections > 1` usa varias conexiones y un archivo de estado para
   * reanudar sin repetir bloques. Si el servidor no admite rangos, vuelve al
   * modo secuencial.
   */
  async streamDownload(
    urlString,
    destination,
    {
      expectedSize = null,
      progress = null,
      headers = {},
      resume = true,
      chunkSize = DEFAULT_CHUNK_SIZE,
      rangeSize = RANGE_SIZE,
      connections = 1,
    } = {},
  ) {
    const dest = String(destination);
    await fsp.mkdir(path.dirname(dest), { recursive: true });
    const part = `${dest}.part`;
    const statePath = `${part}.state`;

    let total = expectedSize ? Number(expectedSize) : null;
    const attempts = this.retries + 1;
    const requestedConnections = Math.max(
      1,
      Math.min(Number.parseInt(connections, 10) || 1, 16),
    );
    const largeEnough = total === null || total > PARALLEL_RANGE_SIZE;

    if (requestedConnections > 1 && largeEnough) {
      let rangesOk = true;
      if (total === null) {
        const probe = await this._probeRanges(urlString, headers);
        total = probe.total;
        rangesOk = probe.ranges;
      }
      if (rangesOk && total !== null && total > PARALLEL_RANGE_SIZE) {
        try {
          return await this._parallelDownload(urlString, dest, part, total, {
            progress,
            headers,
            chunkSize,
            connections: requestedConnections,
            attempts,
          });
        } catch (error) {
          if (error instanceof RangeNotSupportedError) {
            await fsp.rm(part, { force: true });
            await fsp.rm(statePath, { force: true });
            total = null;
          } else {
            throw error;
          }
        }
      }
    }

    return this._sequentialDownload(urlString, dest, part, total, {
      progress,
      headers,
      resume,
      rangeSize,
      attempts,
    });
  }
}

module.exports = {
  DEFAULT_USER_AGENT,
  DEFAULT_CONNECTIONS,
  DEFAULT_CHUNK_SIZE,
  RANGE_SIZE,
  PARALLEL_RANGE_SIZE,
  HttpClient,
  CookieJar,
  sleep,
  contentRangeTotal,
  readAll,
};
