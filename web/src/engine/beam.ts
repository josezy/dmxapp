import { blackoutFrame, headFrame, pack } from "./head";
import { arr, boolField, intField, Json, num, nums, objField } from "./json";
import { clamp, lerp, lerpVec, pythonMod } from "./math";

const TWO_PI = Math.PI * 2;

export interface EngineRun {
  fps: number;
  frame(t: number, now: number): number[];
}

function sideBeam(side: Json): number[] {
  return [intField(side, "r"), intField(side, "g"), intField(side, "b"), intField(side, "w")];
}

function sideHalo(side: Json): number[] {
  return nums(side.halo).slice(0, 3);
}

function colorRows(seq: Json, key: string): { beam: number[]; halo: number[] }[] {
  return arr(seq, key).map((item) => {
    const row = objField({ row: item }, "row");
    const beam = nums(row.beam);
    const halo = row.halo != null ? nums(row.halo).slice(0, 3) : beam.slice(0, 3);
    return { beam, halo };
  });
}

/** Wall clock in seconds. Random holds are anchored here, same as Python's clock(). */
function clock(): number {
  return performance.now() / 1000;
}

class RandomHead {
  private readonly palette: { beam: number[]; halo: number[] }[];
  private readonly holdMin: number;
  private readonly holdMax: number;
  private readonly haloAlwaysOn: boolean;
  private readonly haloOffset: number;
  private on: boolean;
  private until: number;
  private idx: number;
  private beam: number[];
  private halo: number[];

  constructor(
    seq: Json,
    options: { haloAlwaysOn?: boolean; haloOffset?: number; now?: number; random?: () => number } = {},
  ) {
    const rng = options.random ?? Math.random;
    this.palette = colorRows(seq, "palette");
    this.holdMin = num(seq, "hold_min", 0.1);
    this.holdMax = num(seq, "hold_max", 1.5);
    this.haloAlwaysOn = options.haloAlwaysOn ?? false;
    this.haloOffset = options.haloOffset ?? 0;
    const now = options.now ?? clock();
    this.on = rng() < 0.5;
    this.until = now + this.uniform(rng);
    this.idx = Math.floor(rng() * this.palette.length);
    const applied = this.apply(this.idx);
    this.beam = applied.beam;
    this.halo = applied.halo;
  }

  private uniform(rng: () => number): number {
    return this.holdMin + rng() * (this.holdMax - this.holdMin);
  }

  private apply(idx: number): { beam: number[]; halo: number[] } {
    const n = this.palette.length;
    this.idx = ((idx % n) + n) % n;
    const beam = this.palette[this.idx].beam.slice();
    const haloI = (this.idx + this.haloOffset) % n;
    const halo = this.palette[haloI].halo.slice();
    return { beam, halo };
  }

  tick(now: number, rng: () => number = Math.random): void {
    if (now < this.until) return;
    this.on = !this.on;
    this.until = now + this.uniform(rng);
    const nxt = Math.floor(rng() * this.palette.length);
    if (this.haloAlwaysOn) {
      this.halo = this.palette[nxt].halo.slice();
      if (this.on) this.beam = this.palette[nxt].beam.slice();
    } else if (this.on) {
      const applied = this.apply(nxt);
      this.beam = applied.beam;
      this.halo = applied.halo;
    }
  }

  dart(dimmerOn: number, dimmerOff: number, dartOffZero: boolean): [number, number[], number[]] {
    if (this.on) return [dimmerOn, this.beam, this.halo];
    if (dartOffZero) return [dimmerOn, [0, 0, 0, 0], this.halo];
    return [dimmerOff, this.beam, this.halo];
  }
}

function sweepPose(seq: Json, t: number): [number, number, number, number] {
  const panC = num(seq, "pan_center", 128);
  const tiltC = num(seq, "tilt_center", 128);
  const panAmp = num(seq, "pan_amp", 90);
  const tiltAmp = num(seq, "tilt_amp", 40);
  const panHz = num(seq, "pan_hz");
  const tiltHz = num(seq, "tilt_hz");
  const sPan = Math.sin(TWO_PI * panHz * t);
  const sTilt = Math.sin(TWO_PI * tiltHz * t);
  const panA = panC + panAmp * sPan;
  const tiltA = tiltC + tiltAmp * sTilt;
  if (boolField(seq, "mirror", true)) {
    return [panA, tiltA, panC - panAmp * sPan, tiltC - tiltAmp * sTilt];
  }
  return [panA, tiltA, panA, tiltA];
}

function haloHand(t: number, hz: number, hand: number[]): number[] {
  const phase = pythonMod(t * hz * 6, 6);
  const i = Math.trunc(phase);
  const frac = phase - i;
  const segs: number[][] = Array.from({ length: 6 }, () => [0, 0, 0]);
  const j = (i + 1) % 6;
  segs[i] = hand.map((c) => clamp(c * (1 - frac)));
  segs[j] = hand.map((c) => clamp(c * frac));
  return segs.flat();
}

function makeSweepMirror(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 20);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const beamA = sideBeam(objField(seq, "a"));
  const haloA = sideHalo(objField(seq, "a"));
  const beamB = sideBeam(objField(seq, "b"));
  const haloB = sideHalo(objField(seq, "b"));
  return {
    fps: num(seq, "fps", 18),
    frame(t) {
      const pose = sweepPose(seq, t);
      return pack(
        headFrame(pose[0], pose[1], speed, dimmer, strobe, beamA, haloA),
        headFrame(pose[2], pose[3], speed, dimmer, strobe, beamB, haloB),
      );
    },
  };
}

function makeSweepFlash(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 20);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const colors = colorRows(seq, "colors");
  const hz = num(seq, "flash_hz", 2);
  return {
    fps: num(seq, "fps", 18),
    frame(t) {
      const i = pythonMod(Math.trunc(t * hz), colors.length);
      const { beam, halo } = colors[i];
      const pose = sweepPose(seq, t);
      return pack(
        headFrame(pose[0], pose[1], speed, dimmer, strobe, beam, halo),
        headFrame(pose[2], pose[3], speed, dimmer, strobe, beam, halo),
      );
    },
  };
}

function makeSweepFade(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 50);
  const dimmer = intField(seq, "dimmer", 180);
  const strobe = intField(seq, "strobe", 0);
  const rows = colorRows(seq, "palette");
  const period = num(seq, "color_period", 4);
  const colorAt = (t: number, pick: "beam" | "halo"): number[] => {
    const n = rows.length;
    const phase = pythonMod(t / period, n);
    const i = Math.trunc(phase);
    const frac = phase - i;
    return lerpVec(rows[i][pick], rows[(i + 1) % n][pick], frac);
  };
  return {
    fps: num(seq, "fps", 16),
    frame(t) {
      const beam = colorAt(t, "beam");
      const halo = colorAt(t, "halo");
      const pose = sweepPose(seq, t);
      return pack(
        headFrame(pose[0], pose[1], speed, dimmer, strobe, beam, halo),
        headFrame(pose[2], pose[3], speed, dimmer, strobe, beam, halo),
      );
    },
  };
}

function makeAbanicoTilt(seq: Json, contra: boolean): EngineRun {
  const speed = intField(seq, "speed", 30);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const panA = num(seq, "pan_a");
  const panB = num(seq, "pan_b");
  const tiltC = num(seq, "tilt_center", 128);
  const tiltAmp = num(seq, "tilt_amp", 70);
  const tiltHz = num(seq, "tilt_hz");
  const beamA = sideBeam(objField(seq, "a"));
  const haloA = sideHalo(objField(seq, "a"));
  const beamB = sideBeam(objField(seq, "b"));
  const haloB = sideHalo(objField(seq, "b"));
  return {
    fps: num(seq, "fps", 18),
    frame(t) {
      const s = Math.sin(TWO_PI * tiltHz * t);
      const ta = tiltC + tiltAmp * s;
      const tb = contra ? tiltC - tiltAmp * s : ta;
      return pack(
        headFrame(panA, ta, speed, dimmer, strobe, beamA, haloA),
        headFrame(panB, tb, speed, dimmer, strobe, beamB, haloB),
      );
    },
  };
}

function makeAbreCierra(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 25);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const openHz = num(seq, "open_hz");
  const tiltHz = num(seq, "tilt_hz");
  const spreadMin = num(seq, "spread_min");
  const spreadMax = num(seq, "spread_max");
  const panC = num(seq, "pan_center", 128);
  const tiltC = num(seq, "tilt_center", 128);
  const tiltAmp = num(seq, "tilt_amp", 35);
  const beamA = sideBeam(objField(seq, "a"));
  const haloA = sideHalo(objField(seq, "a"));
  const beamB = sideBeam(objField(seq, "b"));
  const haloB = sideHalo(objField(seq, "b"));
  return {
    fps: num(seq, "fps", 18),
    frame(t) {
      const k = 0.5 + 0.5 * Math.sin(TWO_PI * openHz * t);
      const spread = spreadMin + (spreadMax - spreadMin) * k;
      const tilt = tiltC + tiltAmp * Math.sin(TWO_PI * tiltHz * t);
      return pack(
        headFrame(panC - spread, tilt, speed, dimmer, strobe, beamA, haloA),
        headFrame(panC + spread, tilt, speed, dimmer, strobe, beamB, haloB),
      );
    },
  };
}

function makeSpin(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 30);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const dps = num(seq, "pan_dps");
  const tiltHz = num(seq, "tilt_hz");
  const tiltAmp = num(seq, "tilt_amp", 30);
  const tiltC = num(seq, "tilt_center", 128);
  const beamA = sideBeam(objField(seq, "a"));
  const haloA = sideHalo(objField(seq, "a"));
  const beamB = sideBeam(objField(seq, "b"));
  const haloB = sideHalo(objField(seq, "b"));
  return {
    fps: num(seq, "fps", 18),
    frame(t) {
      const panA = pythonMod(t * dps, 256);
      const panB = pythonMod(-t * dps, 256);
      const tilt = tiltC + tiltAmp * Math.sin(TWO_PI * tiltHz * t);
      return pack(
        headFrame(panA, tilt, speed, dimmer, strobe, beamA, haloA),
        headFrame(panB, tilt, speed, dimmer, strobe, beamB, haloB),
      );
    },
  };
}

function makeCirculo(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 25);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const hz = num(seq, "circle_hz");
  const panAmp = num(seq, "pan_amp");
  const tiltAmp = num(seq, "tilt_amp");
  const panC = num(seq, "pan_center", 128);
  const tiltC = num(seq, "tilt_center", 128);
  const beamA = sideBeam(objField(seq, "a"));
  const haloA = sideHalo(objField(seq, "a"));
  const beamB = sideBeam(objField(seq, "b"));
  const haloB = sideHalo(objField(seq, "b"));
  const mirror = boolField(seq, "mirror_pan", true);
  return {
    fps: num(seq, "fps", 18),
    frame(t) {
      const w = TWO_PI * hz * t;
      const s = Math.sin(w);
      const c = Math.cos(w);
      const panA = panC + panAmp * s;
      const panB = mirror ? panC - panAmp * s : panA;
      const tilt = tiltC + tiltAmp * c;
      return pack(
        headFrame(panA, tilt, speed, dimmer, strobe, beamA, haloA),
        headFrame(panB, tilt, speed, dimmer, strobe, beamB, haloB),
      );
    },
  };
}

function makeParalelo(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 25);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const panHz = num(seq, "pan_hz");
  const tiltHz = num(seq, "tilt_hz");
  const panAmp = num(seq, "pan_amp");
  const tiltAmp = num(seq, "tilt_amp");
  const panC = num(seq, "pan_center", 128);
  const tiltC = num(seq, "tilt_center", 128);
  const offset = num(seq, "pan_offset", 44);
  const beamA = sideBeam(objField(seq, "a"));
  const haloA = sideHalo(objField(seq, "a"));
  const beamB = sideBeam(objField(seq, "b"));
  const haloB = sideHalo(objField(seq, "b"));
  return {
    fps: num(seq, "fps", 18),
    frame(t) {
      const sweep = panAmp * Math.sin(TWO_PI * panHz * t);
      const tilt = tiltC + tiltAmp * Math.sin(TWO_PI * tiltHz * t);
      return pack(
        headFrame(panC + sweep - offset / 2, tilt, speed, dimmer, strobe, beamA, haloA),
        headFrame(panC + sweep + offset / 2, tilt, speed, dimmer, strobe, beamB, haloB),
      );
    },
  };
}

function makeTirones(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 0);
  const strobe = intField(seq, "strobe", 0);
  const dimOn = intField(seq, "dimmer_on", 255);
  const dimOff = intField(seq, "dimmer_off", 0);
  const panPeriod = num(seq, "pan_period");
  const tiltHz = num(seq, "tilt_hz");
  const panLo = num(seq, "pan_lo");
  const panHi = num(seq, "pan_hi");
  const tiltLo = num(seq, "tilt_lo");
  const tiltHi = num(seq, "tilt_hi");
  const offset = intField(seq, "halo_offset", 2);
  const heads = [new RandomHead(seq, { haloOffset: offset }), new RandomHead(seq, { haloOffset: offset })];
  return {
    fps: num(seq, "fps", 18),
    frame(t, now) {
      for (const head of heads) head.tick(now);
      const phase = pythonMod(t / panPeriod, 1);
      const panA = lerp(panLo, panHi, phase);
      const panB = lerp(panHi, panLo, phase);
      const mid = (tiltLo + tiltHi) / 2;
      const amp = (tiltHi - tiltLo) / 2;
      const tilt = mid + amp * Math.sin(TWO_PI * tiltHz * t);
      const pans = [panA, panB];
      const frames = heads.map((head, i) => {
        const [dim, beam, halo] = head.dart(dimOn, dimOff, false);
        return headFrame(pans[i], tilt, speed, dim, strobe, beam, halo);
      });
      return pack(frames[0], frames[1]);
    },
  };
}

function makeAbanicoRandom(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 30);
  const strobe = intField(seq, "strobe", 0);
  const dimOn = intField(seq, "dimmer_on", 255);
  const dimOff = intField(seq, "dimmer_off", 0);
  const panA = num(seq, "pan_a");
  const panB = num(seq, "pan_b");
  const tiltC = num(seq, "tilt_center", 128);
  const tiltAmp = num(seq, "tilt_amp", 70);
  const tiltHz = num(seq, "tilt_hz");
  const heads = [new RandomHead(seq), new RandomHead(seq)];
  return {
    fps: num(seq, "fps", 18),
    frame(t, now) {
      for (const head of heads) head.tick(now);
      const tilt = tiltC + tiltAmp * Math.sin(TWO_PI * tiltHz * t);
      const pans = [panA, panB];
      const frames = heads.map((head, i) => {
        const [dim, beam, halo] = head.dart(dimOn, dimOff, false);
        return headFrame(pans[i], tilt, speed, dim, strobe, beam, halo);
      });
      return pack(frames[0], frames[1]);
    },
  };
}

function makeAbreRandom(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 25);
  const strobe = intField(seq, "strobe", 0);
  const dimOn = intField(seq, "dimmer_on", 255);
  const dimOff = intField(seq, "dimmer_off", 0);
  const openHz = num(seq, "open_hz");
  const tiltHz = num(seq, "tilt_hz");
  const spreadMin = num(seq, "spread_min");
  const spreadMax = num(seq, "spread_max");
  const panC = num(seq, "pan_center", 128);
  const tiltC = num(seq, "tilt_center", 128);
  const tiltAmp = num(seq, "tilt_amp", 35);
  const heads = [new RandomHead(seq), new RandomHead(seq)];
  return {
    fps: num(seq, "fps", 18),
    frame(t, now) {
      for (const head of heads) head.tick(now);
      const k = 0.5 + 0.5 * Math.sin(TWO_PI * openHz * t);
      const spread = spreadMin + (spreadMax - spreadMin) * k;
      const tilt = tiltC + tiltAmp * Math.sin(TWO_PI * tiltHz * t);
      const pans = [panC - spread, panC + spread];
      const frames = heads.map((head, i) => {
        const [dim, beam, halo] = head.dart(dimOn, dimOff, false);
        return headFrame(pans[i], tilt, speed, dim, strobe, beam, halo);
      });
      return pack(frames[0], frames[1]);
    },
  };
}

function makeCorona(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 30);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const panA = num(seq, "pan_a");
  const panB = num(seq, "pan_b");
  const tiltC = num(seq, "tilt_center", 128);
  const tiltAmp = num(seq, "tilt_amp", 70);
  const tiltHz = num(seq, "tilt_hz");
  const ringHz = num(seq, "ring_hz", 0.7);
  const colorPeriod = num(seq, "color_period", 2.4);
  const hand = nums(seq.hand);
  const beams = colorRows(seq, "palette").map((row) => row.beam);
  return {
    fps: num(seq, "fps", 18),
    frame(t) {
      const tilt = tiltC + tiltAmp * Math.sin(TWO_PI * tiltHz * t);
      const beam = beams[pythonMod(Math.trunc(t / colorPeriod), beams.length)];
      const halo = haloHand(t, ringHz, hand);
      return pack(
        headFrame(panA, tilt, speed, dimmer, strobe, beam, undefined, halo),
        headFrame(panB, tilt, speed, dimmer, strobe, beam, undefined, halo),
      );
    },
  };
}

function makeTironDisco(seq: Json): EngineRun {
  const speed = intField(seq, "speed", 0);
  const dimmer = intField(seq, "dimmer", 255);
  const strobe = intField(seq, "strobe", 0);
  const period = num(seq, "period", 2.2);
  const panA = nums(seq.pan_a);
  const panB = nums(seq.pan_b);
  const tilt = nums(seq.tilt);
  const always = boolField(seq, "halo_always_on", true);
  const heads = [new RandomHead(seq, { haloAlwaysOn: always }), new RandomHead(seq, { haloAlwaysOn: always })];
  const dartZero = boolField(seq, "dart_off_beam_zero", true);
  return {
    fps: num(seq, "fps", 18),
    frame(t, now) {
      for (const head of heads) head.tick(now);
      const phase = pythonMod(t / period, 1);
      const tiltNow = lerp(tilt[0], tilt[1], phase);
      const pans = [lerp(panA[0], panA[1], phase), lerp(panB[0], panB[1], phase)];
      const frames = heads.map((head, i) => {
        const [dim, beam, halo] = head.dart(dimmer, 0, dartZero);
        return headFrame(pans[i], tiltNow, speed, dim, strobe, beam, halo);
      });
      return pack(frames[0], frames[1]);
    },
  };
}

export function engineFor(seq: Json): EngineRun {
  const engine = seq.engine;
  switch (engine) {
    case "sweep_mirror":
    case "unison_search":
      return makeSweepMirror(seq);
    case "sweep_mirror_flash":
      return makeSweepFlash(seq);
    case "sweep_mirror_fade":
      return makeSweepFade(seq);
    case "abanico_tilt":
      return makeAbanicoTilt(seq, false);
    case "contra_tilt":
      return makeAbanicoTilt(seq, true);
    case "simetrico_abre_cierra":
      return makeAbreCierra(seq);
    case "spin_espejo":
      return makeSpin(seq);
    case "circulo_espejo":
      return makeCirculo(seq);
    case "paralelo_search":
      return makeParalelo(seq);
    case "tirones_random_calido":
      return makeTirones(seq);
    case "abanico_random_frio":
      return makeAbanicoRandom(seq);
    case "abre_cierra_random_andino":
      return makeAbreRandom(seq);
    case "corona_reloj_dardo":
      return makeCorona(seq);
    case "abanico_tiron_disco":
      return makeTironDisco(seq);
    default:
      throw new Error(`unknown beam engine ${String(engine)}`);
  }
}

export function previewFrames(seq: Json, count = 24): number[][] {
  const run = engineFor(seq);
  const fps = Math.max(1, run.fps);
  const frames: number[][] = [];
  for (let n = 0; n < count; n++) {
    const t = n / fps;
    frames.push(run.frame(t, t));
  }
  return frames;
}

export { blackoutFrame };
