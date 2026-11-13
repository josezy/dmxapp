import { clamp } from "./math";

export const BEAM_CH = 30;

export function headFrame(
  pan: number,
  tilt: number,
  speed: number,
  dimmer: number,
  strobe: number,
  beam: number[],
  haloRgb?: number[],
  haloBytes?: number[],
): number[] {
  const r = clamp(beam[0] ?? 0);
  const g = clamp(beam[1] ?? 0);
  const b = clamp(beam[2] ?? 0);
  const w = clamp(beam[3] ?? 0);
  let halo: number[];
  if (haloBytes) {
    halo = haloBytes.map((value) => clamp(value));
  } else {
    if (!haloRgb) throw new Error("falta el halo");
    const hr = clamp(haloRgb[0] ?? 0);
    const hg = clamp(haloRgb[1] ?? 0);
    const hb = clamp(haloRgb[2] ?? 0);
    halo = [];
    for (let i = 0; i < 6; i++) halo.push(hr, hg, hb);
  }
  if (halo.length !== 18) throw new Error("halo must be 18 bytes");
  const out = [
    clamp(pan),
    0,
    clamp(tilt),
    0,
    clamp(speed),
    clamp(dimmer),
    clamp(strobe),
    r,
    g,
    b,
    w,
    ...halo,
    0,
  ];
  if (out.length !== BEAM_CH) throw new Error(`frame de ${out.length} canales`);
  return out;
}

export function blackoutFrame(): number[] {
  const out = new Array<number>(BEAM_CH).fill(0);
  out[0] = 128;
  out[2] = 128;
  out[4] = 180;
  return out;
}

export function pack(a: number[], b: number[]): number[] {
  return a.concat(b);
}
