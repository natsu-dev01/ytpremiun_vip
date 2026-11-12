/** Barra de progreso simple para descargas. */

"use strict";

const {
  humanBytes,
  humanEta,
  humanSpeed,
  truncate,
} = require("./utils");

class ProgressPrinter {
  constructor(label, { quiet = false, enabled = true } = {}) {
    this.label = truncate(label, 44);
    this.quiet = quiet;
    this.enabled = enabled && !quiet;
    this._lastTime = 0;
    this._lastDone = 0;
    this._speed = 0;
    this._lastPrintedPct = -1;
    this._lastRender = 0;
    this._started = false;
    this._finished = false;
    this._isTty = Boolean(process.stdout.isTTY);
  }

  update(done, total) {
    if (!this.enabled || this._finished) return;

    const now = Date.now();
    if (this._lastTime) {
      const elapsed = (now - this._lastTime) / 1000;
      if (elapsed > 0) {
        const instant = (done - this._lastDone) / elapsed;
        this._speed = this._speed
          ? this._speed * 0.75 + instant * 0.25
          : instant;
      }
    }
    this._lastTime = now;
    this._lastDone = done;

    if (!this._started) {
      this._started = true;
      if (!this._isTty) {
        process.stdout.write(`  ${this.label} ...\n`);
      }
    }

    const finished = total !== null && total !== undefined && done >= total;
    if (this._isTty && !finished && now - this._lastRender < 100) return;
    this._lastRender = now;

    if (total) {
      const pct = Math.min(100, (done * 100) / total);
      const eta = this._speed > 0 ? (total - done) / this._speed : null;
      if (this._isTty) {
        const line =
          `  ${this.label} ${pct.toFixed(1).padStart(5)}% ` +
          `${humanBytes(done)}/${humanBytes(total)} ` +
          `${humanSpeed(this._speed)} ETA ${humanEta(eta)}`;
        const width = Math.max(20, (process.stdout.columns || 100) - 1);
        process.stdout.write(`\r${line.slice(0, width).padEnd(width)}`);
      } else {
        const bucket = Math.floor(pct / 20) * 20;
        if (bucket > this._lastPrintedPct) {
          this._lastPrintedPct = bucket;
          process.stdout.write(`  ${this.label}: ${bucket}%\n`);
        }
      }
    } else if (this._isTty) {
      const line = `  ${this.label} ${humanBytes(done)} ${humanSpeed(this._speed)}`;
      const width = Math.max(20, (process.stdout.columns || 100) - 1);
      process.stdout.write(`\r${line.slice(0, width).padEnd(width)}`);
    }
  }

  finish() {
    if (!this.enabled || this._finished) return;
    this._finished = true;
    if (this._isTty && this._started) process.stdout.write("\n");
  }
}

module.exports = { ProgressPrinter };
