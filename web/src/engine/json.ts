export type Json = Record<string, unknown>;

export function isObj(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function asObj(value: unknown, key: string): Json {
  if (!isObj(value)) throw new Error(`${key} no es un objeto`);
  return value;
}

export function has(obj: Json, key: string): boolean {
  return obj[key] !== undefined && obj[key] !== null;
}

export function num(obj: Json, key: string, fallback?: number): number {
  if (!has(obj, key)) {
    if (fallback === undefined) throw new Error(`falta ${key}`);
    return fallback;
  }
  const value = obj[key];
  if (typeof value !== "number" || Number.isNaN(value)) throw new Error(`${key} no es un número`);
  return value;
}

export function intField(obj: Json, key: string, fallback?: number): number {
  if (!has(obj, key)) {
    if (fallback === undefined) throw new Error(`falta ${key}`);
    return fallback;
  }
  return Math.trunc(num(obj, key));
}

export function boolField(obj: Json, key: string, fallback: boolean): boolean {
  if (!has(obj, key)) return fallback;
  const value = obj[key];
  if (typeof value !== "boolean") throw new Error(`${key} no es bool`);
  return value;
}

export function strField(obj: Json, key: string, fallback?: string): string {
  if (!has(obj, key)) {
    if (fallback === undefined) throw new Error(`falta ${key}`);
    return fallback;
  }
  const value = obj[key];
  if (typeof value !== "string") throw new Error(`${key} no es texto`);
  return value;
}

export function arr(obj: Json, key: string): unknown[] {
  const value = obj[key];
  if (!Array.isArray(value)) throw new Error(`${key} no es una lista`);
  return value;
}

export function nums(value: unknown): number[] {
  if (!Array.isArray(value)) throw new Error("se esperaba una lista de números");
  return value.map((item) => {
    if (typeof item !== "number") throw new Error("se esperaba un número");
    return Math.trunc(item);
  });
}

export function objField(obj: Json, key: string): Json {
  return asObj(obj[key], key);
}

export function listOfObjects(obj: Json, key: string): boolean {
  const value = obj[key];
  return Array.isArray(value) && value.length > 0 && isObj(value[0]);
}
