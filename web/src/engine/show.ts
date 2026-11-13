import { engineFor, type EngineRun } from "./beam";
import { BEAM_CH, blackoutFrame, headFrame } from "./head";
import { arr, asObj, has, intField, isObj, Json, listOfObjects, num, strField } from "./json";
import { clamp, deepClone, pythonMod, pythonRound } from "./math";

export const LPC_CH = 7;
export const CH6_LINEAR = 25;
const UNIVERSE = 512;
const MAX_EACH = 8;
const COLOR_HOLD = 1.2;
const TWO_PI = Math.PI * 2;

const RATE_KEYS = ["pan_hz", "tilt_hz", "open_hz", "flash_hz", "circle_hz", "ring_hz", "pan_dps"];
const PERIOD_KEYS = ["color_period", "pan_period", "period", "hold_min", "hold_max"];

export class RigError extends Error {}

export interface Fixture {
  type: "lpc" | "beam";
  index: number;
  address: number;
  start: number;
  channels: number;
  label: string;
}

export interface Rig {
  order: string;
  nLpc: number;
  nBeam: number;
  fixtures: Fixture[];
  span: number;
}

export interface Slot {
  name: string;
  r: number;
  g: number;
  b: number;
  w: number;
  halo: number[];
  beam: number[];
}

export interface Palette {
  id: string;
  label: string;
  colors: Slot[];
}

export interface Speed {
  id: string;
  label: string;
  scale: number;
}

export interface Look {
  id: string;
  label: string;
  kind: string;
  beam: Json | null;
  lpc: Json | null;
}

export interface LookGroup {
  title: string;
  looks: Look[];
}

export interface ShowCatalog {
  groups: LookGroup[];
  looks: Map<string, Look>;
  palettes: Palette[];
  paletteById: Map<string, Palette>;
  speeds: Speed[];
  speedById: Map<string, number>;
}

export function buildRig(nLpc: number, nBeam: number, order = "lpc_first"): Rig {
  if (order !== "lpc_first" && order !== "beam_first") throw new RigError(`unknown order ${order}`);
  for (const [name, n] of [
    ["LPC008", nLpc],
    ["BEAM", nBeam],
  ] as const) {
    if (!Number.isInteger(n) || n < 0) throw new RigError(`${name} count must be >= 0`);
    if (n > MAX_EACH) throw new RigError(`${name} count ${n} is above ${MAX_EACH}`);
  }
  const blocks: ["lpc" | "beam", number, number][] = [
    ["lpc", nLpc, LPC_CH],
    ["beam", nBeam, 30],
  ];
  if (order === "beam_first") blocks.reverse();
  const fixtures: Fixture[] = [];
  let cursor = 0;
  const seen = { lpc: 0, beam: 0 };
  for (const [kind, count, channels] of blocks) {
    for (let i = 0; i < count; i++) {
      if (cursor + channels > UNIVERSE) {
        throw new RigError(`el mapa pasa de ${UNIVERSE} canales (${kind} en ${cursor + 1})`);
      }
      const index = seen[kind];
      fixtures.push({
        type: kind,
        index,
        address: cursor + 1,
        start: cursor,
        channels,
        label: `A${String(cursor + 1).padStart(3, "0")}`,
      });
      seen[kind] = index + 1;
      cursor += channels;
    }
  }
  return { order, nLpc, nBeam, fixtures, span: cursor };
}

export function fixturesOf(rig: Rig, kind: Fixture["type"]): Fixture[] {
  return rig.fixtures.filter((fixture) => fixture.type === kind);
}

function slotFrom(raw: Json): Slot {
  let r: number;
  let g: number;
  let b: number;
  let w: number;
  let halo: number[];
  if (has(raw, "beam")) {
    const beam = pad4(raw.beam);
    r = beam[0];
    g = beam[1];
    b = beam[2];
    w = beam[3];
    halo = has(raw, "halo") ? nums3(raw.halo) : [r, g, b];
  } else {
    r = intField(raw, "r");
    g = intField(raw, "g");
    b = intField(raw, "b");
    w = intField(raw, "w", 0);
    halo = has(raw, "halo") ? nums3(raw.halo) : [r, g, b];
  }
  const name = strField(raw, "name", "");
  return { name, r, g, b, w, halo, beam: [r, g, b, w] };
}

function pad4(value: unknown): number[] {
  const raw = Array.isArray(value) ? value.map((item) => Math.trunc(Number(item))) : [];
  while (raw.length < 4) raw.push(0);
  return raw.slice(0, 4);
}

function nums3(value: unknown): number[] {
  const raw = Array.isArray(value) ? value.map((item) => Math.trunc(Number(item))) : [0, 0, 0];
  return [raw[0] ?? 0, raw[1] ?? 0, raw[2] ?? 0];
}

export function parRgb(slot: Slot): [number, number, number] {
  if (slot.r || slot.g || slot.b) return [slot.r, slot.g, slot.b];
  if (slot.halo.some((channel) => channel !== 0)) return [slot.halo[0], slot.halo[1], slot.halo[2]];
  if (slot.w) return [255, 255, 255];
  return [0, 0, 0];
}

export function loadCatalog(looksText: unknown, palettesText: unknown): ShowCatalog {
  const looksJson = asObj(looksText, "looks");
  const palettesJson = asObj(palettesText, "palettes");
  const groups: LookGroup[] = [];
  const byId = new Map<string, Look>();
  for (const groupRaw of arr(looksJson, "groups")) {
    const group = asObj(groupRaw, "group");
    const looks: Look[] = [];
    for (const lookRaw of arr(group, "looks")) {
      const raw = asObj(lookRaw, "look");
      const look: Look = {
        id: strField(raw, "id"),
        label: strField(raw, "label"),
        kind: strField(raw, "kind"),
        beam: has(raw, "beam") ? asObj(raw.beam, "beam") : null,
        lpc: has(raw, "lpc") ? asObj(raw.lpc, "lpc") : null,
      };
      if (look.kind === "geometry" && !look.beam?.sequence) {
        throw new Error(`look ${look.id} needs beam.sequence`);
      }
      if (look.kind === "light" && !look.lpc?.engine) {
        throw new Error(`look ${look.id} needs lpc.engine`);
      }
      if (byId.has(look.id)) throw new Error(`duplicate look ${look.id}`);
      byId.set(look.id, look);
      looks.push(look);
    }
    groups.push({ title: strField(group, "title"), looks });
  }
  const palettes: Palette[] = [];
  for (const palRaw of arr(palettesJson, "palettes")) {
    const raw = asObj(palRaw, "palette");
    const colors = arr(raw, "colors");
    if (!colors.length) throw new Error(`palette ${strField(raw, "id", "?")} needs a colors list`);
    palettes.push({
      id: strField(raw, "id"),
      label: strField(raw, "label"),
      colors: colors.map((color) => slotFrom(asObj(color, "color"))),
    });
  }
  const speeds: Speed[] = arr(looksJson, "speeds").map((row) => {
    const raw = asObj(row, "speed");
    return { id: strField(raw, "id"), label: strField(raw, "label"), scale: num(raw, "scale") };
  });
  const speedById = new Map(speeds.map((speed) => [speed.id, speed.scale]));
  if (speedById.get("medio") !== 1) throw new Error("speed 'medio' must be scale 1");
  return {
    groups,
    looks: byId,
    palettes,
    paletteById: new Map(palettes.map((palette) => [palette.id, palette])),
    speeds,
    speedById,
  };
}

export function applySpeed(seq: Json, scale: number): Json {
  if (scale === 1) return seq;
  for (const key of RATE_KEYS) {
    if (typeof seq[key] === "number") seq[key] = (seq[key] as number) * scale;
  }
  for (const key of PERIOD_KEYS) {
    if (typeof seq[key] === "number") seq[key] = (seq[key] as number) / scale;
  }
  if (typeof seq.speed === "number") seq.speed = clamp((seq.speed as number) * scale);
  return seq;
}

function colorRow(slot: Slot, index: number): Json {
  return {
    name: slot.name || `c${index}`,
    beam: slot.beam.slice(),
    halo: slot.halo.slice(),
  };
}

function paintSide(side: Json, slot: Slot): void {
  side.r = slot.r;
  side.g = slot.g;
  side.b = slot.b;
  side.w = slot.w;
  side.halo = slot.halo.slice();
}

export function applyPalette(seq: Json, palette: Palette | null): Json {
  if (!palette) return seq;
  const slots = palette.colors;
  const rows = slots.map((slot, index) => colorRow(slot, index));
  const slotA = slots[0];
  const slotB = slots[1] ?? slotA;
  if (isObj(seq.a) && has(seq.a, "r")) {
    paintSide(seq.a, slotA);
    if (!isObj(seq.b)) seq.b = {};
    paintSide(seq.b as Json, slotB);
  }
  if (Array.isArray(seq.colors)) seq.colors = rows;
  if (Array.isArray(seq.palette)) seq.palette = rows;
  return seq;
}

export function prepareSequence(raw: Json, palette: Palette | null, scale: number): Json {
  const out = deepClone(raw);
  applySpeed(out, scale);
  applyPalette(out, palette);
  return out;
}

export function paletteStep(t: number, nColors: number, scale: number): number {
  if (nColors <= 2) return 0;
  const hold = COLOR_HOLD / (scale > 0 ? scale : 1);
  return pythonMod(Math.trunc(t / hold), nColors);
}

function engineCycles(seq: Json): boolean {
  const colors = seq.colors;
  if (Array.isArray(colors) && colors.length && isObj(colors[0]) && has(colors[0], "beam")) return true;
  const listed = seq.palette;
  return Array.isArray(listed) && listed.length > 0 && isObj(listed[0]) && has(listed[0], "beam");
}

function paintBeamColor(frame: number[], slot: Slot): void {
  frame[7] = slot.beam[0];
  frame[8] = slot.beam[1];
  frame[9] = slot.beam[2];
  frame[10] = slot.beam[3];
  const [hr, hg, hb] = slot.halo;
  let p = 11;
  for (let i = 0; i < 6; i++) {
    frame[p++] = hr;
    frame[p++] = hg;
    frame[p++] = hb;
  }
}

export function lpcBytes(r: number, g: number, b: number, dimmer = 255, hardOff = false): number[] {
  if (hardOff || dimmer <= 0) return [0, 0, 0, 0, 0, 0, 0];
  return [dimmer, r, g, b, 0, CH6_LINEAR, 0];
}

export function blackoutBuffer(rig: Rig): number[] {
  const buf = new Array<number>(rig.span).fill(0);
  for (const fixture of rig.fixtures) {
    if (fixture.type === "beam") {
      const frame = blackoutFrame();
      for (let i = 0; i < frame.length; i++) buf[fixture.start + i] = frame[i];
    }
  }
  return buf;
}

interface LightState {
  r: number;
  g: number;
  b: number;
  dimmer: number;
  hardOff: boolean;
}

function uniform(lo: number, hi: number, rng: () => number): number {
  return lo + rng() * (hi - lo);
}

class Hold {
  private readonly lo: number;
  private readonly hi: number;
  private readonly nColors: number;
  private on: boolean;
  private until: number;
  private slot: number;
  private readonly rng: () => number;

  constructor(holdMin: number, holdMax: number, nColors: number, rng: () => number) {
    this.lo = holdMin;
    this.hi = Math.max(holdMax, holdMin);
    this.nColors = Math.max(1, nColors);
    this.rng = rng;
    this.on = rng() < 0.5;
    this.until = uniform(this.lo, this.hi, rng);
    this.slot = Math.floor(rng() * this.nColors);
  }

  at(t: number): [boolean, number] {
    if (t >= this.until) {
      this.on = !this.on;
      this.slot = Math.floor(this.rng() * this.nColors);
      this.until = t + uniform(this.lo, this.hi, this.rng);
    }
    return [this.on, this.slot];
  }
}

class Bolt {
  private readonly colors: number[][];
  private readonly fps: number;
  private readonly gapMin: number;
  private readonly gapMax: number;
  private readonly flashMin: number;
  private readonly flashMax: number;
  private readonly burstsMin: number;
  private readonly burstsMax: number;
  private readonly burstGapMin: number;
  private readonly burstGapMax: number;
  private readonly queue: LightState[] = [];
  private nextT: number;
  private readonly rng: () => number;

  constructor(colors: number[][], base: Json, fps: number, rng: () => number) {
    this.colors = colors;
    this.fps = fps;
    this.rng = rng;
    this.gapMin = num(base, "gap_min", 0.5);
    this.gapMax = Math.max(num(base, "gap_max", 2.4), this.gapMin);
    this.flashMin = num(base, "flash_min", 0.05);
    this.flashMax = num(base, "flash_max", 0.14);
    this.burstsMin = intField(base, "bursts_min", 1);
    this.burstsMax = intField(base, "bursts_max", 3);
    this.burstGapMin = num(base, "burst_gap_min", 0.04);
    this.burstGapMax = num(base, "burst_gap_max", 0.11);
    this.nextT = uniform(0.05, this.gapMax * 0.5, rng);
  }

  lookAt(t: number): LightState {
    if (this.queue.length) return this.queue.shift()!;
    if (t >= this.nextT) {
      this.queue.push(...this.strike());
      const strikeS = this.queue.length / this.fps;
      this.nextT = t + strikeS + uniform(this.gapMin, this.gapMax, this.rng);
      return this.queue.shift()!;
    }
    return { r: 0, g: 0, b: 0, dimmer: 0, hardOff: true };
  }

  private strike(): LightState[] {
    const color = this.colors[Math.floor(this.rng() * this.colors.length)];
    const nBursts =
      this.burstsMin + Math.floor(this.rng() * (this.burstsMax - this.burstsMin + 1));
    const frames: LightState[] = [];
    for (let i = 0; i < nBursts; i++) {
      const dim = i === 0 ? 255 : 90 + Math.floor(this.rng() * 111);
      const nOn = Math.max(1, pythonRound(uniform(this.flashMin, this.flashMax, this.rng) * this.fps));
      for (let k = 0; k < nOn; k++) frames.push({ r: color[0], g: color[1], b: color[2], dimmer: dim, hardOff: false });
      if (i + 1 < nBursts) {
        const nOff = Math.max(1, pythonRound(uniform(this.burstGapMin, this.burstGapMax, this.rng) * this.fps));
        for (let k = 0; k < nOff; k++) frames.push({ r: 0, g: 0, b: 0, dimmer: 0, hardOff: true });
      }
    }
    return frames;
  }
}

function scaledBolt(base: Json, scale: number): Json {
  const out = deepClone(base);
  for (const key of ["gap_min", "gap_max", "flash_min", "flash_max", "burst_gap_min", "burst_gap_max"]) {
    if (typeof out[key] === "number") out[key] = (out[key] as number) / scale;
  }
  return out;
}

function numberField(obj: Json, a: string, b: string, fallback: number): number {
  if (has(obj, a)) return num(obj, a);
  if (has(obj, b)) return num(obj, b);
  return fallback;
}

class LightGesture {
  private readonly bolts: Bolt[];
  private readonly holds: Hold[];

  constructor(
    private readonly engine: string,
    private readonly base: Json,
    private readonly palette: Palette,
    private readonly scale: number,
    private readonly n: number,
    rng: () => number = Math.random,
  ) {
    const safe = scale > 0 ? scale : 1;
    this.bolts =
      engine === "lightning" && n > 0
        ? Array.from({ length: n }, () => new Bolt(palette.colors.map((slot) => parRgb(slot)), scaledBolt(base, safe), num(base, "fps", 12), rng))
        : [];
    this.holds =
      engine === "random" && n > 0
        ? Array.from({ length: n }, () => {
            const lo = numberField(base, "holdMin", "hold_min", 0.35) / safe;
            const hi = numberField(base, "holdMax", "hold_max", 1.4) / safe;
            return new Hold(lo, Math.max(hi, lo), palette.colors.length, rng);
          })
        : [];
  }

  states(t: number): LightState[] {
    if (this.n <= 0) return [];
    switch (this.engine) {
      case "dual_breathe":
        return this.breathe(t);
      case "alt_strobe":
        return this.strobe(t);
      case "chase":
        return this.chase(t);
      case "dual_fade":
        return this.fade(t);
      case "lightning":
        return this.bolts.map((bolt) => bolt.lookAt(t));
      case "random":
        return this.holds.map((hold) => {
          const [on, slot] = hold.at(t);
          if (!on) return { r: 0, g: 0, b: 0, dimmer: 0, hardOff: true };
          const rgb = parRgb(this.palette.colors[slot % this.palette.colors.length]);
          return { r: rgb[0], g: rgb[1], b: rgb[2], dimmer: 255, hardOff: false };
        });
      default:
        throw new Error(`unknown light engine ${this.engine}`);
    }
  }

  private safeScale(): number {
    return this.scale > 0 ? this.scale : 1;
  }

  private breathe(t: number): LightState[] {
    const period = num(this.base, "period", 5) / this.safeScale();
    const lo = intField(this.base, "dimmer_lo", 50);
    const hi = intField(this.base, "dimmer_hi", 255);
    const dims =
      this.n === 2
        ? (() => {
            const u = 0.5 + 0.5 * Math.sin((TWO_PI * t) / period - Math.PI / 2);
            return [pythonRound(lo + (hi - lo) * u), pythonRound(lo + (hi - lo) * (1 - u))];
          })()
        : Array.from({ length: this.n }, (_, i) => {
            const u = 0.5 + 0.5 * Math.sin(TWO_PI * (t / period + i / this.n) - Math.PI / 2);
            return pythonRound(lo + (hi - lo) * u);
          });
    const step = paletteStep(t, this.palette.colors.length, this.scale);
    return dims.map((dim, i) => {
      const rgb = parRgb(this.palette.colors[(i + step) % this.palette.colors.length]);
      return { r: rgb[0], g: rgb[1], b: rgb[2], dimmer: dim, hardOff: false };
    });
  }

  private strobe(t: number): LightState[] {
    const hz = num(this.base, "hz", 1) * this.scale;
    const nColors = this.palette.colors.length;
    if (this.n === 2 && nColors === 2) {
      const stage = pythonMod(Math.trunc(t * hz * 4), 4);
      const picks: [number | null, boolean][] = [
        [0, false],
        [null, true],
        [1, false],
        [null, true],
      ];
      const [slot, off] = picks[stage];
      return [0, 1].map((i) => {
        if (off || slot !== i) return { r: 0, g: 0, b: 0, dimmer: 0, hardOff: true };
        const rgb = parRgb(this.palette.colors[i]);
        return { r: rgb[0], g: rgb[1], b: rgb[2], dimmer: 255, hardOff: false };
      });
    }
    return Array.from({ length: this.n }, (_, i) => {
      const phase = pythonMod(t * hz + i / Math.max(this.n, 1), 1);
      if (phase < 0.25) {
        const rgb = parRgb(this.palette.colors[pythonMod(i + Math.trunc(t * hz), nColors)]);
        return { r: rgb[0], g: rgb[1], b: rgb[2], dimmer: 255, hardOff: false };
      }
      return { r: 0, g: 0, b: 0, dimmer: 0, hardOff: true };
    });
  }

  private chase(t: number): LightState[] {
    const hz = num(this.base, "hz", 1) * this.scale;
    const nColors = this.palette.colors.length;
    if (this.n === 2 && nColors === 2) {
      const swap = pythonMod(Math.trunc(t * hz * 2), 2);
      return [0, 1].map((i) => {
        const rgb = parRgb(this.palette.colors[i ^ swap]);
        return { r: rgb[0], g: rgb[1], b: rgb[2], dimmer: 255, hardOff: false };
      });
    }
    const step = pythonMod(Math.trunc(t * hz * nColors), nColors);
    return Array.from({ length: this.n }, (_, i) => {
      const rgb = parRgb(this.palette.colors[(i + step) % nColors]);
      return { r: rgb[0], g: rgb[1], b: rgb[2], dimmer: 255, hardOff: false };
    });
  }

  private fade(t: number): LightState[] {
    const seconds = num(this.base, "seconds_per", 2) / this.safeScale();
    const dim = intField(this.base, "dimmer", 255);
    const cols = this.palette.colors.map((slot) => parRgb(slot));
    if (this.n === 2 && cols.length === 2) {
      const pos = t / seconds;
      const u = pos - Math.floor(pos);
      const i = pythonMod(Math.floor(pos), 2);
      const left = i === 0 ? cols[0] : cols[1];
      const right = i === 0 ? cols[1] : cols[0];
      return [mixState(u, left, right, dim), mixState(u, right, left, dim)];
    }
    const nColors = cols.length;
    return Array.from({ length: this.n }, (_, i) => {
      const pos = t / seconds + (this.n ? i / this.n : 0);
      const u = pos - Math.floor(pos);
      const left = cols[pythonMod(Math.floor(pos), nColors)];
      const right = cols[pythonMod(Math.floor(pos) + 1, nColors)];
      return mixState(u, left, right, dim);
    });
  }
}

function mixState(u: number, left: number[], right: number[], dim: number): LightState {
  const rgb = [0, 1, 2].map((i) => Math.min(255, Math.max(0, pythonRound(left[i] + (right[i] - left[i]) * u))));
  return { r: rgb[0], g: rgb[1], b: rgb[2], dimmer: dim, hardOff: false };
}

function beam4(raw: number[]): number[] {
  return [raw[0] ?? 0, raw[1] ?? 0, raw[2] ?? 0, raw[3] ?? 0];
}

function colorFromSeq(seq: Json, index: number, t: number): [number[], number[]] {
  if (listOfObjects(seq, "colors")) {
    const colors = arr(seq, "colors");
    const first = asObj(colors[0], "color");
    if (has(first, "beam")) {
      const hz = num(seq, "flash_hz", 2);
      const picked = asObj(colors[pythonMod(Math.trunc(t * hz), colors.length)], "color");
      const beam = beam4(pad4(picked.beam));
      const halo = has(picked, "halo") ? nums3(picked.halo) : beam.slice(0, 3);
      return [beam, halo];
    }
  }
  if (listOfObjects(seq, "palette")) {
    const palette = arr(seq, "palette");
    const first = asObj(palette[0], "palette");
    if (has(first, "beam")) {
      const periodRaw = num(seq, "color_period", 4);
      const period = periodRaw === 0 ? 4 : periodRaw;
      const n = palette.length;
      const phase = pythonMod(t / period + index / n, n);
      const picked = asObj(palette[Math.trunc(phase) % n], "palette");
      const beam = beam4(pad4(picked.beam));
      const halo = has(picked, "halo") ? nums3(picked.halo) : beam.slice(0, 3);
      return [beam, halo];
    }
  }
  const side = index % 2 === 0 ? asObj(seq.a, "a") : asObj(seq.b, "b");
  return [
    [intField(side, "r"), intField(side, "g"), intField(side, "b"), intField(side, "w")],
    nums3(side.halo),
  ];
}

function firstTruthy(seq: Json, keys: string[], fallback: number): number {
  for (const key of keys) {
    const value = seq[key];
    if (typeof value === "number" && value !== 0) return value;
  }
  return fallback;
}

export function beamFanHeads(seq: Json, n: number, t: number): number[][] {
  const hz = firstTruthy(seq, ["pan_hz", "open_hz", "circle_hz", "tilt_hz"], 0.3);
  const tiltHz = firstTruthy(seq, ["tilt_hz"], hz * 0.6);
  const amp = firstTruthy(seq, ["pan_amp", "spread_max"], 70);
  const tiltAmp = num(seq, "tilt_amp", 35);
  const speed = intField(seq, "speed", 25);
  const dimmer = has(seq, "dimmer") ? intField(seq, "dimmer") : intField(seq, "dimmer_on", 255);
  const strobe = intField(seq, "strobe", 0);
  const heads: number[][] = [];
  for (let i = 0; i < n; i++) {
    const pair = Math.min(i, n - 1 - i);
    const phase = pair / n;
    const sign = i <= (n - 1) / 2 ? 1 : -1;
    const pan = 128 + sign * amp * Math.sin(TWO_PI * (hz * t + phase));
    const tilt = 128 + tiltAmp * Math.sin(TWO_PI * (tiltHz * t + i / n));
    const [color, halo] = colorFromSeq(seq, i, t);
    heads.push(headFrame(pan, tilt, speed, dimmer, strobe, color, halo));
  }
  return heads;
}

function beamFromState(state: LightState): number[] {
  if (state.hardOff || state.dimmer <= 0) {
    const frame = blackoutFrame();
    frame[0] = clamp(128);
    frame[2] = clamp(128);
    return frame;
  }
  return headFrame(128, 128, 180, state.dimmer, 0, [state.r, state.g, state.b, 0], [state.r, state.g, state.b]);
}

function place(buf: number[], start: number, values: number[]): void {
  for (let i = 0; i < values.length; i++) buf[start + i] = values[i];
}

export class ShowPlayer {
  fps = 18;
  lastPose: [number, number][];
  private readonly lpcFx: Fixture[];
  private readonly beamFx: Fixture[];
  private duo: EngineRun["frame"] | null = null;
  private prepared: Json | null = null;
  private lightLpc: LightGesture | null = null;
  private lightBeam: LightGesture | null = null;

  constructor(
    readonly rig: Rig,
    private readonly look: Look,
    private readonly palette: Palette,
    private readonly scale: number,
    beamSequences: Record<string, Json>,
    lpcSequences: Record<string, Json>,
    lastPose: [number, number][] = [],
  ) {
    this.lpcFx = fixturesOf(rig, "lpc");
    this.beamFx = fixturesOf(rig, "beam");
    this.lastPose = lastPose.map((pair) => [pair[0], pair[1]] as [number, number]);
    while (this.lastPose.length < this.beamFx.length) this.lastPose.push([128, 128]);
    if (look.kind === "geometry") {
      const name = strField(look.beam!, "sequence");
      const raw = beamSequences[name];
      if (!raw) throw new Error(`secuencia ausente: ${name}`);
      const seq = prepareSequence(raw, palette, scale);
      this.prepared = seq;
      const n = this.beamFx.length;
      if (n === 1 || n === 2) {
        const run = engineFor(seq);
        this.duo = run.frame.bind(run);
        this.fps = run.fps;
      } else if (n > 2) {
        this.fps = num(seq, "fps", 18);
      }
      return;
    }
    const lpc = look.lpc ?? (() => { throw new Error(`look ${look.id} needs lpc`); })();
    const base: Json = {};
    const seqName = strField(lpc, "sequence", "");
    if (seqName) {
      const raw = lpcSequences[seqName];
      if (!raw) throw new Error(`secuencia ausente: ${seqName}`);
      Object.assign(base, deepClone(raw));
    }
    for (const [key, value] of Object.entries(lpc)) {
      if (key !== "sequence") base[key] = value;
    }
    this.fps = num(base, "fps", 12);
    const engine = strField(base, "engine");
    this.lightLpc = new LightGesture(engine, base, palette, scale, this.lpcFx.length);
    this.lightBeam = new LightGesture(engine, base, palette, scale, this.beamFx.length);
  }

  frame(now: number, t: number): number[] {
    const buf = new Array<number>(this.rig.span).fill(0);
    if (this.look.kind === "geometry") {
      const step = paletteStep(t, this.palette.colors.length, this.scale);
      this.lpcFx.forEach((fixture, i) => {
        const rgb = parRgb(this.palette.colors[(i + step) % this.palette.colors.length]);
        place(buf, fixture.start, lpcBytes(rgb[0], rgb[1], rgb[2]));
      });
      const heads = this.beamHeads(now, t);
      this.beamFx.forEach((fixture, i) => {
        const raw = heads[i];
        place(buf, fixture.start, raw);
        this.lastPose[fixture.index] = [raw[0], raw[2]];
      });
      return buf;
    }
    const lpcStates = this.lightLpc?.states(t) ?? [];
    this.lpcFx.forEach((fixture, i) => {
      const state = lpcStates[i];
      if (!state) return;
      place(buf, fixture.start, lpcBytes(state.r, state.g, state.b, state.dimmer, state.hardOff));
    });
    const beamStates = this.lightBeam?.states(t) ?? [];
    this.beamFx.forEach((fixture, i) => {
      const state = beamStates[i];
      if (!state) return;
      const raw = beamFromState(state);
      place(buf, fixture.start, raw);
      this.lastPose[fixture.index] = [128, 128];
    });
    return buf;
  }

  private beamHeads(now: number, t: number): number[][] {
    const n = this.beamFx.length;
    if (n <= 0) return [];
    let heads: number[][];
    if (n > 2) {
      heads = beamFanHeads(this.prepared!, n, t);
    } else {
      const duoFrame = this.duo!(t, now);
      heads = n === 1 ? [duoFrame.slice(0, BEAM_CH)] : [duoFrame.slice(0, BEAM_CH), duoFrame.slice(BEAM_CH, BEAM_CH * 2)];
    }
    const seq = this.prepared;
    if (seq && !engineCycles(seq) && this.palette.colors.length > 2) {
      const step = paletteStep(t, this.palette.colors.length, this.scale);
      heads.forEach((raw, i) => {
        paintBeamColor(raw, this.palette.colors[(step + i) % this.palette.colors.length]);
      });
    }
    return heads;
  }
}
