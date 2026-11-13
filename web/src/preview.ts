import type { Rig } from "./engine/show";

function rgb(r: number, g: number, b: number, dimmer = 255): string {
  const k = Math.max(0, Math.min(255, dimmer)) / 255;
  return `rgb(${Math.round(r * k)}, ${Math.round(g * k)}, ${Math.round(b * k)})`;
}

function beamColor(frame: number[], start: number): string {
  const dim = frame[start + 5] ?? 0;
  const r = frame[start + 7] ?? 0;
  const g = frame[start + 8] ?? 0;
  const b = frame[start + 9] ?? 0;
  const w = frame[start + 10] ?? 0;
  if (r || g || b) return rgb(r, g, b, dim);
  if (w) return rgb(255, 255, 255, Math.round((dim * w) / 255));
  return rgb(0, 0, 0, 0);
}

export function renderPreview(root: HTMLElement, rig: Rig, frame: number[]): void {
  root.replaceChildren();
  if (!rig.fixtures.length || frame.length < rig.span) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Elige un look para ver los canales.";
    root.append(empty);
    return;
  }

  const stage = document.createElement("div");
  stage.className = "stage";
  for (const fixture of rig.fixtures) {
    const card = document.createElement("article");
    card.className = "fixture";
    const title = document.createElement("h3");
    title.textContent = `${fixture.type === "lpc" ? "PAR" : "BEAM"} ${fixture.label}`;
    card.append(title);
    if (fixture.type === "lpc") {
      const dim = frame[fixture.start] ?? 0;
      const swatch = document.createElement("div");
      swatch.className = "par";
      swatch.style.background = rgb(frame[fixture.start + 1] ?? 0, frame[fixture.start + 2] ?? 0, frame[fixture.start + 3] ?? 0, dim);
      card.append(swatch);
    } else {
      card.append(beamWidget(frame, fixture.start));
    }
    const nums = document.createElement("p");
    nums.className = "bytes";
    const slice = frame.slice(fixture.start, fixture.start + fixture.channels);
    nums.textContent = slice.map((value, index) => `${fixture.address + index}:${value}`).join(" ");
    card.append(nums);
    stage.append(card);
  }
  root.append(stage);

  const bars = document.createElement("div");
  bars.className = "bars";
  bars.title = "Valor de cada canal del frame, del 0 al 255";
  frame.slice(0, rig.span).forEach((value, index) => {
    const bar = document.createElement("i");
    bar.style.height = `${Math.max(2, Math.round((value / 255) * 48))}px`;
    bar.title = `canal ${index + 1} = ${value}`;
    bars.append(bar);
  });
  root.append(bars);
}

function beamWidget(frame: number[], start: number): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "beam";
  const pan = frame[start] ?? 128;
  const tilt = frame[start + 2] ?? 128;
  const dot = document.createElement("div");
  dot.className = "dot";
  dot.style.left = `${((pan - 128) / 128) * 42 + 50}%`;
  dot.style.top = `${((tilt - 128) / 128) * 42 + 50}%`;
  dot.style.background = beamColor(frame, start);
  const ring = document.createElement("div");
  ring.className = "halo";
  for (let seg = 0; seg < 6; seg++) {
    const piece = document.createElement("span");
    const base = start + 11 + seg * 3;
    const dim = frame[start + 5] ?? 0;
    piece.style.background = rgb(frame[base] ?? 0, frame[base + 1] ?? 0, frame[base + 2] ?? 0, dim);
    ring.append(piece);
  }
  wrap.append(ring, dot);
  return wrap;
}
