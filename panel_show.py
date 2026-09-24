#!/usr/bin/env python3
"""Unified show console: pick LPC008 + BEAM counts, then one look list.

http://127.0.0.1:8766/
Does not replace the older single-fixture panels.
"""

from __future__ import annotations

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

import dmx  # noqa: E402
from show_dispatch import ShowPlayer, blackout_buffer, load_catalog  # noqa: E402
from show_rig import RigError, build_rig  # noqa: E402

HOST = "127.0.0.1"
PORT = 8766
CATALOG = load_catalog()


class ShowWorker(threading.Thread):
    HEARTBEAT_S = 1.0

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.jobs: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.dev = None
        self.rig = build_rig(0, 0)
        self.player: ShowPlayer | None = None
        self.last_buf: list[int] = []
        self.last_pose: list[tuple[float, float]] = []
        self.last_scene: tuple | None = None
        self.line = "elige el rig"
        self.scene: str | None = None
        self.palette_id: str | None = None
        self.speed_id: str | None = None
        self._next_recover_at = 0.0

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

    def snapshot(self) -> dict:
        h = dmx.usb_health()
        err = h.get("last_error") or ""
        tail = f"  ·  {err}" if h["streak"] and err else ""
        return {
            "line": self.line,
            "scene": self.scene,
            "palette": self.palette_id,
            "speed": self.speed_id,
            "rig": self.rig,
            "usb": f"usb  ok {h['ok']}  fail {h['fail']}  racha {h['streak']}  saltos {h['skipped']}{tail}",
        }

    def run(self) -> None:
        self._try_open("uDMX listo")
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
                    self._blackout()
                    return
                if kind == "rig":
                    self.rig = job[1]
                    self.player = None
                    self.last_pose = []
                    self.scene = None
                    self._blackout()
                    labels = "  ".join(f["label"] for f in self.rig["fixtures"]) or "vacío"
                    self._emit(labels, None)
                    continue
                if kind == "blackout":
                    self.player = None
                    self._blackout()
                    self._emit("blackout", "blackout")
                    continue
                if kind == "reconnect":
                    self._reconnect_and_restore("reconectando uDMX")
                    continue
                if kind == "play":
                    self._play(job[1], job[2], job[3])
            except SystemExit as exc:
                self._reconnect_and_restore(f"uDMX: {exc}")
            except Exception as exc:
                self._emit(f"error: {exc}")

    def _emit(self, text: str, scene: str | None = None) -> None:
        self.line = text
        if scene is not None or scene == "blackout":
            self.scene = scene
        if scene is None and text:
            pass

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
        return self._try_open("uDMX reconectado")

    def _reconnect_and_restore(self, msg: str) -> None:
        self._emit(msg)
        now = time.perf_counter()
        if now < self._next_recover_at:
            return
        self._next_recover_at = now + 1.0
        if not self._reconnect():
            return
        scene = self.last_scene
        if scene and scene[0] == "play" and self.jobs.empty():
            self.jobs.put(scene)

    def _heartbeat(self) -> None:
        if self.dev is None or not self.last_buf:
            return
        if dmx.link_check_due() and not dmx.udmx_handle_ok(self.dev):
            dmx.mark_usb_dead("No such device")
            self._reconnect_and_restore("uDMX desconectado")
            return
        dmx.send_range_once(self.dev, 0, self.last_buf)

    def _blackout(self) -> None:
        self.last_buf = blackout_buffer(self.rig)
        if self.dev is not None and self.last_buf:
            try:
                dmx.send_range(self.dev, 0, self.last_buf)
            except SystemExit as exc:
                self._emit(f"uDMX: {exc}")

    def _play(self, name: str, palette_id: str, speed_id: str) -> None:
        look = CATALOG["looks"].get(name)
        palette = CATALOG["paletteById"].get(palette_id)
        if look is None or palette is None or speed_id not in CATALOG["speedById"]:
            self._emit("look, paleta o velocidad desconocida")
            return
        if self.rig["span"] <= 0:
            self._emit("elige al menos un fixture")
            return
        if self.dev is None and not self._try_open("uDMX listo"):
            self._emit("sin uDMX · reintento en 1 s")
            return
        scale = CATALOG["speedById"][speed_id]
        self.palette_id = palette_id
        self.speed_id = speed_id
        self.player = ShowPlayer(self.rig, look, palette, scale, self.last_pose)
        self.scene = name
        speed_label = next(row["label"] for row in CATALOG["speeds"] if row["id"] == speed_id)
        self._emit(f"{look['label']} · {palette['label']} · {speed_label}", name)
        fps = max(1.0, float(self.player.fps))
        step = 1.0 / fps
        t0 = time.perf_counter()
        n = 0
        fails = 0
        while not dmx.stopped(self.stop):
            n, halt = dmx.sync_frame(t0, n, step, self.stop)
            if halt:
                break
            if self.dev is None or (dmx.link_check_due() and not dmx.udmx_handle_ok(self.dev)):
                self._reconnect_and_restore("sin uDMX")
                return
            now = time.perf_counter()
            buf = self.player.frame(now, now - t0)
            if dmx.send_range_once(self.dev, 0, buf):
                self.last_buf = buf
                self.last_pose = list(self.player.last_pose)
            else:
                fails += 1
                if dmx.usb_is_dead():
                    self._reconnect_and_restore("uDMX saturado")
                    return
            n += 1


def _parse_rig(payload: dict) -> dict:
    order = str(payload.get("order") or "lpc_first")
    return build_rig(int(payload.get("nLpc", 0)), int(payload.get("nBeam", 0)), order)


PAGE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Deo Volente · show</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; font-family: -apple-system, Helvetica, sans-serif; background: #1a1a1a; color: #ececec; }
  header { padding: 16px 18px 8px; display: flex; justify-content: space-between; gap: 12px; align-items: center; }
  .muted { color: #8a8a8a; font-size: 13px; }
  .bar, .chips { display: flex; gap: 8px; padding: 8px 18px; flex-wrap: wrap; }
  .bar button { flex: 1; }
  #line, #map { padding: 0 18px 12px; font-size: 15px; }
  #map { color: #8a8a8a; font-size: 13px; }
  section { margin: 8px 14px; padding: 10px; border: 1px solid #333; border-radius: 8px; }
  section h2 { margin: 0 0 8px; font-size: 13px; color: #8a8a8a; font-weight: 500; }
  .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  button, .step button {
    font: 14px/1.2 Helvetica, sans-serif; padding: 14px 10px; cursor: pointer;
    border-radius: 6px; border: 1px solid #6e6e6e; background: #d8d8d8; color: #111;
  }
  button.small { padding: 8px 10px; font-size: 13px; }
  button:hover { background: #e6e6e6; }
  button.picked { background: #f0f0f0; font-weight: 700; border-color: #fff; }
  button.on {
    background: #fff; font-weight: 700; border-color: #111;
    box-shadow: 0 0 0 3px #f2c14e;
  }
  #blackout { background: #8b1a1a; color: #fff; border-color: #5a1010; font-weight: 700; font-size: 16px; }
  .home { max-width: 520px; margin: 24px auto; padding: 0 16px; }
  .row { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 14px 0; }
  .step { display: flex; align-items: center; gap: 8px; }
  .step strong { min-width: 1.5em; text-align: center; }
  .swatch { display: inline-block; width: 36px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
  @media (max-width: 720px) { .grid { grid-template-columns: repeat(2, 1fr); } }
</style>
</head>
<body>
<div id="home" class="home">
  <h1 style="font-size:18px;font-weight:600">Rig</h1>
  <p class="muted">LPC008 es el PAR de 7 canales. BEAM 60W es 30 canales. Las direcciones salen desde el canal 1.</p>
  <div class="row"><span>LPC008 · 7CH</span><div class="step"><button type="button" id="lpc-dec">−</button><strong id="n-lpc">0</strong><button type="button" id="lpc-inc">+</button></div></div>
  <div class="row"><span>BEAM 60W · 30CH</span><div class="step"><button type="button" id="beam-dec">−</button><strong id="n-beam">2</strong><button type="button" id="beam-inc">+</button></div></div>
  <div class="chips">
    <button type="button" class="small picked" id="order-lpc" data-order="lpc_first">PAR primero</button>
    <button type="button" class="small" id="order-beam" data-order="beam_first">BEAM primero</button>
  </div>
  <div id="map">—</div>
  <div class="bar"><button type="button" id="enter">Entrar al pad</button></div>
</div>
<div id="pad" hidden>
  <header>
    <div class="muted" id="subtitle">show</div>
    <button type="button" class="small" id="edit-rig">Rig</button>
  </header>
  <div class="muted" id="usb" style="padding:0 18px">usb —</div>
  <div class="bar">
    <button id="blackout" type="button">BLACKOUT</button>
    <button id="reconnect" type="button">Reconectar</button>
  </div>
  <div id="line">…</div>
  <div class="chips" id="palettes"></div>
  <div class="chips" id="speeds"></div>
  <div id="groups"></div>
</div>
<script>
const CATALOG = __CATALOG__;
const RIG_KEY = "deo.show.rig";
const TUNE_KEY = "deo.show.tune";
let rig = { nLpc: 0, nBeam: 2, order: "lpc_first" };
let tune = { palette: "blanco", speed: "medio" };
let active = null;

function loadStore() {
  try { rig = Object.assign(rig, JSON.parse(localStorage.getItem(RIG_KEY) || "{}")); } catch (e) {}
  try {
    const saved = JSON.parse(localStorage.getItem(TUNE_KEY) || "null");
    if (saved && saved.palette && saved.speed) tune = saved;
  } catch (e) {}
}
function saveStore() {
  localStorage.setItem(RIG_KEY, JSON.stringify(rig));
  localStorage.setItem(TUNE_KEY, JSON.stringify(tune));
}
async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "error");
  return data;
}
function paintHome() {
  document.getElementById("n-lpc").textContent = rig.nLpc;
  document.getElementById("n-beam").textContent = rig.nBeam;
  document.getElementById("order-lpc").classList.toggle("picked", rig.order !== "beam_first");
  document.getElementById("order-beam").classList.toggle("picked", rig.order === "beam_first");
}
async function refreshMap() {
  paintHome();
  try {
    const data = await post("/api/map", rig);
    const labels = data.rig.fixtures.map((f) => f.type + " " + f.label).join("   ");
    document.getElementById("map").textContent = labels || "ningún fixture";
  } catch (e) {
    document.getElementById("map").textContent = e.message;
  }
}
function showPad(on) {
  document.getElementById("home").hidden = on;
  document.getElementById("pad").hidden = !on;
}
function slotRgb(c) {
  const r = c.r | 0, g = c.g | 0, b = c.b | 0;
  if (r || g || b) return `rgb(${r},${g},${b})`;
  if (c.halo && (c.halo[0] || c.halo[1] || c.halo[2])) return `rgb(${c.halo[0]},${c.halo[1]},${c.halo[2]})`;
  if ((c.w | 0) > 0) return "rgb(255,255,255)";
  return "rgb(0,0,0)";
}
function swatch(p) {
  const cols = (p.colors && p.colors.length ? p.colors : [p.a, p.b]).map(slotRgb);
  const n = cols.length;
  const stops = cols.map((c, i) => `${c} ${(i / n) * 100}% ${((i + 1) / n) * 100}%`).join(",");
  return `<span class="swatch" style="background:linear-gradient(90deg,${stops})"></span>`;
}
function paintControls() {
  const lookId = active && active !== "blackout" ? active : null;
  document.querySelectorAll("#palettes button").forEach((b) => b.classList.toggle("on", b.dataset.id === tune.palette));
  document.querySelectorAll("#speeds button").forEach((b) => b.classList.toggle("on", b.dataset.id === tune.speed));
  document.querySelectorAll("button[data-look]").forEach((b) => b.classList.toggle("on", b.dataset.look === lookId));
}
function buildPad() {
  const pal = document.getElementById("palettes");
  const speeds = document.getElementById("speeds");
  pal.innerHTML = "";
  speeds.innerHTML = "";
  for (const p of CATALOG.palettes) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "small";
    b.dataset.id = p.id;
    b.innerHTML = swatch(p) + p.label;
    b.addEventListener("click", () => choosePalette(p.id));
    pal.appendChild(b);
  }
  for (const s of CATALOG.speeds) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "small";
    b.dataset.id = s.id;
    b.textContent = s.label;
    b.addEventListener("click", () => chooseSpeed(s.id));
    speeds.appendChild(b);
  }
  const groups = document.getElementById("groups");
  groups.innerHTML = "";
  for (const group of CATALOG.groups) {
    const sec = document.createElement("section");
    const h = document.createElement("h2");
    h.textContent = group.title;
    const grid = document.createElement("div");
    grid.className = "grid";
    for (const look of group.looks) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = look.label;
      b.dataset.look = look.id;
      b.addEventListener("click", () => play(look.id));
      grid.appendChild(b);
    }
    sec.appendChild(h);
    sec.appendChild(grid);
    groups.appendChild(sec);
  }
}
async function play(id) {
  active = id;
  saveStore();
  paintControls();
  await post("/api/play", { name: id, palette: tune.palette, speed: tune.speed });
}
async function choosePalette(id) {
  tune.palette = id;
  saveStore();
  paintControls();
  if (active && active !== "blackout") await play(active);
}
async function chooseSpeed(id) {
  tune.speed = id;
  saveStore();
  paintControls();
  if (active && active !== "blackout") await play(active);
}
function bump(key, delta) {
  rig[key] = Math.max(0, Math.min(8, rig[key] + delta));
  refreshMap();
}
document.getElementById("lpc-dec").onclick = () => bump("nLpc", -1);
document.getElementById("lpc-inc").onclick = () => bump("nLpc", 1);
document.getElementById("beam-dec").onclick = () => bump("nBeam", -1);
document.getElementById("beam-inc").onclick = () => bump("nBeam", 1);
document.getElementById("order-lpc").onclick = () => { rig.order = "lpc_first"; refreshMap(); };
document.getElementById("order-beam").onclick = () => { rig.order = "beam_first"; refreshMap(); };
document.getElementById("enter").onclick = async () => {
  const data = await post("/api/rig", rig);
  rig = { nLpc: data.rig.nLpc, nBeam: data.rig.nBeam, order: data.rig.order };
  saveStore();
  const labels = data.rig.fixtures.map((f) => f.label).join(" ");
  document.getElementById("subtitle").textContent = labels || "sin fixtures";
  showPad(true);
};
document.getElementById("edit-rig").onclick = () => { showPad(false); refreshMap(); };
document.getElementById("blackout").onclick = async () => {
  await post("/api/blackout");
};
document.getElementById("reconnect").onclick = () => post("/api/reconnect");
async function poll() {
  if (document.getElementById("pad").hidden) return;
  try {
    const s = await (await fetch("/api/status")).json();
    document.getElementById("line").textContent = s.line || "";
    document.getElementById("usb").textContent = s.usb || "";
    if (s.scene && s.scene !== "blackout" && s.scene !== active) {
      active = s.scene;
      paintControls();
    }
  } catch (e) {
    document.getElementById("line").textContent = "panel desconectado";
  }
}
loadStore();
buildPad();
paintControls();
refreshMap();
if (localStorage.getItem(RIG_KEY)) {
  post("/api/rig", rig).then((data) => {
    const labels = data.rig.fixtures.map((f) => f.label).join(" ");
    document.getElementById("subtitle").textContent = labels || "sin fixtures";
    showPad(true);
  }).catch(() => showPad(false));
}
setInterval(poll, 400);
</script>
</body>
</html>
"""


def page_html() -> str:
    payload = json.dumps(CATALOG["public"], ensure_ascii=False).replace("<", "\\u003c")
    return PAGE.replace("__CATALOG__", payload)


def make_handler(worker: ShowWorker):
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
            self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

        def _read(self) -> dict:
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
            if path == "/api/catalog":
                self._json(200, CATALOG["public"])
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                payload = self._read()
            except json.JSONDecodeError:
                self._json(400, {"error": "json"})
                return
            try:
                if path == "/api/map":
                    self._json(200, {"rig": _parse_rig(payload)})
                    return
                if path == "/api/rig":
                    rig = _parse_rig(payload)
                    worker.submit(("rig", rig))
                    self._json(200, {"ok": True, "rig": rig})
                    return
                if path == "/api/play":
                    name = str(payload.get("name") or "")
                    palette = str(payload.get("palette") or "")
                    speed = str(payload.get("speed") or "medio")
                    if name not in CATALOG["looks"] or palette not in CATALOG["paletteById"]:
                        self._json(400, {"error": "unknown look"})
                        return
                    if speed not in CATALOG["speedById"]:
                        self._json(400, {"error": "unknown speed"})
                        return
                    worker.submit(("play", name, palette, speed))
                    self._json(200, {"ok": True, "play": name})
                    return
                if path == "/api/blackout":
                    worker.submit(("blackout",))
                    self._json(200, {"ok": True})
                    return
                if path == "/api/reconnect":
                    worker.submit(("reconnect",))
                    self._json(200, {"ok": True})
                    return
            except (RigError, TypeError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(404, {"error": "not found"})

    return Handler


def main() -> None:
    CATALOG["public"] = {
        "groups": CATALOG["groups"],
        "speeds": CATALOG["speeds"],
        "palettes": CATALOG["palettes"],
    }
    print("show console (web)", flush=True)
    worker = ShowWorker()
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
        worker.submit(("quit",))
        worker.join(timeout=1.5)
        httpd.server_close()


if __name__ == "__main__":
    main()
