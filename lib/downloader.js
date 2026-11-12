/** Orquestador nativo: descubre videos, selecciona formatos y descarga. */

"use strict";

const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");

const { ExtractionError, MediaError, YtPremiunVipError } = require("./errors");
const { formatTable, selectFormat } = require("./formats");
const {
  DEFAULT_CONNECTIONS,
  DEFAULT_USER_AGENT,
  HttpClient,
} = require("./http");
const {
  InnertubeClient,
  formatKind,
  formatResolution,
  videoInfoToDict,
} = require("./innertube");
const { PlaylistClient } = require("./playlist");
const { ProgressPrinter } = require("./progress");
const { downloadSubtitle, selectTracks } = require("./subtitles");
const { parseInput, videoUrl } = require("./urls");
const {
  buildOutputPath,
  humanBytes,
  humanDuration,
  parseIndexSpec,
} = require("./utils");

function defaultOptions(overrides = {}) {
  return {
    outputTemplate: "%(title)s [%(id)s].%(ext)s",
    paths: "downloads",
    formatSpec: null,
    audioOnly: false,
    audioFormat: "mp3",
    audioQuality: "192K",
    mergeOutputFormat: "mp4",
    writeSubs: false,
    subLangs: null,
    subFormat: "srt",
    writeAutoSubs: false,
    playlist: true,
    playlistItems: null,
    maxDownloads: null,
    archive: null,
    restrictFilenames: false,
    forceOverwrites: false,
    keepFiles: false,
    quiet: false,
    noProgress: false,
    verbose: false,
    retries: 5,
    timeout: 20.0,
    connections: DEFAULT_CONNECTIONS,
    jobs: 1,
    proxy: null,
    cookies: null,
    listFormats: false,
    printJson: false,
    flatPlaylist: false,
    simulate: false,
    ...overrides,
  };
}

function makeJob({
  videoId,
  url,
  playlistId = null,
  playlistTitle = null,
  playlistIndex = null,
  entryTitle = null,
}) {
  return {
    video_id: videoId,
    url,
    playlist_id: playlistId,
    playlist_title: playlistTitle,
    playlist_index: playlistIndex,
    entry_title: entryTitle,
  };
}

function makeResult(job, status, { paths = [], error = null, info = null } = {}) {
  return { job, status, paths, error, info };
}

function replaceExtension(filePath, extension) {
  const current = path.extname(filePath);
  return current ? `${filePath.slice(0, -current.length)}.${extension}` : `${filePath}.${extension}`;
}

class Downloader {
  constructor(options = {}) {
    this.options = defaultOptions(options);
    this.http = new HttpClient({
      timeout: this.options.timeout,
      retries: this.options.retries,
      proxy: this.options.proxy,
      cookies: this.options.cookies,
    });
    this.innertube = new InnertubeClient(this.http, {
      verbose: this.options.verbose,
    });
    this.playlists = new PlaylistClient(this.http);
    this._archive = this._loadArchive();
    this._archiveChain = Promise.resolve();
  }

  close() {
    this.http.close();
  }

  // ------------------------------------------------------------------ cola
  async discover(inputs) {
    const jobs = [];
    const errors = [];

    for (const raw of inputs) {
      try {
        const parsed = parseInput(raw);
        const usePlaylist = Boolean(
          parsed.playlist_id &&
            this.options.playlist &&
            !(
              parsed.video_id &&
              String(parsed.playlist_id).startsWith("RD")
            ),
        );

        if (usePlaylist) {
          this._log(`Leyendo playlist ${parsed.playlist_id}...`);
          const playlist = await this.playlists.fetch(parsed.playlist_id);
          if (playlist.warning) this._warn(playlist.warning);

          const contains = parseIndexSpec(this.options.playlistItems);
          let added = 0;
          for (const entry of playlist.entries) {
            if (contains && !contains(entry.index)) continue;
            jobs.push(
              makeJob({
                videoId: entry.video_id,
                url: entry.url,
                playlistId: playlist.id,
                playlistTitle: playlist.title,
                playlistIndex: entry.index,
                entryTitle: entry.title,
              }),
            );
            added += 1;
          }
          this._log(
            `Playlist: ${playlist.title} (${added} videos seleccionados)`,
          );
          if (added === 0) {
            throw new ExtractionError(
              "Ningún elemento de la playlist coincide con --playlist-items.",
            );
          }
        } else if (parsed.video_id) {
          jobs.push(
            makeJob({
              videoId: parsed.video_id,
              url: videoUrl(parsed.video_id),
            }),
          );
        } else {
          throw new ExtractionError(
            "La URL solo contiene una playlist. " +
              "Usa --no-playlist únicamente con URLs de video.",
          );
        }
      } catch (error) {
        errors.push({ url: raw, error });
      }
    }

    const seen = new Set();
    const unique = [];
    for (const job of jobs) {
      if (seen.has(job.video_id)) continue;
      seen.add(job.video_id);
      unique.push(job);
    }

    return { jobs: unique, errors };
  }

  async run(jobs) {
    let selected = jobs;
    if (this.options.maxDownloads !== null && this.options.maxDownloads !== undefined) {
      selected = jobs.slice(0, Math.max(0, Number(this.options.maxDownloads)));
    }

    const total = selected.length;
    if (total === 0) return [];

    const workers = Math.max(
      1,
      Math.min(Number(this.options.jobs) || 1, total),
    );
    if (workers === 1) {
      const results = [];
      for (let index = 0; index < total; index += 1) {
        results.push(
          await this._processSafe(selected[index], index + 1, total),
        );
      }
      return results;
    }

    const results = new Array(total);
    let next = 0;
    const worker = async () => {
      while (true) {
        const index = next;
        next += 1;
        if (index >= total) return;
        results[index] = await this._processSafe(
          selected[index],
          index + 1,
          total,
        );
      }
    };
    await Promise.all(Array.from({ length: workers }, () => worker()));
    return results.filter(Boolean);
  }

  async _processSafe(job, position, total) {
    try {
      return await this.process(job, position, total);
    } catch (error) {
      if (this.options.verbose) console.error(error);
      this._warn(`✗ ${job.video_id}: ${error.message}`);
      return makeResult(job, "failed", { error: error.message });
    }
  }

  // -------------------------------------------------------------- descarga
  async process(job, position, total) {
    if (this._archive.has(job.video_id)) {
      this._log(
        `↷ [${position}/${total}] ${job.video_id}: ya está en el archivo; se omite.`,
      );
      return makeResult(job, "skipped");
    }

    const info = await this.innertube.getVideo(job.video_id);
    if (job.entry_title && (!info.title || info.title === info.id)) {
      info.title = job.entry_title;
    }

    if (!this.options.quiet) {
      process.stdout.write(`\n[${position}/${total}] ${info.title}\n`);
      const details = [info.author];
      if (info.length_seconds) details.push(humanDuration(info.length_seconds));
      details.push(`cliente ${info.source_client}`);
      process.stdout.write(
        `  ${details.filter(Boolean).join(" · ")}\n`,
      );
    }

    if (this.options.printJson) {
      process.stdout.write(
        `${JSON.stringify(videoInfoToDict(info), null, 2)}\n`,
      );
    }

    if (this.options.listFormats) {
      process.stdout.write(`${formatTable(info.formats)}\n`);
      return makeResult(job, "ok", { info });
    }

    const selection = this._select(info);
    const ext = this._targetExt(selection);
    const finalPath = this._buildPath(info, job, selection);
    await fsp.mkdir(path.dirname(finalPath), { recursive: true });

    if (fs.existsSync(finalPath) && !this.options.forceOverwrites) {
      this._log(`  ↷ Ya existe: ${finalPath}`);
      return makeResult(job, "skipped", { paths: [finalPath], info });
    }

    if (this.options.simulate) {
      this._log(`  (simulación) ${finalPath}`);
      for (const format of [
        selection.progressive,
        selection.video,
        selection.audio,
      ]) {
        if (!format) continue;
        const detail = format.has_video
          ? formatResolution(format)
          : format.ext;
        this._log(`    itag ${format.itag}: ${formatKind(format)} ${detail}`);
      }
      return makeResult(job, "ok", { paths: [finalPath], info });
    }

    const tempDir = path.join(path.dirname(finalPath), ".ytpremiun-vip-tmp");
    await fsp.mkdir(tempDir, { recursive: true });
    const created = [];
    const metadata = this._metadata(info, job);
    let actualFinal = finalPath;

    if (this.options.audioOnly) {
      const source = selection.audio || selection.progressive;
      if (!source) throw new ExtractionError("No se seleccionó ninguna pista de audio.");
      const sourcePath = path.join(tempDir, `${info.id}.f${source.itag}.${source.ext}`);
      await this._downloadSource(source, sourcePath, `audio ${source.ext}`);
      created.push(sourcePath);
      if (source.ext === ext) {
        await this._move(sourcePath, finalPath);
      } else {
        this._requireFfmpeg();
        const mixed = path.join(tempDir, `${info.id}.audio.${ext}`);
        created.push(mixed);
        await this._extractAudio(
          sourcePath,
          mixed,
          ext,
          this.options.audioQuality,
          metadata,
        );
        await this._move(mixed, finalPath);
      }
    } else if (selection.progressive) {
      const source = selection.progressive;
      const sourcePath = path.join(tempDir, `${info.id}.f${source.itag}.${source.ext}`);
      await this._downloadSource(
        source,
        sourcePath,
        `video+audio ${formatResolution(source)}`,
      );
      created.push(sourcePath);
      if (source.ext === finalPath.slice(finalPath.lastIndexOf(".") + 1).toLowerCase()) {
        await this._move(sourcePath, finalPath);
      } else {
        try {
          const mixed = path.join(tempDir, `${info.id}.merged.${ext}`);
          created.push(mixed);
          await this._remux(sourcePath, mixed, metadata);
          await this._move(mixed, finalPath);
        } catch (error) {
          if (!(error instanceof MediaError)) throw error;
          const fallback = replaceExtension(finalPath, source.ext);
          this._warn(
            `  ! No se pudo cambiar el contenedor (${error.message}). ` +
              `Se guarda como ${path.basename(fallback)}`,
          );
          await this._move(sourcePath, fallback);
          actualFinal = fallback;
        }
      }
    } else if (selection.video && selection.audio) {
      const videoPath = path.join(
        tempDir,
        `${info.id}.f${selection.video.itag}.${selection.video.ext}`,
      );
      const audioPath = path.join(
        tempDir,
        `${info.id}.f${selection.audio.itag}.${selection.audio.ext}`,
      );
      await this._downloadSources([
        [
          selection.video,
          videoPath,
          `video ${formatResolution(selection.video)}`,
        ],
        [selection.audio, audioPath, `audio ${selection.audio.ext}`],
      ]);
      created.push(videoPath, audioPath);

      try {
        const mixed = path.join(tempDir, `${info.id}.merged.${ext}`);
        created.push(mixed);
        await this._merge(videoPath, audioPath, mixed, metadata);
        await this._move(mixed, finalPath);
      } catch (error) {
        if (!(error instanceof MediaError) || ext !== "mp4") throw error;
        const fallback = replaceExtension(finalPath, "mkv");
        const mixedMkv = path.join(tempDir, `${info.id}.merged.mkv`);
        created.push(mixedMkv);
        this._warn(
          `  ! Falló el merge en MP4 (${error.message}). ` +
            "Reintentando en MKV...",
        );
        await this._merge(videoPath, audioPath, mixedMkv, metadata);
        await this._move(mixedMkv, fallback);
        actualFinal = fallback;
      }
    } else if (selection.video) {
      const source = selection.video;
      const sourcePath = path.join(tempDir, `${info.id}.f${source.itag}.${source.ext}`);
      await this._downloadSource(
        source,
        sourcePath,
        `video ${formatResolution(source)}`,
      );
      created.push(sourcePath);
      await this._move(sourcePath, finalPath);
    } else if (selection.audio) {
      const source = selection.audio;
      const sourcePath = path.join(tempDir, `${info.id}.f${source.itag}.${source.ext}`);
      await this._downloadSource(source, sourcePath, `audio ${source.ext}`);
      created.push(sourcePath);
      await this._move(sourcePath, finalPath);
    } else {
      throw new ExtractionError("La selección de formato quedó vacía.");
    }

    const paths = [actualFinal];
    if (this.options.writeSubs) {
      paths.push(...(await this._downloadSubtitles(info, actualFinal)));
    }

    if (!this.options.keepFiles) {
      for (const filePath of created) await this._safeUnlink(filePath);
      await fsp.rmdir(tempDir).catch(() => {});
    }

    await this._archiveAdd(info.id);

    let size = 0;
    try {
      size = (await fsp.stat(actualFinal)).size;
    } catch {
      size = 0;
    }
    this._log(`  ✓ ${path.basename(actualFinal)} (${humanBytes(size)})`);
    return makeResult(job, "ok", { paths, info });
  }

  // -------------------------------------------------------------- helpers
  _select(info) {
    let audioPref;
    if (this.options.audioOnly) {
      audioPref =
        { m4a: "m4a", mp3: "m4a", opus: "webm" }[
          this.options.audioFormat
        ] || null;
    } else {
      audioPref = this.options.mergeOutputFormat === "mp4" ? "m4a" : null;
    }

    return selectFormat(info.formats, this.options.formatSpec, {
      audioOnly: this.options.audioOnly,
      mergeExt: this.options.mergeOutputFormat,
      audioExtPref: audioPref,
    });
  }

  _targetExt(selection) {
    if (this.options.audioOnly) {
      const source = selection.audio || selection.progressive;
      if (!source) throw new ExtractionError("No hay audio disponible.");
      if (this.options.audioFormat === "best") return source.ext;
      if (this.options.audioFormat === "m4a" && source.ext === "m4a") return "m4a";
      if (this.options.audioFormat === "opus" && source.ext === "webm") return "opus";
      return this.options.audioFormat;
    }

    if (selection.progressive) {
      if (
        selection.progressive.ext === "webm" &&
        this.options.mergeOutputFormat === "mp4"
      ) {
        return "mp4";
      }
      return selection.progressive.ext;
    }
    if (selection.video && selection.audio) {
      return this.options.mergeOutputFormat;
    }
    if (selection.video) return selection.video.ext;
    if (selection.audio) return selection.audio.ext;
    throw new ExtractionError("No se pudo determinar la extensión de salida.");
  }

  _buildPath(info, job, selection) {
    const primary = selection.progressive || selection.video || selection.audio;
    const fields = {
      id: info.id,
      title: info.title,
      uploader: info.author,
      channel: info.author,
      channel_id: info.channel_id,
      duration: info.length_seconds,
      duration_string: humanDuration(info.length_seconds),
      upload_date: info.upload_date,
      view_count: info.view_count,
      playlist_id: job.playlist_id || "",
      playlist_title: job.playlist_title || "",
      playlist_index: job.playlist_index || "",
      epoch: Math.floor(Date.now() / 1000),
      ext: this._targetExt(selection),
      resolution: primary
        ? formatResolution(primary)
        : "",
      height: primary ? primary.height || "" : "",
      width: primary ? primary.width || "" : "",
      fps: primary ? primary.fps || "" : "",
      format_id: primary ? primary.itag : "",
    };
    return buildOutputPath(
      this.options.outputTemplate,
      fields,
      this.options.paths,
      { restrict: this.options.restrictFilenames },
    );
  }

  async _downloadSources(sources) {
    if (sources.length === 1) {
      await this._downloadSource(...sources[0]);
      return;
    }
    const results = await Promise.allSettled(
      sources.map((source) => this._downloadSource(...source)),
    );
    const failure = results.find((result) => result.status === "rejected");
    if (failure) throw failure.reason;
  }

  async _downloadSource(format, destination, label) {
    const printer = new ProgressPrinter(label, {
      quiet: this.options.quiet,
      enabled: !this.options.noProgress,
    });
    try {
      await this.http.streamDownload(format.url, destination, {
        expectedSize: format.filesize,
        progress: (done, total) => printer.update(done, total),
        headers: {
          "User-Agent": DEFAULT_USER_AGENT,
          Referer: "https://www.youtube.com/",
        },
        connections: this.options.connections,
      });
    } finally {
      printer.finish();
    }
  }

  async _downloadSubtitles(info, finalPath) {
    const tracks = selectTracks(
      info.subtitles,
      this.options.subLangs,
      this.options.writeAutoSubs,
      info.default_audio_language,
    );
    if (tracks.length === 0) {
      this._warn("  ! No hay subtítulos que coincidan con el idioma pedido.");
      return [];
    }

    const base = finalPath.slice(0, finalPath.length - path.extname(finalPath).length);
    const downloaded = [];
    for (const track of tracks) {
      let subtitle;
      try {
        subtitle = await downloadSubtitle(
          track,
          this.http,
          base,
          this.options.subFormat,
          { force: this.options.forceOverwrites },
        );
      } catch (error) {
        if (!(error instanceof YtPremiunVipError)) throw error;
        this._warn(
          `  ! No se pudo descargar el subtítulo ` +
            `${track.language_code}: ${error.message}`,
        );
        continue;
      }
      if (subtitle === null) {
        this._warn(
          `  ! El subtítulo ${track.language_code} llegó vacío; se omite.`,
        );
        continue;
      }
      downloaded.push(subtitle);
      this._log(
        `  ✓ subtítulos ${track.language_code}: ${path.basename(subtitle)}`,
      );
    }
    return downloaded;
  }

  _metadata(info, job) {
    const metadata = {
      title: info.title,
      artist: info.author,
      date: info.upload_date,
      comment: info.webpage_url,
    };
    if (job.playlist_title) metadata.album = job.playlist_title;
    return metadata;
  }

  async _move(source, destination) {
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    try {
      await fsp.rename(source, destination);
      return;
    } catch {
      // Windows no siempre reemplaza un archivo existente con rename.
    }
    await fsp.rm(destination, { force: true });
    try {
      await fsp.rename(source, destination);
    } catch {
      await fsp.copyFile(source, destination);
      await this._safeUnlink(source);
    }
  }

  async _safeUnlink(filePath) {
    try {
      await fsp.unlink(filePath);
    } catch {
      // El temporal ya no existe.
    }
  }

  _requireFfmpeg() {
    require("./media").findFfmpeg();
  }

  async _merge(video, audio, output, metadata) {
    return require("./media").merge(video, audio, output, metadata);
  }

  async _remux(source, output, metadata) {
    return require("./media").remux(source, output, metadata);
  }

  async _extractAudio(source, output, format, quality, metadata) {
    return require("./media").extractAudio(
      source,
      output,
      format,
      quality,
      metadata,
    );
  }

  _loadArchive() {
    if (!this.options.archive) return new Set();
    const filePath = String(this.options.archive);
    if (!fs.existsSync(filePath)) return new Set();
    const identifiers = new Set();
    const text = fs.readFileSync(filePath, "utf8");
    for (let line of text.split(/\r?\n/)) {
      line = line.trim();
      if (!line || line.startsWith("#")) continue;
      identifiers.add(line.split(/\s+/)[0]);
    }
    return identifiers;
  }

  _archiveAdd(videoId) {
    if (!this.options.archive) return Promise.resolve();
    this._archiveChain = this._archiveChain.then(async () => {
      if (this._archive.has(videoId)) return;
      const filePath = String(this.options.archive);
      await fsp.mkdir(path.dirname(filePath), { recursive: true });
      await fsp.appendFile(filePath, `${videoId}\n`, "utf8");
      this._archive.add(videoId);
    });
    return this._archiveChain;
  }

  _log(message) {
    if (!this.options.quiet) process.stdout.write(`${message}\n`);
  }

  _warn(message) {
    process.stderr.write(`${message}\n`);
  }
}

module.exports = {
  Downloader,
  defaultOptions,
  makeJob,
  makeResult,
  replaceExtension,
};
