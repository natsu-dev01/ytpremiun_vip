"""Barra de progreso simple para descargas."""

from __future__ import annotations

import shutil
import sys
import threading
import time

from .utils import human_bytes, human_eta, human_speed, truncate


# Varios hilos (descargas de video+audio o varios trabajos a la vez) pueden
# escribir progreso al mismo tiempo. El candado evita líneas mezcladas.
_OUTPUT_LOCK = threading.Lock()


class ProgressPrinter:
    """Imprime porcentaje, velocidad y ETA en una sola línea."""

    def __init__(
        self,
        label: str,
        *,
        quiet: bool = False,
        enabled: bool = True,
    ) -> None:
        self.label = truncate(label, 44)
        self.quiet = quiet
        self.enabled = enabled and not quiet
        self._last_time = 0.0
        self._last_done = 0
        self._speed = 0.0
        self._last_printed_pct = -1
        self._last_render = 0.0
        self._started = False
        self._finished = False
        try:
            self._is_tty = sys.stdout.isatty()
        except Exception:
            self._is_tty = False

    def __call__(self, done: int, total: int | None) -> None:
        if not self.enabled or self._finished:
            return

        now = time.monotonic()
        if self._last_time:
            elapsed = now - self._last_time
            if elapsed > 0:
                instant = (done - self._last_done) / elapsed
                self._speed = instant if not self._speed else (self._speed * 0.75 + instant * 0.25)
        self._last_time = now
        self._last_done = done

        if not self._started:
            self._started = True
            if not self._is_tty:
                with _OUTPUT_LOCK:
                    print(f"  {self.label} ...", flush=True)

        # Redibujar la barra 10 veces por segundo es suficiente para que se vea
        # fluida y evita gastar CPU con descargas muy rápidas.
        finished = total is not None and done >= total
        if self._is_tty and not finished and now - self._last_render < 0.1:
            return
        self._last_render = now

        if total:
            pct = min(100.0, done * 100.0 / total)
            eta = (total - done) / self._speed if self._speed > 0 else None
            if self._is_tty:
                line = (
                    f"  {self.label} {pct:5.1f}% "
                    f"{human_bytes(done)}/{human_bytes(total)} "
                    f"{human_speed(self._speed)} ETA {human_eta(eta)}"
                )
                width = max(20, shutil.get_terminal_size((100, 20)).columns - 1)
                with _OUTPUT_LOCK:
                    print("\r" + line[:width].ljust(width), end="", flush=True)
            else:
                bucket = int(pct // 20) * 20
                if bucket > self._last_printed_pct:
                    self._last_printed_pct = bucket
                    with _OUTPUT_LOCK:
                        print(f"  {self.label}: {bucket}%", flush=True)
        elif self._is_tty:
            line = f"  {self.label} {human_bytes(done)} {human_speed(self._speed)}"
            width = max(20, shutil.get_terminal_size((100, 20)).columns - 1)
            with _OUTPUT_LOCK:
                print("\r" + line[:width].ljust(width), end="", flush=True)

    def finish(self) -> None:
        if not self.enabled or self._finished:
            return
        self._finished = True
        if self._is_tty and self._started:
            with _OUTPUT_LOCK:
                print()
