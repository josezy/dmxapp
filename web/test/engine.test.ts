import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { engineFor } from "../src/engine/beam";
import { blackoutFrame } from "../src/engine/head";
import type { Json } from "../src/engine/json";
import { clamp, pythonRound } from "../src/engine/math";
import {
  buildRig,
  loadCatalog,
  prepareSequence,
  RigError,
  ShowPlayer,
} from "../src/engine/show";
import { explainUsbFailure } from "../src/usb";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const goldenDir = path.join(repo, "android/app/src/test/resources/goldens");
const beamDir = path.join(repo, "beam-halo-duo/sequences");
const lpcDir = path.join(repo, "lpc008-duo/sequences");

function readJson(file: string): Json {
  return JSON.parse(readFileSync(file, "utf8")) as Json;
}

function readDir(dir: string): Record<string, Json> {
  const out: Record<string, Json> = {};
  for (const name of readdirSync(dir)) {
    if (!name.endsWith(".json")) continue;
    out[name.replace(/\.json$/, "")] = readJson(path.join(dir, name));
  }
  return out;
}

const beams = readDir(beamDir);
const lpcs = readDir(lpcDir);
const catalog = loadCatalog(readJson(path.join(repo, "show/looks.json")), readJson(path.join(repo, "show/palettes.json")));

describe("python round", () => {
  it("matches CPython 3 half-to-even", () => {
    expect(pythonRound(0.4)).toBe(0);
    expect(pythonRound(0.5)).toBe(0);
    expect(pythonRound(1.5)).toBe(2);
    expect(pythonRound(2.5)).toBe(2);
    expect(pythonRound(3.5)).toBe(4);
    expect(pythonRound(127.5)).toBe(128);
    expect(pythonRound(126.5)).toBe(126);
    expect(pythonRound(-0.5)).toBe(0);
    expect(pythonRound(-1.5)).toBe(-2);
    expect(clamp(-1.5)).toBe(0);
    expect(clamp(300)).toBe(255);
  });
});

describe("beam goldens", () => {
  const files = readdirSync(goldenDir).filter((name) => name.endsWith(".json")).sort();

  it("has the deterministic set", () => {
    expect(files.length).toBeGreaterThanOrEqual(14);
  });

  for (const file of files) {
    it(file, () => {
      const golden = readJson(path.join(goldenDir, file));
      const name = String(golden.sequence);
      const seq = beams[name];
      const run = engineFor(seq);
      expect(run.fps).toBe(golden.fps);
      const frames = golden.frames as number[][];
      expect(frames).toHaveLength(24);
      frames.forEach((want, n) => {
        const t = n / run.fps;
        expect(run.frame(t, t), `${name} frame ${n}`).toEqual(want);
      });
    });
  }
});

describe("random engines", () => {
  it("emits 60 channels without a CPython seed", () => {
    for (const name of ["tirones-random-calido", "abanico-random-frio", "abre-cierra-random-andino", "abanico-tiron-disco"]) {
      const run = engineFor(beams[name]);
      for (const t of [0, 1]) {
        const frame = run.frame(t, t);
        expect(frame, name).toHaveLength(60);
        expect(frame.every((value) => value >= 0 && value <= 255)).toBe(true);
      }
    }
  });
});

describe("show console", () => {
  it("maps the rig the same way as Python", () => {
    const duo = buildRig(0, 2);
    expect(duo.fixtures.map((fixture) => fixture.address)).toEqual([1, 31]);
    expect(duo.span).toBe(60);
    const pars = buildRig(2, 0);
    expect(pars.fixtures.map((fixture) => fixture.address)).toEqual([1, 8]);
    expect(pars.span).toBe(14);
    const mixed = buildRig(2, 2, "lpc_first");
    expect(mixed.fixtures.map((fixture) => fixture.label)).toEqual(["A001", "A008", "A015", "A045"]);
    expect(mixed.span).toBe(74);
    const flipped = buildRig(2, 2, "beam_first");
    expect(flipped.fixtures.map((fixture) => fixture.address)).toEqual([1, 31, 61, 68]);
    expect(() => buildRig(9, 0)).toThrow(RigError);
  });

  it("paints sangre on two PARs and cycles disco", () => {
    const sangre = catalog.paletteById.get("sangre");
    const disco = catalog.paletteById.get("disco");
    if (!sangre || !disco) throw new Error("paletas");
    const pars = new ShowPlayer(buildRig(2, 0), catalog.looks.get("abre-cierra")!, sangre, 1, beams, lpcs);
    const buf = pars.frame(0, 0);
    expect(buf.slice(0, 7)).toEqual([255, 255, 0, 8, 0, 25, 0]);
    expect(buf.slice(7, 14)).toEqual([255, 200, 0, 0, 0, 25, 0]);

    const cycling = new ShowPlayer(buildRig(0, 2), catalog.looks.get("abre-cierra")!, disco, 1, beams, lpcs);
    const seen = new Set(
      [0, 1, 2, 3, 4].map((i) => JSON.stringify(cycling.frame(i * 1.2, i * 1.2).slice(7, 11))),
    );
    expect(seen).toEqual(new Set(disco.colors.map((slot) => JSON.stringify(slot.beam))));

    const light = new ShowPlayer(
      buildRig(2, 1),
      catalog.looks.get("breathe")!,
      catalog.paletteById.get("calida")!,
      1,
      beams,
      lpcs,
      [[20, 200]],
    );
    const frame = light.frame(1, 0.4);
    expect(frame).toHaveLength(44);
    expect(frame[0]).toBeGreaterThan(0);
    expect(frame[14]).toBe(128);
    expect(frame[16]).toBe(128);
  });

  it("scales golpe and repaints disco onto corona and tirón", () => {
    const golpe = beams["golpe-blanco"];
    const fast = prepareSequence(golpe, null, 2);
    expect(fast.pan_hz).toBeCloseTo((golpe.pan_hz as number) * 2, 9);
    expect(fast.speed).toBe(clamp((golpe.speed as number) * 2));

    const disco = catalog.paletteById.get("disco");
    if (!disco) throw new Error("disco");
    const painted = prepareSequence(beams["abanico-tiron-disco"], disco, 1);
    const rows = painted.palette as { beam: number[]; halo: number[] }[];
    expect(rows).toHaveLength(5);
    expect(rows[0].beam).toEqual([255, 0, 160, 0]);
    expect(rows[0].halo).toEqual([0, 230, 240]);
    expect(rows[4].halo).toEqual([255, 220, 0]);

    const crowned = prepareSequence(beams["corona-reloj-dardo"], disco, 1);
    expect(crowned.palette).toHaveLength(5);
    expect(crowned.hand).toEqual(beams["corona-reloj-dardo"].hand);
  });

  it("matches Python ShowPlayer frames", () => {
    const fixture = JSON.parse(readFileSync(path.join(repo, "web/test/fixtures/show-frames.json"), "utf8")) as {
      cases: {
        name: string;
        nLpc: number;
        nBeam: number;
        order: string;
        look: string;
        palette: string;
        scale: number;
        fps: number;
        samples: { t: number; now: number; frame: number[] }[];
      }[];
    };
    for (const item of fixture.cases) {
      const player = new ShowPlayer(
        buildRig(item.nLpc, item.nBeam, item.order),
        catalog.looks.get(item.look)!,
        catalog.paletteById.get(item.palette)!,
        item.scale,
        beams,
        lpcs,
      );
      expect(player.fps, item.name).toBe(item.fps);
      for (const sample of item.samples) {
        expect(player.frame(sample.now, sample.t), `${item.name} t=${sample.t}`).toEqual(sample.frame);
      }
    }
  });

  it("parks a beam blackout at pan/tilt 128", () => {
    const frame = blackoutFrame();
    expect(frame[0]).toBe(128);
    expect(frame[2]).toBe(128);
    expect(frame[4]).toBe(180);
    expect(frame[5]).toBe(0);
  });
});

describe("usb hints", () => {
  it("points Windows at Zadig when the device is missing", () => {
    const hint = explainUsbFailure(new DOMException("no device selected", "NotFoundError"), "abrir");
    expect(hint.hint).toMatch(/WinUSB/);
    expect(hint.hint).toMatch(/16C0:05DC/);
    expect(hint.hint).toMatch(/pyusb/);
  });
});
