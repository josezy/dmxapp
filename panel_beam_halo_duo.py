#!/usr/bin/env python3
"""Local web panel for the LED 60W Beam+Halo duo (A001 + A031).

Tk on this venv hangs at `import tkinter`, so the UI is a page on localhost.
"""

from __future__ import annotations

import html
import json
import queue
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

import beam_halo_duo as beam  # noqa: E402
import dmx  # noqa: E402

HOST = "127.0.0.1"
PORT = 8765

SHOW = beam.load_show()
GROUPS = SHOW["groups"]
KNOWN_SCENES = set(SHOW["scene_names"])


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
        self.line = "abriendo uDMX…"
        self.scene: str | None = None

    def submit(self, job: tuple) -> None:
        kind = job[0]
        if kind in ("play", "blackout"):
            self.last_scene = job
        self.stop.set()
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break
        self.jobs.put(job)

    def play(self, name: str) -> None:
        self.submit(("play", name))

    def blackout(self) -> None:
        self.submit(("blackout",))

    def reconnect(self) -> None:
        self.submit(("reconnect",))

    def shutdown(self) -> None:
        self.submit(("quit",))

    def _emit(self, text: str, scene: str | None = None) -> None:
        self.line = text
        if scene is not None:
            self.scene = scene
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
        return self._try_open("A001 + A031 · uDMX reconectado")

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
            if kind == "blackout":
                beam.blackout_on(self.dev)
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
        if not beam.keepalive(self.dev) or dmx.usb_is_dead():
            self._reconnect_and_restore("uDMX perdido")

    def snapshot(self) -> dict:
        h = dmx.usb_health()
        err = h.get("last_error") or ""
        tail = f"  ·  {err}" if h["streak"] and err else ""
        return {
            "line": self.line,
            "scene": self.scene,
            "usb": f"usb  ok {h['ok']}  fail {h['fail']}  racha {h['streak']}  saltos {h['skipped']}{tail}",
        }

    def run(self) -> None:
        self._try_open("A001 + A031 · 30CH · uDMX listo")
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
                            beam.blackout_on(self.dev)
                    except SystemExit:
                        pass
                    self._emit("blackout", "blackout")
                    return
                if kind == "reconnect":
                    self._reconnect_and_restore("reconectando uDMX")
                    continue
                if kind in ("blackout", "play"):
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
                    beam.blackout_on(self.dev)
                    self._emit("blackout", "blackout")
                    continue
                if kind == "play":
                    name = job[1]
                    _path, seq = beam.load_sequence(name)
                    self._emit(f"play {name}", name)
                    stats = beam.run_sequence(self.dev, seq, stop=self.stop)
                    if stats.get("usb_dead"):
                        err = dmx.usb_health().get("last_error") or "overflow/timeout"
                        self._reconnect_and_restore(f"uDMX saturado ({err})")
            except SystemExit as exc:
                self._reconnect_and_restore(f"uDMX: {exc}")
            except Exception as exc:
                self._emit(f"error: {exc}")


def page_html() -> str:
    payload = json.dumps(
        {"subtitle": SHOW.get("subtitle") or "", "groups": GROUPS},
        ensure_ascii=False,
    )
    subtitle = html.escape(SHOW.get("subtitle") or "BEAM 60W · A001 izq + A031 der · 30CH")
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Deo Volente · BEAM duo</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    margin: 0; font-family: -apple-system, Helvetica, sans-serif;
    background: #1a1a1a; color: #ececec;
  }}
  header {{ padding: 16px 18px 8px; display: flex; justify-content: space-between; gap: 12px; }}
  .muted {{ color: #8a8a8a; font-size: 13px; }}
  .bar {{ display: flex; gap: 10px; padding: 8px 18px 12px; }}
  .bar button {{ flex: 1; }}
  #line {{ padding: 0 18px 12px; font-size: 15px; }}
  section {{
    margin: 8px 14px; padding: 10px; border: 1px solid #333; border-radius: 8px;
  }}
  section h2 {{ margin: 0 0 8px; font-size: 13px; color: #8a8a8a; font-weight: 500; }}
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
  button {{
    font: 14px/1.2 Helvetica, sans-serif; padding: 14px 10px; cursor: pointer;
    border-radius: 6px; border: 1px solid #6e6e6e; background: #d8d8d8; color: #111;
  }}
  button:hover {{ background: #e6e6e6; }}
  button.active {{ background: #f0f0f0; font-weight: 700; border-color: #fff; }}
  #blackout {{ background: #8b1a1a; color: #fff; border-color: #5a1010; font-weight: 700; font-size: 16px; }}
  #blackout.active {{ background: #b42222; }}
  @media (max-width: 720px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
</head>
<body>
<header>
  <div class="muted">{subtitle}</div>
  <div class="muted" id="usb">usb —</div>
</header>
<div class="bar">
  <button id="blackout" type="button">BLACKOUT</button>
  <button id="reconnect" type="button">Reconectar</button>
</div>
<div id="line">abriendo…</div>
<div id="groups"></div>
<script>
const SHOW = {payload};
const GROUPS = SHOW.groups;
const groupsEl = document.getElementById("groups");
const lineEl = document.getElementById("line");
const usbEl = document.getElementById("usb");
let active = null;

function mark(name) {{
  active = name;
  document.querySelectorAll("button[data-name]").forEach((b) => {{
    b.classList.toggle("active", b.dataset.name === name);
  }});
  const bo = document.getElementById("blackout");
  bo.classList.toggle("active", name === "blackout");
}}

async function post(path, body) {{
  await fetch(path, {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(body || {{}}),
  }});
}}

GROUPS.forEach((group) => {{
  const sec = document.createElement("section");
  const h = document.createElement("h2");
  h.textContent = group.title;
  const grid = document.createElement("div");
  grid.className = "grid";
  group.scenes.forEach((scene) => {{
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = scene.label;
    b.dataset.name = scene.name;
    b.addEventListener("click", () => {{
      mark(scene.name);
      post("/api/play", {{ name: scene.name }});
    }});
    grid.appendChild(b);
  }});
  sec.appendChild(h);
  sec.appendChild(grid);
  groupsEl.appendChild(sec);
}});

document.getElementById("blackout").addEventListener("click", () => {{
  mark("blackout");
  post("/api/blackout");
}});
document.getElementById("reconnect").addEventListener("click", () => post("/api/reconnect"));

async function poll() {{
  try {{
    const r = await fetch("/api/status");
    const s = await r.json();
    lineEl.textContent = s.line || "";
    usbEl.textContent = s.usb || "";
    if (s.scene) mark(s.scene);
  }} catch (e) {{
    lineEl.textContent = "panel desconectado";
  }}
}}
poll();
setInterval(poll, 400);
</script>
</body>
</html>
"""


def make_handler(worker: DmxWorker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: dict) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self._send(code, raw, "application/json; charset=utf-8")

        def _read_json(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, page_html().encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/status":
                self._json(200, worker.snapshot())
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/play":
                name = str(self._read_json().get("name") or "")
                if name not in KNOWN_SCENES:
                    self._json(400, {"error": "unknown look"})
                    return
                worker.play(name)
                self._json(200, {"ok": True, "play": name})
                return
            if path == "/api/blackout":
                worker.blackout()
                self._json(200, {"ok": True})
                return
            if path == "/api/reconnect":
                worker.reconnect()
                self._json(200, {"ok": True})
                return
            self._json(404, {"error": "not found"})

    return Handler


def main() -> None:
    print("BEAM duo panel (web, no Tk)", flush=True)
    worker = DmxWorker(queue.Queue())
    worker.start()
    httpd = ThreadingHTTPServer((HOST, PORT), make_handler(worker))
    httpd.allow_reuse_address = True
    url = f"http://{HOST}:{PORT}/"
    print(f"Abierto en {url}", flush=True)
    print("Ctrl+C → blackout y salir", flush=True)
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nblackout…", flush=True)
    finally:
        worker.shutdown()
        worker.join(timeout=1.5)
        httpd.server_close()


if __name__ == "__main__":
    main()
