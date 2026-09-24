"""One universe buffer from a shared look: palette + speed, LPC and BEAM together.

N=2 beam geometry calls the existing duo engines. N=1 uses head A of that duo.
N>2 fans pan around 128 with phase i/N and mirrored ends. Light looks drive the
PARs and paint the same gesture on the beams, parked at pan/tilt center.
"""

from __future__ import annotations

import copy
import json
import math
import random
import time
from pathlib import Path

import beam_halo_duo as beam
import lpc008_duo as lpc
from show_rig import fixtures_of

ROOT = Path(__file__).resolve().parents[1]
SHOW_DIR = ROOT / "show"
LOOKS_PATH = SHOW_DIR / "looks.json"
PALETTES_PATH = SHOW_DIR / "palettes.json"

RATE_KEYS = (
    "pan_hz",
    "tilt_hz",
    "open_hz",
    "flash_hz",
    "circle_hz",
    "ring_hz",
    "pan_dps",
)
PERIOD_KEYS = ("color_period", "pan_period", "period", "hold_min", "hold_max")
NATIVE_KEYS = ("a", "b", "colors", "palette", "hand")


def load_catalog() -> dict:
    looks = json.loads(LOOKS_PATH.read_text(encoding="utf-8"))
    palettes = json.loads(PALETTES_PATH.read_text(encoding="utf-8"))
    by_id = {}
    for group in looks["groups"]:
        for look in group["looks"]:
            if look["id"] in by_id:
                raise ValueError(f"duplicate look {look['id']}")
            if look.get("kind") == "geometry" and "sequence" not in look.get("beam", {}):
                raise ValueError(f"look {look['id']} needs beam.sequence")
            if look.get("kind") == "light" and "engine" not in look.get("lpc", {}):
                raise ValueError(f"look {look['id']} needs lpc.engine")
            by_id[look["id"]] = look
    pal_by_id = {}
    normalized = []
    for pal in palettes["palettes"]:
        pal = _normalize_palette(pal)
        normalized.append(pal)
        pal_by_id[pal["id"]] = pal
    palettes["palettes"] = normalized
    speeds = {row["id"]: float(row["scale"]) for row in looks["speeds"]}
    if "medio" not in speeds or speeds["medio"] != 1.0:
        raise ValueError("speed 'medio' must be scale 1")
    return {
        "groups": looks["groups"],
        "speeds": looks["speeds"],
        "palettes": palettes["palettes"],
        "looks": by_id,
        "paletteById": pal_by_id,
        "speedById": speeds,
    }


def native_palette(seq: dict) -> dict:
    """Color fields of a beam sequence, so scale 1 can round-trip the goldens."""
    return {"native": {k: copy.deepcopy(seq[k]) for k in NATIVE_KEYS if k in seq}}


def apply_speed(seq: dict, scale: float) -> dict:
    if scale == 1.0:
        return seq
    for key in RATE_KEYS:
        if key in seq:
            seq[key] = float(seq[key]) * scale
    for key in PERIOD_KEYS:
        if key in seq:
            seq[key] = float(seq[key]) / scale
    if "speed" in seq and not isinstance(seq["speed"], bool):
        seq["speed"] = beam.clamp(float(seq["speed"]) * scale)
    return seq


def _slot_beam(rgb: dict) -> dict:
    name = str(rgb.get("name") or "")
    if "beam" in rgb:
        raw = [int(x) for x in rgb["beam"]]
        while len(raw) < 4:
            raw.append(0)
        r, g, b, w = raw[:4]
        halo = rgb.get("halo")
        if halo is None:
            halo = [r, g, b]
    else:
        r, g, b = int(rgb["r"]), int(rgb["g"]), int(rgb["b"])
        w = int(rgb.get("w", 0))
        halo = rgb.get("halo")
        if halo is None:
            halo = [r, g, b]
    return {
        "name": name,
        "r": r,
        "g": g,
        "b": b,
        "w": w,
        "halo": [int(x) for x in halo],
        "beam": [r, g, b, w],
    }


def _normalize_palette(pal: dict) -> dict:
    raw = pal.get("colors")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"palette {pal.get('id')} needs a colors list")
    slots = []
    for i, color in enumerate(raw):
        if "beam" not in color and not all(ch in color for ch in ("r", "g", "b")):
            raise ValueError(f"palette {pal.get('id')} color {i} missing rgb")
        slots.append(_slot_beam(color))
    out = dict(pal)
    out["colors"] = slots
    out["a"] = slots[0]
    out["b"] = slots[1] if len(slots) > 1 else slots[0]
    return out


def _palette_slots(palette: dict) -> list[dict]:
    raw = palette.get("colors")
    if not raw:
        raw = [palette["a"], palette["b"]]
    if raw and isinstance(raw[0], dict) and "beam" in raw[0] and "r" in raw[0]:
        return raw
    return [_slot_beam(color) for color in raw]


def _color_row(slot: dict, index: int) -> dict:
    return {
        "name": slot.get("name") or f"c{index}",
        "beam": list(slot["beam"]),
        "halo": list(slot["halo"]),
    }


def apply_palette(seq: dict, palette: dict | None) -> dict:
    if not palette:
        return seq
    if "native" in palette:
        for key, value in palette["native"].items():
            seq[key] = copy.deepcopy(value)
        return seq
    slots = _palette_slots(palette)
    slot_a = slots[0]
    slot_b = slots[1] if len(slots) > 1 else slots[0]
    if isinstance(seq.get("a"), dict) and "r" in seq["a"]:
        seq["a"] = {**seq["a"], **{k: slot_a[k] for k in ("r", "g", "b", "w", "halo")}}
        seq["b"] = {**seq.get("b", {}), **{k: slot_b[k] for k in ("r", "g", "b", "w", "halo")}}
    rows = [_color_row(slot, i) for i, slot in enumerate(slots)]
    if isinstance(seq.get("colors"), list):
        seq["colors"] = rows
    if isinstance(seq.get("palette"), list):
        seq["palette"] = rows
    return seq


def prepare_beam_sequence(seq: dict, palette: dict | None, scale: float) -> dict:
    out = copy.deepcopy(seq)
    apply_speed(out, scale)
    apply_palette(out, palette)
    return out


def _par_rgb(slot: dict) -> tuple[int, int, int]:
    """PAR has no white diode and no halo, so a white dart with a colored ring reads as the ring."""
    r, g, b = int(slot["r"]), int(slot["g"]), int(slot["b"])
    if r or g or b:
        return r, g, b
    halo = slot.get("halo") or [0, 0, 0]
    if any(int(x) for x in halo):
        return int(halo[0]), int(halo[1]), int(halo[2])
    if int(slot.get("w") or 0):
        return 255, 255, 255
    return 0, 0, 0


def _rgb(palette: dict, index: int) -> tuple[int, int, int]:
    cols = _palette_slots(palette)
    return _par_rgb(cols[index % len(cols)])


COLOR_HOLD = 1.2


def palette_step(t: float, n_colors: int, scale: float) -> int:
    """Slide through a palette. Two colors stay put: one per head."""
    if n_colors <= 2:
        return 0
    hold = COLOR_HOLD / (scale if scale > 0 else 1.0)
    return int(t / hold) % n_colors


def _engine_cycles_colors(seq: dict) -> bool:
    colors = seq.get("colors")
    if isinstance(colors, list) and colors and isinstance(colors[0], dict) and "beam" in colors[0]:
        return True
    listed = seq.get("palette")
    return isinstance(listed, list) and bool(listed) and isinstance(listed[0], dict) and "beam" in listed[0]


def _paint_beam_color(frame: list[int], slot: dict) -> None:
    frame[7:11] = [int(x) for x in slot["beam"][:4]]
    hr, hg, hb = (int(x) for x in slot["halo"][:3])
    frame[11:29] = [hr, hg, hb] * 6


def lpc_bytes(r: int, g: int, b: int, dimmer: int = 255, *, hard_off: bool = False) -> list[int]:
    if hard_off or dimmer <= 0:
        return [0, 0, 0, 0, 0, 0, 0]
    return [int(dimmer), int(r), int(g), int(b), 0, lpc.CH6_LINEAR, 0]


class _Hold:
    def __init__(self, hold_min: float, hold_max: float, n_colors: int) -> None:
        self.hold_min = hold_min
        self.hold_max = hold_max
        self.n_colors = max(1, n_colors)
        self.on = random.choice([True, False])
        self.until = random.uniform(hold_min, hold_max)
        self.slot = random.randrange(self.n_colors)

    def at(self, t: float) -> tuple[bool, int]:
        if t >= self.until:
            self.on = not self.on
            self.slot = random.randrange(self.n_colors)
            self.until = t + random.uniform(self.hold_min, self.hold_max)
        return self.on, self.slot


class LightGesture:
    """Palette-colored light gesture for any head count. N=2 matches the LPC duo phase."""

    def __init__(self, engine: str, base: dict, palette: dict, scale: float, n: int) -> None:
        self.engine = engine
        self.base = base
        self.palette = palette
        self.scale = scale if scale > 0 else 1.0
        self.n = n
        self.fps = float(base.get("fps", 12))
        self._bolts = []
        self._holds: list[_Hold] = []
        if engine == "lightning" and n:
            gap_min = float(base.get("gap_min", 0.5)) / self.scale
            gap_max = float(base.get("gap_max", 2.4)) / self.scale
            colors = [_rgb_dict(palette, i) for i in range(len(_palette_slots(palette)))]
            kw = dict(
                gap_min=gap_min,
                gap_max=max(gap_max, gap_min),
                fps=self.fps,
                flash_min=float(base.get("flash_min", 0.05)) / self.scale,
                flash_max=float(base.get("flash_max", 0.14)) / self.scale,
                bursts_min=int(base.get("bursts_min", 1)),
                bursts_max=int(base.get("bursts_max", 3)),
                burst_gap_min=float(base.get("burst_gap_min", 0.04)) / self.scale,
                burst_gap_max=float(base.get("burst_gap_max", 0.11)) / self.scale,
            )
            self._bolts = [lpc._Bolt(colors, **kw) for _ in range(n)]
        if engine == "random" and n:
            lo = float(base.get("holdMin", base.get("hold_min", 0.35))) / self.scale
            hi = float(base.get("holdMax", base.get("hold_max", 1.4))) / self.scale
            n_colors = len(_palette_slots(palette))
            self._holds = [_Hold(lo, max(hi, lo), n_colors) for _ in range(n)]

    def states(self, t: float) -> list[dict]:
        n = self.n
        if n <= 0:
            return []
        if self.engine == "dual_breathe":
            return self._breathe(t)
        if self.engine == "alt_strobe":
            return self._strobe(t)
        if self.engine == "chase":
            return self._chase(t)
        if self.engine == "dual_fade":
            return self._fade(t)
        if self.engine == "lightning":
            return self._lightning(t)
        if self.engine == "random":
            return self._random(t)
        raise ValueError(f"unknown light engine {self.engine!r}")

    def _dimmer_span(self) -> tuple[int, int]:
        return int(self.base.get("dimmer_lo", 50)), int(self.base.get("dimmer_hi", 255))

    def _breathe(self, t: float) -> list[dict]:
        period = float(self.base.get("period", 5.0)) / self.scale
        lo, hi = self._dimmer_span()
        out = []
        if self.n == 2:
            u = 0.5 + 0.5 * math.sin(2 * math.pi * t / period - math.pi / 2)
            dims = (
                int(round(lo + (hi - lo) * u)),
                int(round(lo + (hi - lo) * (1.0 - u))),
            )
        else:
            dims = []
            for i in range(self.n):
                u = 0.5 + 0.5 * math.sin(
                    2 * math.pi * (t / period + i / self.n) - math.pi / 2
                )
                dims.append(int(round(lo + (hi - lo) * u)))
        n_colors = len(_palette_slots(self.palette))
        step = palette_step(t, n_colors, self.scale)
        for i, dim in enumerate(dims):
            r, g, b = _rgb(self.palette, i + step)
            out.append({"r": r, "g": g, "b": b, "dimmer": dim, "hard_off": False})
        return out

    def _strobe(self, t: float) -> list[dict]:
        hz = float(self.base.get("hz", 1.0)) * self.scale
        n_colors = len(_palette_slots(self.palette))
        if self.n == 2 and n_colors == 2:
            stage = int(t * hz * 4) % 4
            picks = [(0, False), (None, True), (1, False), (None, True)]
            slot, off = picks[stage]
            out = []
            for i in range(2):
                if off or slot != i:
                    out.append({"r": 0, "g": 0, "b": 0, "dimmer": 0, "hard_off": True})
                else:
                    r, g, b = _rgb(self.palette, i)
                    out.append({"r": r, "g": g, "b": b, "dimmer": 255, "hard_off": False})
            return out
        out = []
        for i in range(self.n):
            phase = (t * hz + i / max(self.n, 1)) % 1.0
            if phase < 0.25:
                r, g, b = _rgb(self.palette, i + int(t * hz))
                out.append({"r": r, "g": g, "b": b, "dimmer": 255, "hard_off": False})
            else:
                out.append({"r": 0, "g": 0, "b": 0, "dimmer": 0, "hard_off": True})
        return out

    def _chase(self, t: float) -> list[dict]:
        hz = float(self.base.get("hz", 1.0)) * self.scale
        n_colors = len(_palette_slots(self.palette))
        if self.n == 2 and n_colors == 2:
            swap = int(t * hz * 2) % 2
            out = []
            for i in range(2):
                r, g, b = _rgb(self.palette, i ^ swap)
                out.append({"r": r, "g": g, "b": b, "dimmer": 255, "hard_off": False})
            return out
        step = int(t * hz * n_colors) % n_colors
        out = []
        for i in range(self.n):
            r, g, b = _rgb(self.palette, i + step)
            out.append({"r": r, "g": g, "b": b, "dimmer": 255, "hard_off": False})
        return out

    def _fade(self, t: float) -> list[dict]:
        seconds = float(self.base.get("seconds_per", 2.0)) / self.scale
        dim = int(self.base.get("dimmer", 255))
        cols = [_rgb(self.palette, i) for i in range(len(_palette_slots(self.palette)))]

        def mix(u: float, left, right) -> tuple[int, int, int]:
            return tuple(int(round(x + (y - x) * u)) for x, y in zip(left, right))

        out = []
        if self.n == 2 and len(cols) == 2:
            a, b = cols
            pos = t / seconds
            u = pos - math.floor(pos)
            i = int(math.floor(pos)) % 2
            left = a if i == 0 else b
            right = b if i == 0 else a
            pair = (mix(u, left, right), mix(u, right, left))
            for rgb in pair:
                r, g, bch = rgb
                out.append({"r": r, "g": g, "b": bch, "dimmer": dim, "hard_off": False})
            return out
        n_colors = len(cols)
        for i in range(self.n):
            pos = t / seconds + (i / self.n if self.n else 0)
            u = pos - math.floor(pos)
            left = cols[int(math.floor(pos)) % n_colors]
            right = cols[(int(math.floor(pos)) + 1) % n_colors]
            r, g, bch = mix(u, left, right)
            out.append({"r": r, "g": g, "b": bch, "dimmer": dim, "hard_off": False})
        return out

    def _lightning(self, t: float) -> list[dict]:
        out = []
        for bolt in self._bolts:
            look = bolt.look_at(t)
            hard = int(look.get("feature", 0)) == 0 and int(look.get("dimmer", 0)) == 0
            out.append(
                {
                    "r": int(look.get("r", 0)),
                    "g": int(look.get("g", 0)),
                    "b": int(look.get("b", 0)),
                    "dimmer": 0 if hard else int(look.get("dimmer", 255)),
                    "hard_off": hard,
                }
            )
        return out

    def _random(self, t: float) -> list[dict]:
        out = []
        for hold in self._holds:
            on, slot = hold.at(t)
            if not on:
                out.append({"r": 0, "g": 0, "b": 0, "dimmer": 0, "hard_off": True})
                continue
            r, g, b = _rgb(self.palette, slot)
            out.append({"r": r, "g": g, "b": b, "dimmer": 255, "hard_off": False})
        return out


def _rgb_dict(palette: dict, index: int) -> dict:
    r, g, b = _rgb(palette, index)
    return {"r": r, "g": g, "b": b}


def _beam_color_from_seq(seq: dict, index: int, t: float) -> tuple[tuple, tuple]:
    colors = seq.get("colors")
    if isinstance(colors, list) and colors and isinstance(colors[0], dict) and "beam" in colors[0]:
        hz = float(seq.get("flash_hz", 2.0))
        picked = colors[int(t * hz) % len(colors)]
        return tuple(picked["beam"]), tuple(picked["halo"])
    palette = seq.get("palette")
    if isinstance(palette, list) and palette and isinstance(palette[0], dict) and "beam" in palette[0]:
        period = float(seq.get("color_period", 4.0)) or 4.0
        n = len(palette)
        phase = (t / period + index / n) % n
        picked = palette[int(phase) % n]
        halo = picked.get("halo") or list(picked["beam"][:3])
        return tuple(picked["beam"]), tuple(halo)
    side = seq["a"] if index % 2 == 0 else seq["b"]
    return beam.side_beam(side), beam.side_halo(side)


def beam_fan_heads(seq: dict, n: int, t: float) -> list[list[int]]:
    """Generic spatial rule for N>2. Ends mirror; phase is i/N."""
    hz = float(
        seq.get("pan_hz")
        or seq.get("open_hz")
        or seq.get("circle_hz")
        or seq.get("tilt_hz")
        or 0.3
    )
    tilt_hz = float(seq.get("tilt_hz") or hz * 0.6)
    amp = float(seq.get("pan_amp") or seq.get("spread_max") or 70)
    tilt_amp = float(seq.get("tilt_amp") or 35)
    speed = int(seq.get("speed", 25))
    dimmer = int(seq.get("dimmer", seq.get("dimmer_on", 255)))
    strobe = int(seq.get("strobe", 0))
    heads = []
    for i in range(n):
        pair = min(i, n - 1 - i)
        phase = pair / n
        sign = 1.0 if i <= (n - 1) / 2.0 else -1.0
        pan = 128 + sign * amp * math.sin(2 * math.pi * (hz * t + phase))
        tilt = 128 + tilt_amp * math.sin(2 * math.pi * (tilt_hz * t + i / n))
        color, halo = _beam_color_from_seq(seq, i, t)
        heads.append(
            beam.head_frame(
                pan,
                tilt,
                speed=speed,
                dimmer=dimmer,
                strobe=strobe,
                beam=color,
                halo_rgb=halo,
            )
        )
    return heads


def beam_from_state(state: dict, pan: float, tilt: float) -> list[int]:
    if state["hard_off"] or state["dimmer"] <= 0:
        frame = beam.blackout_frame()
        frame[0] = beam.clamp(pan)
        frame[2] = beam.clamp(tilt)
        return frame
    return beam.head_frame(
        pan,
        tilt,
        speed=180,
        dimmer=state["dimmer"],
        strobe=0,
        beam=(state["r"], state["g"], state["b"], 0),
        halo_rgb=(state["r"], state["g"], state["b"]),
    )


def palette_hold_heads(palette: dict, n: int, t: float = 0.0, scale: float = 1.0) -> list[list[int]]:
    step = palette_step(t, len(_palette_slots(palette)), scale)
    out = []
    for i in range(n):
        r, g, b = _rgb(palette, i + step)
        out.append(lpc_bytes(r, g, b, 255))
    return out


class ShowPlayer:
    def __init__(
        self,
        rig: dict,
        look: dict,
        palette: dict,
        scale: float,
        last_pose: list[tuple[float, float]] | None = None,
    ) -> None:
        self.rig = rig
        self.look = look
        self.palette = palette
        self.scale = scale
        self.kind = look["kind"]
        self.lpc_fx = fixtures_of(rig, "lpc")
        self.beam_fx = fixtures_of(rig, "beam")
        self.fps = 18.0
        self._duo = None
        self._seq = None
        self._light_lpc = None
        self._light_beam = None
        self.last_pose = list(last_pose or [])
        while len(self.last_pose) < len(self.beam_fx):
            self.last_pose.append((128.0, 128.0))
        self._build()

    def _build(self) -> None:
        if self.kind == "geometry":
            _path, seq = beam.load_sequence(self.look["beam"]["sequence"])
            prepared = prepare_beam_sequence(seq, self.palette, self.scale)
            self._seq = prepared
            n = len(self.beam_fx)
            if n == 1 or n == 2:
                fn, fps = beam.frame_maker(prepared)
                self._duo = fn
                self.fps = fps
            elif n > 2:
                self.fps = float(prepared.get("fps", 18))
            return
        base = dict(self.look["lpc"])
        if base.get("sequence"):
            _path, seq = lpc.load_sequence(base["sequence"])
            base = {**seq, **{k: v for k, v in base.items() if k != "sequence"}}
        self.fps = float(base.get("fps", 12))
        self._light_lpc = LightGesture(base["engine"], base, self.palette, self.scale, len(self.lpc_fx))
        self._light_beam = LightGesture(base["engine"], base, self.palette, self.scale, len(self.beam_fx))

    def frame(self, now: float, t: float) -> list[int]:
        buf = [0] * self.rig["span"]
        if self.kind == "geometry":
            held = palette_hold_heads(self.palette, len(self.lpc_fx), t, self.scale)
            for fx, raw in zip(self.lpc_fx, held):
                _place(buf, fx["start"], raw)
            heads = self._beam_heads(t, now)
            for fx, raw in zip(self.beam_fx, heads):
                _place(buf, fx["start"], raw)
                self.last_pose[fx["index"]] = (float(raw[0]), float(raw[2]))
            return buf
        lpc_states = self._light_lpc.states(t) if self._light_lpc else []
        for fx, state in zip(self.lpc_fx, lpc_states):
            _place(
                buf,
                fx["start"],
                lpc_bytes(state["r"], state["g"], state["b"], state["dimmer"], hard_off=state["hard_off"]),
            )
        beam_states = self._light_beam.states(t) if self._light_beam else []
        for fx, state in zip(self.beam_fx, beam_states):
            raw = beam_from_state(state, 128, 128)
            _place(buf, fx["start"], raw)
            self.last_pose[fx["index"]] = (128.0, 128.0)
        return buf

    def _beam_heads(self, t: float, now: float) -> list[list[int]]:
        n = len(self.beam_fx)
        if n <= 0:
            return []
        if n > 2:
            heads = beam_fan_heads(self._seq, n, t)
        else:
            duo = self._duo(t, now)
            heads = [duo[: beam.CH]] if n == 1 else [duo[: beam.CH], duo[beam.CH : beam.CH * 2]]
        self._recolor_static(heads, t)
        return heads

    def _recolor_static(self, heads: list[list[int]], t: float) -> None:
        """a/b engines bake two colors. A longer palette has to be painted each frame."""
        if self._seq is None or _engine_cycles_colors(self._seq):
            return
        slots = _palette_slots(self.palette)
        if len(slots) <= 2:
            return
        step = palette_step(t, len(slots), self.scale)
        for i, raw in enumerate(heads):
            _paint_beam_color(raw, slots[(step + i) % len(slots)])


def _place(buf: list[int], start: int, values: list[int]) -> None:
    buf[start : start + len(values)] = values


def blackout_buffer(rig: dict) -> list[int]:
    buf = [0] * rig["span"]
    for fx in rig["fixtures"]:
        if fx["type"] == "beam":
            _place(buf, fx["start"], beam.blackout_frame())
    return buf


def preview_beam_duo(seq: dict, palette: dict | None, scale: float, count: int = 24, seed: int = 1) -> list[list[int]]:
    """N=2 beam frames through prepare + the existing preview clock. For goldens."""
    prepared = prepare_beam_sequence(seq, palette, scale)
    return beam.preview_frames(prepared, count=count, seed=seed)
