#!/usr/bin/env python3
"""Two LPC008 PARs: A001 + A008. Complementary colors and opposite phase."""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

import dmx  # noqa: E402
import lpc008_duo as duo  # noqa: E402

BG = "#1a1a1a"
FG = "#ececec"
MUTED = "#8a8a8a"
BLACKOUT_BG = "#8b1a1a"
BLACKOUT_ACTIVE = "#b42222"

# 4x4 pad, left→right, top→bottom. (kind, scene file, label)
SCENES: list[tuple[str, str, str]] = [
    ("play", "breathe-calida", "Standby"),
    ("play", "breathe-fria", "Intro Hijomio"),
    ("play", "random-medio", "Falló / Siempre"),
    ("play", "random-rapido", "Desaparecidos / Caer / Fango"),
    ("play", "relampago-blanco", "Audio Biphospital"),
    ("play", "cancer-dolor", "Cáncer / Dolor"),
    ("play", "breathe-cancer", "Audio Viejitobucle"),
    ("play", "ecos", "Ecos"),
    ("play", "strobe-secundario-rapido", "verde/magenta rápido"),
    ("look", "deo-cian", "Deo"),
    ("look", "deo-hielo", "Hielo"),
    ("play", "sonido-deo", "Sonido"),
    ("play", "ekg", "EKG"),
    ("play", "flicker-dolor", "Flicker"),
    ("play", "fade-ultima", "Fade última"),
    ("play", "relampago-tormenta", "Tormenta"),
]

PAD_BG = "#d8d8d8"
PAD_ACTIVE = "#f0f0f0"
PAD_FG = "#111111"


class DmxWorker(threading.Thread):
    HEARTBEAT_S = 1.0

    def __init__(self, status: queue.Queue):
        super().__init__(daemon=True)
        self.status = status
        self.jobs: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.dev = None
        self.last_scene: tuple | None = None
        self._next_recover_at = 0.0

    def submit(self, job: tuple) -> None:
        kind = job[0]
        if kind in ("look", "play", "blackout"):
            self.last_scene = job
        self.stop.set()
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break
        self.jobs.put(job)

    def look(self, name: str) -> None:
        self.submit(("look", name))

    def play(self, name: str) -> None:
        self.submit(("play", name))

    def blackout(self) -> None:
        self.submit(("blackout",))

    def reconnect(self) -> None:
        self.submit(("reconnect",))

    def shutdown(self) -> None:
        self.submit(("quit",))

    def _emit(self, text: str, scene: str | None = None) -> None:
        self.status.put((text, scene))

    def _try_open(self, ok_msg: str) -> bool:
        try:
            self.dev = dmx.open_udmx()
        except SystemExit as exc:
            self.dev = None
            self._emit(f"uDMX: {exc}")
            return False
        self._emit(ok_msg)
        return True

    def _reconnect(self) -> bool:
        dmx.close_udmx(self.dev)
        self.dev = None
        return self._try_open("A001 + A008 · uDMX reconectado")

    def _restore_last(self) -> None:
        scene = self.last_scene
        if scene is None or self.dev is None:
            return
        if not self.jobs.empty():
            return
        kind = scene[0]
        if kind == "play":
            self.jobs.put(scene)
            return
        try:
            if kind == "look":
                name = scene[1]
                duo.write_look(self.dev, duo.load_look(name))
                self._emit(f"look {name} · restaurado", name)
            elif kind == "blackout":
                duo.blackout_on(self.dev)
                self._emit("blackout", "blackout")
        except SystemExit as exc:
            self.dev = None
            self._emit(f"uDMX: {exc}")

    def _reconnect_and_restore(self, reason: str) -> None:
        now = time.perf_counter()
        wait = self._next_recover_at - now
        if wait > 0 and self.stop.wait(wait):
            return
        self._emit(f"{reason} · reconectando…")
        ok = self._reconnect()
        self._next_recover_at = time.perf_counter() + self.HEARTBEAT_S
        if not ok:
            return
        self._restore_last()

    def _heartbeat(self) -> None:
        if self.dev is None or not dmx.udmx_handle_ok(self.dev):
            self._reconnect_and_restore("uDMX perdido")
            return
        scene = self.last_scene
        if scene is None:
            return
        if scene[0] == "play":
            if self.jobs.empty():
                self.jobs.put(scene)
            return
        if not duo.keepalive(self.dev) or dmx.usb_is_dead():
            self._reconnect_and_restore("uDMX perdido")

    def run(self) -> None:
        self._try_open("A001 + A008 · uDMX listo")
        while True:
            try:
                job = self.jobs.get(timeout=self.HEARTBEAT_S)
            except queue.Empty:
                self._heartbeat()
                continue
            self.stop.clear()
            kind = job[0]
            try:
                if kind == "quit":
                    try:
                        if self.dev is not None:
                            duo.blackout_on(self.dev)
                    except SystemExit:
                        pass
                    self._emit("blackout", "blackout")
                    return
                if kind == "reconnect":
                    self._reconnect_and_restore("reconectando uDMX")
                    continue
                if kind in ("blackout", "look", "play"):
                    stale = (
                        self.dev is None
                        or dmx.usb_health()["streak"] >= 5
                        or not dmx.udmx_handle_ok(self.dev)
                    )
                    if stale:
                        self._reconnect()
                    if self.dev is None:
                        self._emit("sin uDMX · reintento en 1 s")
                        continue
                if kind == "blackout":
                    duo.blackout_on(self.dev)
                    self._emit("blackout", "blackout")
                    continue
                if kind == "look":
                    name = job[1]
                    duo.write_look(self.dev, duo.load_look(name))
                    self._emit(f"look {name}", name)
                    continue
                if kind == "play":
                    name = job[1]
                    _path, seq = duo.load_sequence(name)
                    self._emit(f"play {name}", name)
                    stats = duo.run_sequence(self.dev, seq, stop=self.stop)
                    if stats.get("usb_dead"):
                        err = dmx.usb_health().get("last_error") or "overflow/timeout"
                        self._reconnect_and_restore(f"uDMX saturado ({err})")
            except SystemExit as exc:
                self._reconnect_and_restore(f"uDMX: {exc}")
            except Exception as exc:
                self._emit(f"error: {exc}")


class Panel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Deo Volente · LPC008 duo")
        self.configure(bg=BG)
        self.minsize(720, 720)
        self.geometry("900x980")
        self.status_q: queue.Queue = queue.Queue()
        self.worker = DmxWorker(self.status_q)
        self.buttons: dict[str, ttk.Button] = {}
        self.active: str | None = None
        self._style()
        self._build()
        self.worker.start()
        self.after(80, self._pump_status)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG)
        style.configure(
            "Scene.TButton",
            background="#d8d8d8",
            foreground="#111111",
            bordercolor="#6e6e6e",
            lightcolor="#ececec",
            darkcolor="#9a9a9a",
            focusthickness=0,
            focuscolor=BG,
            padding=(8, 8),
            font=("Helvetica", 11),
        )
        style.map(
            "Scene.TButton",
            background=[("pressed", "#c4c4c4"), ("active", "#e6e6e6")],
            foreground=[("pressed", "#111111"), ("active", "#111111")],
        )
        style.configure(
            "SceneActive.TButton",
            background="#f0f0f0",
            foreground="#111111",
            bordercolor="#ffffff",
            lightcolor="#ffffff",
            darkcolor="#b0b0b0",
            focusthickness=0,
            focuscolor=BG,
            padding=(8, 8),
            font=("Helvetica", 11, "bold"),
        )
        style.map(
            "SceneActive.TButton",
            background=[("pressed", "#e0e0e0"), ("active", "#f7f7f7")],
            foreground=[("pressed", "#111111"), ("active", "#111111")],
        )
        style.configure(
            "Blackout.TButton",
            background=BLACKOUT_BG,
            foreground="#ffffff",
            bordercolor="#5a1010",
            lightcolor="#a32222",
            darkcolor="#5a1010",
            focusthickness=0,
            focuscolor=BG,
            padding=(10, 10),
            font=("Helvetica", 14, "bold"),
        )
        style.map(
            "Blackout.TButton",
            background=[("pressed", BLACKOUT_ACTIVE), ("active", BLACKOUT_ACTIVE)],
            foreground=[("pressed", "#ffffff"), ("active", "#ffffff")],
        )
        style.configure(
            "BlackoutActive.TButton",
            background=BLACKOUT_ACTIVE,
            foreground="#ffffff",
            bordercolor="#ffffff",
            lightcolor="#d44",
            darkcolor="#5a1010",
            focusthickness=0,
            focuscolor=BG,
            padding=(10, 10),
            font=("Helvetica", 14, "bold"),
        )
        style.map(
            "BlackoutActive.TButton",
            background=[("pressed", BLACKOUT_BG), ("active", BLACKOUT_ACTIVE)],
            foreground=[("pressed", "#ffffff"), ("active", "#ffffff")],
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#3a3a3a",
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=FG,
            darkcolor="#2a2a2a",
            lightcolor="#4a4a4a",
        )
        style.configure(
            "Reconnect.TButton",
            background="#d8d8d8",
            foreground="#111111",
            bordercolor="#6e6e6e",
            lightcolor="#ececec",
            darkcolor="#9a9a9a",
            focusthickness=0,
            focuscolor=BG,
            padding=(10, 10),
            font=("Helvetica", 12, "bold"),
        )
        style.map(
            "Reconnect.TButton",
            background=[("pressed", "#c4c4c4"), ("active", "#e6e6e6")],
            foreground=[("pressed", "#111111"), ("active", "#111111")],
        )

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(
            header,
            text="LPC008  ·  A001 + A008  ·  nunca el mismo color",
            bg=BG,
            fg=MUTED,
            font=("Helvetica", 11),
        ).pack(side="left")
        self.usb_var = tk.StringVar(value="usb  —")
        tk.Label(
            header,
            textvariable=self.usb_var,
            bg=BG,
            fg=MUTED,
            font=("Helvetica", 11),
            anchor="e",
        ).pack(side="right")

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=10, pady=(6, 4))
        blackout = ttk.Button(
            bar,
            text="BLACKOUT",
            command=self._blackout,
            style="Blackout.TButton",
            cursor="hand2",
        )
        blackout.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.buttons["blackout"] = blackout
        ttk.Button(
            bar,
            text="Reconectar",
            command=self._reconnect,
            style="Reconnect.TButton",
            cursor="hand2",
        ).pack(side="right", fill="x", expand=True, padx=(6, 0))

        self.status_var = tk.StringVar(value="abriendo uDMX…")
        tk.Label(
            self,
            textvariable=self.status_var,
            bg=BG,
            fg=FG,
            font=("Helvetica", 12),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 4))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        grid = tk.Frame(body, bg=BG)
        self._pad_grid = grid

        for i, (kind, name, label) in enumerate(SCENES):
            row, col = divmod(i, 4)
            btn = tk.Button(
                grid,
                text=label,
                wraplength=160,
                justify="center",
                font=("Helvetica", 13),
                bg=PAD_BG,
                fg=PAD_FG,
                activebackground="#e6e6e6",
                activeforeground=PAD_FG,
                bd=1,
                relief="raised",
                highlightthickness=1,
                highlightbackground="#6e6e6e",
                highlightcolor="#ffffff",
                cursor="hand2",
                command=lambda k=kind, n=name: self._fire(k, n),
            )
            btn.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            self.buttons[name] = btn
        for n in range(4):
            grid.rowconfigure(n, weight=1, uniform="pad")
            grid.columnconfigure(n, weight=1, uniform="pad")

        def _fit(_event=None) -> None:
            w = body.winfo_width()
            h = body.winfo_height()
            if w < 8 or h < 8:
                return
            side = min(w, h)
            grid.place(relx=0.5, rely=0.5, anchor="center", width=side, height=side)
            wrap = max(72, (side // 4) - 28)
            for name, btn in self.buttons.items():
                if name == "blackout":
                    continue
                btn.configure(wraplength=wrap)

        body.bind("<Configure>", _fit)

    def _fire(self, kind: str, name: str) -> None:
        self._mark(name)
        if kind == "look":
            self.worker.look(name)
        else:
            self.worker.play(name)

    def _blackout(self) -> None:
        self._mark("blackout")
        self.worker.blackout()

    def _reconnect(self) -> None:
        self.worker.reconnect()

    def _idle_pad(self, btn: tk.Button) -> None:
        btn.configure(
            bg=PAD_BG,
            font=("Helvetica", 13),
            highlightbackground="#6e6e6e",
            highlightthickness=1,
        )

    def _active_pad(self, btn: tk.Button) -> None:
        btn.configure(
            bg=PAD_ACTIVE,
            font=("Helvetica", 13, "bold"),
            highlightbackground="#ffffff",
            highlightthickness=2,
        )

    def _mark(self, name: str) -> None:
        if self.active and self.active in self.buttons:
            prev = self.buttons[self.active]
            if self.active == "blackout":
                prev.configure(style="Blackout.TButton")
            else:
                self._idle_pad(prev)
        self.active = name
        btn = self.buttons.get(name)
        if btn is None:
            return
        if name == "blackout":
            btn.configure(style="BlackoutActive.TButton")
        else:
            self._active_pad(btn)

    def _pump_status(self) -> None:
        try:
            while True:
                text, scene = self.status_q.get_nowait()
                self.status_var.set(text)
                if scene:
                    self._mark(scene)
        except queue.Empty:
            pass
        h = dmx.usb_health()
        err = h["last_error"]
        tail = f"  ·  {err}" if h["streak"] and err else ""
        self.usb_var.set(
            f"usb  ok {h['ok']}  fail {h['fail']}  racha {h['streak']}  saltos {h['skipped']}{tail}"
        )
        self.after(80, self._pump_status)

    def _close(self) -> None:
        self.worker.shutdown()
        self.worker.join(timeout=1.5)
        self.destroy()


def main() -> None:
    Panel().mainloop()


if __name__ == "__main__":
    main()
