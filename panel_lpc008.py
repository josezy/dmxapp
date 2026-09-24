#!/usr/bin/env python3
"""Live recall panel for the Big Dipper LPC008 PAR (A001 7ch)."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

import dmx  # noqa: E402
import lpc008_ctl as lpc  # noqa: E402

BG = "#1a1a1a"
FG = "#ececec"
MUTED = "#8a8a8a"
BLACKOUT_BG = "#8b1a1a"
BLACKOUT_ACTIVE = "#b42222"
COLS = 4

GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Camas",
        [
            ("look", "blanco", "blanco"),
            ("look", "tungsteno", "tungsteno"),
            ("look", "sangre", "sangre"),
            ("look", "acero", "acero"),
            ("look", "hueco", "hueco"),
            ("look", "fuego", "fuego"),
            ("look", "verde", "verde"),
            ("look", "azul", "azul"),
        ],
    ),
    (
        "Paleta fixture",
        [
            ("look", "paleta-verde", "macro verde"),
            ("look", "paleta-azul", "macro azul"),
        ],
    ),
    (
        "Programas",
        [
            ("look", "shade-lento", "shade lento"),
            ("look", "shade-rapido", "shade rápido"),
            ("look", "fade-lento", "fade lento"),
            ("look", "fade-rapido", "fade rápido"),
            ("look", "pulse-suave", "pulse suave"),
            ("look", "pulse-rapido", "pulse rápido"),
        ],
    ),
    (
        "Breathe",
        [
            ("play", "blanco-breathe", "blanco"),
            ("play", "tungsteno-breathe", "tungsteno"),
            ("play", "sangre-breathe", "sangre"),
            ("play", "hueco-breathe", "hueco"),
        ],
    ),
    (
        "Strobe 2 colores (script)",
        [
            ("play", "strobe-azul-morado", "azul-morado"),
            ("play", "strobe-rojo-azul", "rojo-azul"),
            ("play", "strobe-rojo-blanco", "rojo-blanco"),
            ("play", "strobe-rojo-azul-lento", "rojo-azul lento"),
        ],
    ),
    (
        "Fade / build",
        [
            ("play", "fade-calor", "fade calor"),
            ("play", "fade-frio", "fade frío"),
            ("play", "build-verso-coro", "verso → coro"),
        ],
    ),
]


class DmxWorker(threading.Thread):
    def __init__(self, status: queue.Queue):
        super().__init__(daemon=True)
        self.status = status
        self.jobs: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.dev = None

    def submit(self, job: tuple) -> None:
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

    def _reconnect(self) -> None:
        self._emit("reconectando uDMX…")
        dmx.close_udmx(self.dev)
        self.dev = None
        self._try_open("LPC008 A001 · uDMX reconectado")

    def run(self) -> None:
        self._try_open("LPC008 A001 · uDMX listo")
        while True:
            job = self.jobs.get()
            self.stop.clear()
            kind = job[0]
            try:
                if kind == "quit":
                    if self.dev is not None:
                        lpc.blackout_on(self.dev)
                    self._emit("blackout", "blackout")
                    return
                if kind == "reconnect":
                    self._reconnect()
                    continue
                if self.dev is None:
                    self._emit("sin uDMX · pulsa Reconectar (QLC+ cerrado)")
                    continue
                if kind == "blackout":
                    lpc.blackout_on(self.dev)
                    self._emit("blackout", "blackout")
                    continue
                if kind == "look":
                    name = job[1]
                    lpc.write_look(self.dev, lpc.load_look(name))
                    self._emit(f"look {name}", name)
                    continue
                if kind == "play":
                    name = job[1]
                    _path, seq = lpc.load_sequence(name)
                    self._emit(f"play {name}", name)
                    lpc.run_sequence(self.dev, seq, loop=True, stop=self.stop)
            except SystemExit as exc:
                self.dev = None
                self._emit(f"uDMX: {exc}")
            except Exception as exc:
                self._emit(f"error: {exc}")


class Panel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Deo Volente · LPC008")
        self.configure(bg=BG)
        self.minsize(560, 740)
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
            padding=(10, 12),
            font=("Helvetica", 12),
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
            padding=(10, 12),
            font=("Helvetica", 12, "bold"),
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
            padding=(12, 16),
            font=("Helvetica", 16, "bold"),
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
            padding=(12, 16),
            font=("Helvetica", 16, "bold"),
        )
        style.map(
            "BlackoutActive.TButton",
            background=[("pressed", BLACKOUT_BG), ("active", BLACKOUT_ACTIVE)],
            foreground=[("pressed", "#ffffff"), ("active", "#ffffff")],
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
            padding=(12, 16),
            font=("Helvetica", 14, "bold"),
        )
        style.map(
            "Reconnect.TButton",
            background=[("pressed", "#c4c4c4"), ("active", "#e6e6e6")],
            foreground=[("pressed", "#111111"), ("active", "#111111")],
        )

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}
        tk.Label(
            self,
            text="LPC008  ·  A001  ·  RGB  ·  ch5=0",
            bg=BG,
            fg=MUTED,
            font=("Helvetica", 11),
        ).pack(anchor="w", padx=12, pady=(12, 0))

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=12, pady=(8, 10))
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
        ).pack(fill="x", padx=14, pady=(0, 8))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 12))

        for title, scenes in GROUPS:
            box = tk.LabelFrame(
                body,
                text=f"  {title}  ",
                bg=BG,
                fg=MUTED,
                font=("Helvetica", 11),
                bd=1,
                relief="solid",
                highlightthickness=0,
                labelanchor="nw",
            )
            box.pack(fill="x", **pad)
            for i, (kind, name, label) in enumerate(scenes):
                btn = ttk.Button(
                    box,
                    text=label,
                    command=lambda k=kind, n=name: self._fire(k, n),
                    style="Scene.TButton",
                    cursor="hand2",
                )
                btn.grid(row=i // COLS, column=i % COLS, sticky="nsew", padx=4, pady=4)
                self.buttons[name] = btn
            for col in range(COLS):
                box.grid_columnconfigure(col, weight=1)

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

    def _mark(self, name: str) -> None:
        if self.active and self.active in self.buttons:
            prev = self.buttons[self.active]
            prev.configure(
                style="Blackout.TButton" if self.active == "blackout" else "Scene.TButton"
            )
        self.active = name
        btn = self.buttons.get(name)
        if btn is None:
            return
        btn.configure(
            style="BlackoutActive.TButton" if name == "blackout" else "SceneActive.TButton"
        )

    def _pump_status(self) -> None:
        try:
            while True:
                text, scene = self.status_q.get_nowait()
                self.status_var.set(text)
                if scene:
                    self._mark(scene)
        except queue.Empty:
            pass
        self.after(80, self._pump_status)

    def _close(self) -> None:
        self.worker.shutdown()
        self.worker.join(timeout=1.5)
        self.destroy()


def main() -> None:
    Panel().mainloop()


if __name__ == "__main__":
    main()
