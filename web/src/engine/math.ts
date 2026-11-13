/** Python 3 round (ties to even), then the 0–255 clamp used by the beam engine. */

export function pythonRound(n: number): number {
  if (Number.isNaN(n)) return 0;
  const fl = Math.floor(n);
  const frac = n - fl;
  if (frac > 0.5) return fl + 1;
  if (frac < 0.5) return fl;
  return fl % 2 === 0 ? fl : fl + 1;
}

export function clamp(n: number): number {
  return Math.min(255, Math.max(0, pythonRound(n)));
}

export function clampInt(n: number): number {
  return Math.min(255, Math.max(0, Math.trunc(n)));
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function lerpVec(a: number[], b: number[], t: number): number[] {
  const u = Math.min(1, Math.max(0, t));
  return a.map((x, i) => clamp(x + ((b[i] ?? 0) - x) * u));
}

/** Python `a % m` for floats: result in [0, m). */
export function pythonMod(a: number, m: number): number {
  const r = a % m;
  return r < 0 ? r + m : r;
}

export function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
