import { catalog } from "./catalog";
import { buildRig, parRgb, RigError, type Palette, type Rig } from "./engine/show";
import { renderPreview } from "./preview";
import { ShowRuntime, type RuntimeCommand, type ShowStatus } from "./runtime";
import { explainUsbFailure, PID, VID } from "./usb";

const RIG_KEY = "deo.show.rig";
const TUNE_KEY = "deo.show.tune";
const LOOK_KEY = "deo.show.look";

interface RigChoice {
  nLpc: number;
  nBeam: number;
  order: string;
}

interface Tune {
  palette: string;
  speed: string;
}

const app = document.querySelector("#app");
if (!app) throw new Error("falta #app");

let rigChoice: RigChoice = { nLpc: 0, nBeam: 2, order: "lpc_first" };
let tune: Tune = { palette: "blanco", speed: "medio" };
let activeLook: string | null = null;
let wakeLock: WakeLockSentinel | null = null;
let hiddenAt = 0;
let worker: Worker | null = null;
let local: ShowRuntime | null = null;
let useWorker = false;
let status: ShowStatus | null = null;

function loadStore(): boolean {
  let hadRig = false;
  try {
    const saved = JSON.parse(localStorage.getItem(RIG_KEY) || "null") as RigChoice | null;
    if (saved && typeof saved.nLpc === "number") {
      rigChoice = { nLpc: saved.nLpc, nBeam: saved.nBeam, order: saved.order || "lpc_first" };
      hadRig = true;
    }
  } catch {
    /* ignore broken storage */
  }
  try {
    const saved = JSON.parse(localStorage.getItem(TUNE_KEY) || "null") as Tune | null;
    if (saved?.palette && saved.speed) tune = saved;
  } catch {
    /* ignore */
  }
  activeLook = localStorage.getItem(LOOK_KEY);
  if (tune.palette && !catalog.paletteById.has(tune.palette)) tune.palette = "blanco";
  if (!catalog.speedById.has(tune.speed)) tune.speed = "medio";
  return hadRig;
}

function saveStore(): void {
  localStorage.setItem(RIG_KEY, JSON.stringify(rigChoice));
  localStorage.setItem(TUNE_KEY, JSON.stringify(tune));
  if (activeLook) localStorage.setItem(LOOK_KEY, activeLook);
}

let localChain: Promise<void> = Promise.resolve();

function send(command: RuntimeCommand): void {
  if (useWorker && worker) worker.postMessage(command);
  else if (local) localChain = localChain.then(() => local?.handle(command));
}

function slotCss(palette: Palette): string {
  const cols = palette.colors.map((color) => {
    const [r, g, b] = parRgb(color);
    return `rgb(${r}, ${g}, ${b})`;
  });
  const n = Math.max(cols.length, 1);
  const stops = cols.map((color, i) => `${color} ${(i / n) * 100}% ${((i + 1) / n) * 100}%`).join(", ");
  return `linear-gradient(90deg, ${stops})`;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const hadRig = loadStore();

const home = el("div", "home");
const pad = el("div");
pad.hidden = !hadRig;
const banner = el("div", "banner");
banner.hidden = true;
const help = document.createElement("dialog");

home.append(
  el("h1", undefined, "Rig"),
  el("p", "muted", "LPC008 es el PAR de 7 canales. BEAM 60W es 30 canales. Las direcciones salen desde el canal 1."),
);
const lpcRow = el("div", "row");
const lpcStep = el("div", "step");
const lpcDec = el("button", undefined, "−");
const lpcNum = el("strong", undefined, String(rigChoice.nLpc));
const lpcInc = el("button", undefined, "+");
lpcDec.type = "button";
lpcInc.type = "button";
lpcStep.append(lpcDec, lpcNum, lpcInc);
lpcRow.append(el("span", undefined, "LPC008 · 7CH"), lpcStep);
const beamRow = el("div", "row");
const beamStep = el("div", "step");
const beamDec = el("button", undefined, "−");
const beamNum = el("strong", undefined, String(rigChoice.nBeam));
const beamInc = el("button", undefined, "+");
beamDec.type = "button";
beamInc.type = "button";
beamStep.append(beamDec, beamNum, beamInc);
beamRow.append(el("span", undefined, "BEAM 60W · 30CH"), beamStep);
const orderRow = el("div", "chips");
const orderLpc = el("button", "small", "PAR primero");
const orderBeam = el("button", "small", "BEAM primero");
orderLpc.type = "button";
orderBeam.type = "button";
orderRow.append(orderLpc, orderBeam);
const mapLine = el("div");
mapLine.id = "map";
const enterRow = el("div", "bar");
const enter = el("button", undefined, "Entrar al pad");
enter.type = "button";
enterRow.append(enter);
const connectRow = el("div", "bar");
const connect = el("button", undefined, "Conectar uDMX");
const simulate = el("button", undefined, "Simular");
const helpBtn = el("button", "small", "Ayuda");
connect.type = "button";
simulate.type = "button";
helpBtn.type = "button";
connectRow.append(connect, simulate, helpBtn);
home.append(lpcRow, beamRow, orderRow, mapLine, enterRow, connectRow);

const header = el("header");
const subtitle = el("div", "muted", "show");
const editRig = el("button", "small", "Rig");
const helpPad = el("button", "small", "Ayuda");
editRig.type = "button";
helpPad.type = "button";
const headerButtons = el("div", "step");
headerButtons.append(helpPad, editRig);
header.append(subtitle, headerButtons);
helpPad.addEventListener("click", () => help.showModal());
const usbLine = el("div", "muted");
usbLine.style.padding = "0 18px";
const actions = el("div", "bar");
const blackout = el("button", undefined, "BLACKOUT");
const reconnect = el("button", undefined, "Reconectar");
blackout.id = "blackout";
blackout.type = "button";
reconnect.type = "button";
actions.append(blackout, reconnect);
const line = el("div");
line.id = "line";
const hint = el("div");
hint.id = "hint";
const palettes = el("div", "chips");
const speeds = el("div", "chips");
const groups = el("div");
const previewTitle = el("h2", undefined, "Vista");
previewTitle.style.padding = "8px 18px 0";
const preview = el("div");
pad.append(header, banner, usbLine, actions, line, hint, palettes, speeds, groups, previewTitle, preview);

help.append(helpArticle(), el("form", undefined));
const closeHelp = el("button", undefined, "Cerrar");
closeHelp.type = "submit";
closeHelp.value = "cerrar";
help.querySelector("form")?.append(closeHelp);
help.addEventListener("click", (event) => {
  if (event.target === help) help.close();
});
help.querySelector("form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  help.close();
});

app.append(home, pad, help);

function paintHome(): void {
  lpcNum.textContent = String(rigChoice.nLpc);
  beamNum.textContent = String(rigChoice.nBeam);
  orderLpc.classList.toggle("picked", rigChoice.order !== "beam_first");
  orderBeam.classList.toggle("picked", rigChoice.order === "beam_first");
  try {
    const rig = buildRig(rigChoice.nLpc, rigChoice.nBeam, rigChoice.order);
    mapLine.textContent = rig.fixtures.map((fixture) => `${fixture.type} ${fixture.label}`).join("   ") || "ningún fixture";
  } catch (err) {
    mapLine.textContent = err instanceof RigError ? err.message : "rig inválido";
  }
}

function paintControls(): void {
  for (const button of palettes.querySelectorAll("button")) {
    button.classList.toggle("on", button.dataset.id === tune.palette);
  }
  for (const button of speeds.querySelectorAll("button")) {
    button.classList.toggle("on", button.dataset.id === tune.speed);
  }
  for (const button of groups.querySelectorAll("button")) {
    button.classList.toggle("on", button.dataset.look === activeLook);
  }
}

function buildPad(): void {
  palettes.replaceChildren();
  speeds.replaceChildren();
  for (const palette of catalog.palettes) {
    const button = el("button", "small");
    button.type = "button";
    button.dataset.id = palette.id;
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = slotCss(palette);
    button.append(swatch, document.createTextNode(palette.label));
    button.addEventListener("click", () => choosePalette(palette.id));
    palettes.append(button);
  }
  for (const speed of catalog.speeds) {
    const button = el("button", "small", speed.label);
    button.type = "button";
    button.dataset.id = speed.id;
    button.addEventListener("click", () => chooseSpeed(speed.id));
    speeds.append(button);
  }
  groups.replaceChildren();
  for (const group of catalog.groups) {
    const section = document.createElement("section");
    section.append(el("h2", undefined, group.title));
    const grid = el("div", "grid");
    for (const look of group.looks) {
      const button = el("button", undefined, look.label);
      button.type = "button";
      button.dataset.look = look.id;
      button.addEventListener("click", () => play(look.id));
      grid.append(button);
    }
    section.append(grid);
    groups.append(section);
  }
}

function showPad(on: boolean): void {
  home.hidden = on;
  pad.hidden = !on;
}

function play(id: string): void {
  activeLook = id;
  saveStore();
  paintControls();
  send({ type: "play", lookId: id, paletteId: tune.palette, speedId: tune.speed });
  void keepAwake();
}

function choosePalette(id: string): void {
  tune.palette = id;
  saveStore();
  paintControls();
  if (activeLook && activeLook !== "blackout") play(activeLook);
}

function chooseSpeed(id: string): void {
  tune.speed = id;
  saveStore();
  paintControls();
  if (activeLook && activeLook !== "blackout") play(activeLook);
}

function bump(key: "nLpc" | "nBeam", delta: number): void {
  rigChoice[key] = Math.max(0, Math.min(8, rigChoice[key] + delta));
  paintHome();
}

function applyStatus(next: ShowStatus): void {
  status = next;
  line.textContent = next.line;
  usbLine.textContent = next.usb;
  hint.textContent = next.hint;
  if (next.scene && next.scene !== "blackout") {
    activeLook = next.scene;
    localStorage.setItem(LOOK_KEY, next.scene);
  }
  if (next.scene === "blackout") activeLook = null;
  subtitle.textContent = next.rig.fixtures.map((fixture) => fixture.label).join(" ") || "sin fixtures";
  reconnect.textContent = next.connected ? "Reconectar" : "Conectar uDMX";
  previewTitle.textContent = next.mode === "usb" ? "Lo que se está enviando" : "Simulador";
  renderPreview(preview, next.rig, next.frame);
  paintControls();
}

async function keepAwake(): Promise<void> {
  if (!("wakeLock" in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
    wakeLock.addEventListener("release", () => {
      wakeLock = null;
    });
  } catch {
    /* hidden tab or unsupported */
  }
}

async function onConnect(): Promise<void> {
  if (!navigator.usb) {
    hint.textContent = explainUsbFailure(new DOMException("sin WebUSB", "SecurityError"), "abrir").hint;
    return;
  }
  try {
    const device = await navigator.usb.requestDevice({ filters: [{ vendorId: VID, productId: PID }] });
    if (useWorker) send({ type: "open" });
    else await local?.openDevice(device);
    await keepAwake();
    if (activeLook && activeLook !== "blackout" && !useWorker) {
      send({ type: "play", lookId: activeLook, paletteId: tune.palette, speedId: tune.speed });
    }
  } catch (err) {
    const explained = explainUsbFailure(err, "abrir");
    line.textContent = explained.message;
    hint.textContent = explained.hint;
  }
}

function onRigEnter(): void {
  try {
    const rig: Rig = buildRig(rigChoice.nLpc, rigChoice.nBeam, rigChoice.order);
    rigChoice = { nLpc: rig.nLpc, nBeam: rig.nBeam, order: rig.order };
  } catch (err) {
    mapLine.textContent = err instanceof Error ? err.message : "rig inválido";
    return;
  }
  saveStore();
  send({ type: "rig", ...rigChoice });
  showPad(true);
  if (activeLook && activeLook !== "blackout") play(activeLook);
}

lpcDec.addEventListener("click", () => bump("nLpc", -1));
lpcInc.addEventListener("click", () => bump("nLpc", 1));
beamDec.addEventListener("click", () => bump("nBeam", -1));
beamInc.addEventListener("click", () => bump("nBeam", 1));
orderLpc.addEventListener("click", () => {
  rigChoice.order = "lpc_first";
  paintHome();
});
orderBeam.addEventListener("click", () => {
  rigChoice.order = "beam_first";
  paintHome();
});
enter.addEventListener("click", onRigEnter);
editRig.addEventListener("click", () => {
  showPad(false);
  paintHome();
});
connect.addEventListener("click", () => void onConnect());
simulate.addEventListener("click", () => {
  try {
    buildRig(rigChoice.nLpc, rigChoice.nBeam, rigChoice.order);
  } catch (err) {
    mapLine.textContent = err instanceof Error ? err.message : "rig inválido";
    return;
  }
  saveStore();
  send({ type: "rig", ...rigChoice });
  send({ type: "simulate" });
  showPad(true);
  if (activeLook && activeLook !== "blackout") play(activeLook);
});
helpBtn.addEventListener("click", () => help.showModal());
blackout.addEventListener("click", () => {
  activeLook = null;
  localStorage.removeItem(LOOK_KEY);
  paintControls();
  send({ type: "blackout" });
});
reconnect.addEventListener("click", () => void onConnect());

document.addEventListener("visibilitychange", () => {
  const visible = document.visibilityState === "visible";
  send({ type: "visible", visible });
  if (!visible) {
    hiddenAt = performance.now();
    banner.hidden = false;
    banner.textContent = "Pestaña oculta: el navegador puede frenar el USB. Al volver se retoma el look.";
    return;
  }
  void keepAwake();
  const away = performance.now() - hiddenAt;
  banner.hidden = away < 1000;
  banner.textContent = "Se reanudó el envío.";
  if (!banner.hidden) setTimeout(() => { banner.hidden = true; }, 3000);
});

window.addEventListener("pagehide", () => send({ type: "shutdown" }));

function attach(source: { handle?: (command: RuntimeCommand) => Promise<void> } | Worker): void {
  if (source instanceof Worker) {
    source.onmessage = (event: MessageEvent<{ type: string; usbInWorker?: boolean; status?: ShowStatus }>) => {
      if (event.data.type === "ready") {
        useWorker = Boolean(event.data.usbInWorker);
        if (!useWorker) {
          source.terminate();
          worker = null;
          startLocal();
          return;
        }
        send({ type: "boot" });
        restoreRig();
        return;
      }
      if (event.data.status) applyStatus(event.data.status);
    };
    return;
  }
}

function startLocal(): void {
  useWorker = false;
  local = new ShowRuntime(applyStatus);
  send({ type: "boot" });
  restoreRig();
}

function restoreRig(): void {
  if (!hadRig) return;
  send({ type: "rig", ...rigChoice });
  if (activeLook && activeLook !== "blackout") {
    send({ type: "play", lookId: activeLook, paletteId: tune.palette, speedId: tune.speed });
  }
}

function boot(): void {
  paintHome();
  buildPad();
  paintControls();
  if (hadRig) showPad(true);
  try {
    worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    attach(worker);
  } catch {
    startLocal();
  }
}

boot();

function helpArticle(): HTMLElement {
  const article = document.createElement("article");
  article.append(el("h2", undefined, "Ayuda"));
  article.append(
    el(
      "p",
      undefined,
      "La consola manda DMX al Anyma uDMX (USB 16C0:05DC) desde Chrome o Edge. Un solo programa puede tener el dongle: cierra QLC+ y el panel Python antes de conectar.",
    ),
  );
  article.append(el("h3", undefined, "Mac"));
  article.append(
    el(
      "p",
      undefined,
      "Chrome o Edge, el link en HTTPS (o localhost). Pulsa Conectar uDMX y elige el aparato. Deja esta pestaña delante. Si la pantalla se apaga, la página pide que siga encendida; si cambias de app, el envío puede parar y al volver se retoma solo.",
    ),
  );
  article.append(el("h3", undefined, "Android (Seeker)"));
  article.append(
    el(
      "p",
      undefined,
      "Cable OTG, Chrome, la APK cerrada. El mismo botón Conectar. Chrome tiene que quedarse en primer plano. Con el teléfono en el bolsillo sigue siendo más fiable la app nativa.",
    ),
  );
  article.append(el("h3", undefined, "Windows: driver WinUSB"));
  article.append(
    el(
      "p",
      undefined,
      "Chrome en Windows no abre el uDMX con el driver de libusb que usan pyusb y QLC+. Hay que instalar WinUSB con Zadig. Eso reemplaza el driver anterior: en esa máquina pyusb y QLC+ pueden dejar de ver el dongle hasta que lo reviertas.",
    ),
  );
  const steps = document.createElement("ol");
  for (const step of [
    "Cierra Chrome, QLC+ y cualquier panel Python.",
    "Descarga Zadig desde https://zadig.akeo.ie/ y ábrelo.",
    "Menú Options → List All Devices.",
    "Elige el uDMX. En la línea USB ID tiene que decir 16C0 05DC. A veces aparece como dispositivo desconocido.",
    "En el recuadro de la derecha, el driver destino es WinUSB.",
    "Replace Driver y espera a que termine. Desenchufa y vuelve a enchufar.",
    "Abre Chrome, entra a esta página y pulsa Conectar uDMX.",
  ]) {
    steps.append(el("li", undefined, step));
  }
  article.append(steps);
  article.append(el("h3", undefined, "Volver a pyusb o QLC+"));
  article.append(
    el(
      "p",
      undefined,
      "Abre Zadig otra vez, List All Devices, el mismo 16C0:05DC. Como driver destino elige libusb-win32 o libusbK (el que usabas antes) y Replace Driver. Si no recuerdas cuál era: en el Administrador de dispositivos, el uDMX → Desinstalar dispositivo, marca eliminar el driver, desenchufa y enchufa. Windows lo dejará sin driver; Zadig puede instalar libusb-win32 de nuevo.",
    ),
  );
  article.append(el("h3", undefined, "Si Chrome se queja"));
  article.append(
    el(
      "p",
      undefined,
      "«No se eligió» o el aparato no sale en la lista: falta WinUSB, u otro programa lo tiene abierto. «No se pudo abrir»: cierra QLC+ y el panel, y revisa que el driver sea WinUSB. El simulador no necesita el dongle.",
    ),
  );
  return article;
}
