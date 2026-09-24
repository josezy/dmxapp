#!/usr/bin/env python3
"""Two LED 60W Beam+Halo heads at A001 + A031 (30CH each, 60 bytes)."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

import dmx

ROOT = Path(__file__).resolve().parents[1]
SEQ_DIR = ROOT / "beam-halo-duo" / "sequences"
SHOW_PATH = ROOT / "beam-halo-duo" / "show.json"
START = 0
CH = 30
_OFF = [128, 0, 128, 0, 180, 0, 0, 0, 0, 0, 0] + [0] * 18 + [0]
_last_frame = _OFF + _OFF
clock = time.perf_counter


def load_show() -> dict:
    """Pad layout shared with the Android app (`beam-halo-duo/show.json`)."""
    data = json.loads(SHOW_PATH.read_text(encoding="utf-8"))
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError(f"show.json missing groups: {SHOW_PATH}")
    names: list[str] = []
    for group in groups:
        title = group.get("title")
        scenes = group.get("scenes")
        if not title or not isinstance(scenes, list) or not scenes:
            raise ValueError(f"invalid group in show.json: {group!r}")
        for scene in scenes:
            name = scene.get("name")
            label = scene.get("label")
            if not name or not label:
                raise ValueError(f"invalid scene in {title!r}: {scene!r}")
            names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("duplicate scene names in show.json")
    data["scene_names"] = names
    return data


def clamp(n: float) -> int:
    return max(0, min(255, int(round(n))))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_vec(a, b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(clamp(x + (y - x) * t) for x, y in zip(a, b))


def head_frame(
    pan,
    tilt,
    *,
    speed: int,
    dimmer: int,
    strobe: int,
    beam,
    halo_rgb=None,
    halo_bytes=None,
) -> list[int]:
    r, g, b, w = (clamp(x) for x in beam)
    if halo_bytes is not None:
        halo = [clamp(x) for x in halo_bytes]
    else:
        hr, hg, hb = (clamp(x) for x in halo_rgb)
        halo = [hr, hg, hb] * 6
    if len(halo) != 18:
        raise ValueError("halo must be 18 bytes")
    return [
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
        *halo,
        0,
    ]


def blackout_frame() -> list[int]:
    return [128, 0, 128, 0, 180, 0, 0, 0, 0, 0, 0] + [0] * 18 + [0]


def pack(a: list[int], b: list[int]) -> list[int]:
    return a + b


def blackout_on(dev) -> list[int]:
    values = pack(blackout_frame(), blackout_frame())
    dmx.send_range(dev, START, values)
    _remember(values)
    return values


def _remember(values: list[int]) -> None:
    global _last_frame
    _last_frame = list(values)


def keepalive(dev) -> bool:
    return dmx.send_range_once(dev, START, _last_frame)


def load_sequence(name: str) -> tuple[Path, dict]:
    path = Path(name)
    if not path.is_file():
        path = SEQ_DIR / name
        if not path.suffix:
            path = path.with_suffix(".json")
    return path, json.loads(path.read_text())


def list_sequences() -> list[str]:
    return sorted(p.stem for p in SEQ_DIR.glob("*.json"))


def side_beam(side: dict) -> tuple[int, int, int, int]:
    return (int(side["r"]), int(side["g"]), int(side["b"]), int(side["w"]))


def side_halo(side: dict) -> tuple[int, int, int]:
    h = side["halo"]
    return (int(h[0]), int(h[1]), int(h[2]))


def _link_dead(dev) -> bool:
    if dmx.link_check_due() and not dmx.udmx_handle_ok(dev):
        dmx.mark_usb_dead("No such device")
        return True
    return dmx.usb_is_dead()


def _pump(dev, stop, fps: float, make_frame) -> dict:
    step = 1.0 / max(1.0, float(fps))
    t0 = time.perf_counter()
    n = 0
    fails = 0
    while not dmx.stopped(stop):
        n, halt = dmx.sync_frame(t0, n, step, stop)
        if halt:
            break
        now = time.perf_counter()
        frame = make_frame(now - t0, now)
        if dmx.send_range_once(dev, START, frame):
            _remember(frame)
        else:
            fails += 1
        if _link_dead(dev):
            return {
                "frames": n,
                "usb_fail": fails,
                "stopped": dmx.stopped(stop),
                "usb_dead": True,
            }
        n += 1
    return {
        "frames": n,
        "usb_fail": fails,
        "stopped": dmx.stopped(stop),
        "usb_dead": False,
    }


class RandomHead:
    def __init__(self, seq: dict, *, halo_always_on: bool = False, halo_offset: int = 0):
        self.palette = seq["palette"]
        self.hold_min = float(seq.get("hold_min", 0.1))
        self.hold_max = float(seq.get("hold_max", 1.5))
        self.halo_always_on = halo_always_on
        self.halo_offset = int(halo_offset)
        self.on = random.choice([True, False])
        self.until = clock() + random.uniform(self.hold_min, self.hold_max)
        self.idx = random.randrange(len(self.palette))
        self._apply(self.idx)

    def _apply(self, idx: int) -> None:
        n = len(self.palette)
        self.idx = idx % n
        self.beam = tuple(self.palette[self.idx]["beam"])
        halo_i = (self.idx + self.halo_offset) % n
        self.halo = tuple(self.palette[halo_i]["halo"])

    def tick(self, now: float) -> None:
        if now < self.until:
            return
        self.on = not self.on
        self.until = now + random.uniform(self.hold_min, self.hold_max)
        nxt = random.randrange(len(self.palette))
        if self.halo_always_on:
            self.halo = tuple(self.palette[nxt]["halo"])
            if self.on:
                self.beam = tuple(self.palette[nxt]["beam"])
        elif self.on:
            self._apply(nxt)

    def dart(self, dimmer_on: int, dimmer_off: int, dart_off_zero: bool):
        if self.on:
            return dimmer_on, self.beam, self.halo
        if dart_off_zero:
            return dimmer_on, (0, 0, 0, 0), self.halo
        return dimmer_off, self.beam, self.halo


def _sweep_pose(seq: dict, t: float) -> tuple[float, float, float, float]:
    pan_c = float(seq.get("pan_center", 128))
    tilt_c = float(seq.get("tilt_center", 128))
    pan_amp = float(seq.get("pan_amp", 90))
    tilt_amp = float(seq.get("tilt_amp", 40))
    pan_hz = float(seq["pan_hz"])
    tilt_hz = float(seq["tilt_hz"])
    s_pan = math.sin(2 * math.pi * pan_hz * t)
    s_tilt = math.sin(2 * math.pi * tilt_hz * t)
    pan_a = pan_c + pan_amp * s_pan
    tilt_a = tilt_c + tilt_amp * s_tilt
    if seq.get("mirror", True):
        pan_b = pan_c - pan_amp * s_pan
        tilt_b = tilt_c - tilt_amp * s_tilt
    else:
        pan_b, tilt_b = pan_a, tilt_a
    return pan_a, tilt_a, pan_b, tilt_b


def _make_sweep_mirror(seq: dict):
    speed = int(seq.get("speed", 20))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    beam_a, halo_a = side_beam(seq["a"]), side_halo(seq["a"])
    beam_b, halo_b = side_beam(seq["b"]), side_halo(seq["b"])

    def frame(t, _now):
        pa, ta, pb, tb = _sweep_pose(seq, t)
        return pack(
            head_frame(pa, ta, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_a, halo_rgb=halo_a),
            head_frame(pb, tb, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_b, halo_rgb=halo_b),
        )

    return frame, float(seq.get("fps", 18))


def _make_sweep_flash(seq: dict):
    speed = int(seq.get("speed", 20))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    colors = seq["colors"]
    hz = float(seq.get("flash_hz", 2.0))

    def frame(t, _now):
        i = int(t * hz) % len(colors)
        beam = tuple(colors[i]["beam"])
        halo = tuple(colors[i]["halo"])
        pa, ta, pb, tb = _sweep_pose(seq, t)
        a = head_frame(pa, ta, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam, halo_rgb=halo)
        b = head_frame(pb, tb, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam, halo_rgb=halo)
        return pack(a, b)

    return frame, float(seq.get("fps", 18))


def _make_sweep_fade(seq: dict):
    speed = int(seq.get("speed", 50))
    dimmer = int(seq.get("dimmer", 180))
    strobe = int(seq.get("strobe", 0))
    palette = seq["palette"]
    period = float(seq.get("color_period", 4.0))

    def color_at(t: float, key: str):
        n = len(palette)
        phase = (t / period) % n
        i = int(phase)
        frac = phase - i
        return lerp_vec(palette[i][key], palette[(i + 1) % n][key], frac)

    def frame(t, _now):
        beam = color_at(t, "beam")
        halo = color_at(t, "halo")
        pa, ta, pb, tb = _sweep_pose(seq, t)
        a = head_frame(pa, ta, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam, halo_rgb=halo)
        b = head_frame(pb, tb, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam, halo_rgb=halo)
        return pack(a, b)

    return frame, float(seq.get("fps", 16))


def _make_abanico_tilt(seq: dict, *, contra: bool = False):
    speed = int(seq.get("speed", 30))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    pan_a = float(seq["pan_a"])
    pan_b = float(seq["pan_b"])
    tilt_c = float(seq.get("tilt_center", 128))
    tilt_amp = float(seq.get("tilt_amp", 70))
    tilt_hz = float(seq["tilt_hz"])
    beam_a, halo_a = side_beam(seq["a"]), side_halo(seq["a"])
    beam_b, halo_b = side_beam(seq["b"]), side_halo(seq["b"])

    def frame(t, _now):
        s = math.sin(2 * math.pi * tilt_hz * t)
        ta = tilt_c + tilt_amp * s
        tb = tilt_c - tilt_amp * s if contra else ta
        return pack(
            head_frame(pan_a, ta, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_a, halo_rgb=halo_a),
            head_frame(pan_b, tb, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_b, halo_rgb=halo_b),
        )

    return frame, float(seq.get("fps", 18))


def _make_abre_cierra(seq: dict):
    speed = int(seq.get("speed", 25))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    open_hz = float(seq["open_hz"])
    tilt_hz = float(seq["tilt_hz"])
    spread_min = float(seq["spread_min"])
    spread_max = float(seq["spread_max"])
    pan_c = float(seq.get("pan_center", 128))
    tilt_c = float(seq.get("tilt_center", 128))
    tilt_amp = float(seq.get("tilt_amp", 35))
    beam_a, halo_a = side_beam(seq["a"]), side_halo(seq["a"])
    beam_b, halo_b = side_beam(seq["b"]), side_halo(seq["b"])

    def frame(t, _now):
        k = 0.5 + 0.5 * math.sin(2 * math.pi * open_hz * t)
        spread = spread_min + (spread_max - spread_min) * k
        tilt = tilt_c + tilt_amp * math.sin(2 * math.pi * tilt_hz * t)
        return pack(
            head_frame(pan_c - spread, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_a, halo_rgb=halo_a),
            head_frame(pan_c + spread, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_b, halo_rgb=halo_b),
        )

    return frame, float(seq.get("fps", 18))


def _make_spin_espejo(seq: dict):
    speed = int(seq.get("speed", 30))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    dps = float(seq["pan_dps"])
    tilt_hz = float(seq["tilt_hz"])
    tilt_amp = float(seq.get("tilt_amp", 30))
    tilt_c = float(seq.get("tilt_center", 128))
    beam_a, halo_a = side_beam(seq["a"]), side_halo(seq["a"])
    beam_b, halo_b = side_beam(seq["b"]), side_halo(seq["b"])

    def frame(t, _now):
        pan_a = (t * dps) % 256
        pan_b = (-t * dps) % 256
        tilt = tilt_c + tilt_amp * math.sin(2 * math.pi * tilt_hz * t)
        return pack(
            head_frame(pan_a, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_a, halo_rgb=halo_a),
            head_frame(pan_b, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_b, halo_rgb=halo_b),
        )

    return frame, float(seq.get("fps", 18))


def _make_circulo(seq: dict):
    speed = int(seq.get("speed", 25))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    hz = float(seq["circle_hz"])
    pan_amp = float(seq["pan_amp"])
    tilt_amp = float(seq["tilt_amp"])
    pan_c = float(seq.get("pan_center", 128))
    tilt_c = float(seq.get("tilt_center", 128))
    beam_a, halo_a = side_beam(seq["a"]), side_halo(seq["a"])
    beam_b, halo_b = side_beam(seq["b"]), side_halo(seq["b"])
    mirror = bool(seq.get("mirror_pan", True))

    def frame(t, _now):
        w = 2 * math.pi * hz * t
        s, c = math.sin(w), math.cos(w)
        pan_a = pan_c + pan_amp * s
        pan_b = pan_c - pan_amp * s if mirror else pan_a
        tilt = tilt_c + tilt_amp * c
        return pack(
            head_frame(pan_a, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_a, halo_rgb=halo_a),
            head_frame(pan_b, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_b, halo_rgb=halo_b),
        )

    return frame, float(seq.get("fps", 18))


def _make_paralelo(seq: dict):
    speed = int(seq.get("speed", 25))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    pan_hz = float(seq["pan_hz"])
    tilt_hz = float(seq["tilt_hz"])
    pan_amp = float(seq["pan_amp"])
    tilt_amp = float(seq["tilt_amp"])
    pan_c = float(seq.get("pan_center", 128))
    tilt_c = float(seq.get("tilt_center", 128))
    offset = float(seq.get("pan_offset", 44))
    beam_a, halo_a = side_beam(seq["a"]), side_halo(seq["a"])
    beam_b, halo_b = side_beam(seq["b"]), side_halo(seq["b"])

    def frame(t, _now):
        sweep = pan_amp * math.sin(2 * math.pi * pan_hz * t)
        tilt = tilt_c + tilt_amp * math.sin(2 * math.pi * tilt_hz * t)
        return pack(
            head_frame(pan_c + sweep - offset / 2, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_a, halo_rgb=halo_a),
            head_frame(pan_c + sweep + offset / 2, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam_b, halo_rgb=halo_b),
        )

    return frame, float(seq.get("fps", 18))


def _make_tirones_random(seq: dict):
    speed = int(seq.get("speed", 0))
    strobe = int(seq.get("strobe", 0))
    dim_on = int(seq.get("dimmer_on", 255))
    dim_off = int(seq.get("dimmer_off", 0))
    pan_period = float(seq["pan_period"])
    tilt_hz = float(seq["tilt_hz"])
    pan_lo, pan_hi = float(seq["pan_lo"]), float(seq["pan_hi"])
    tilt_lo, tilt_hi = float(seq["tilt_lo"]), float(seq["tilt_hi"])
    heads = [
        RandomHead(seq, halo_offset=int(seq.get("halo_offset", 2))),
        RandomHead(seq, halo_offset=int(seq.get("halo_offset", 2))),
    ]

    def frame(t, now):
        for h in heads:
            h.tick(now)
        phase = (t / pan_period) % 1.0
        pan_a = lerp(pan_lo, pan_hi, phase)
        pan_b = lerp(pan_hi, pan_lo, phase)
        mid = (tilt_lo + tilt_hi) / 2
        amp = (tilt_hi - tilt_lo) / 2
        tilt = mid + amp * math.sin(2 * math.pi * tilt_hz * t)
        out = []
        for pan, h in ((pan_a, heads[0]), (pan_b, heads[1])):
            dim, beam, halo = h.dart(dim_on, dim_off, False)
            out.append(head_frame(pan, tilt, speed=speed, dimmer=dim, strobe=strobe, beam=beam, halo_rgb=halo))
        return pack(*out)

    return frame, float(seq.get("fps", 18))


def _make_abanico_random(seq: dict):
    speed = int(seq.get("speed", 30))
    strobe = int(seq.get("strobe", 0))
    dim_on = int(seq.get("dimmer_on", 255))
    dim_off = int(seq.get("dimmer_off", 0))
    pan_a = float(seq["pan_a"])
    pan_b = float(seq["pan_b"])
    tilt_c = float(seq.get("tilt_center", 128))
    tilt_amp = float(seq.get("tilt_amp", 70))
    tilt_hz = float(seq["tilt_hz"])
    heads = [RandomHead(seq), RandomHead(seq)]

    def frame(t, now):
        for h in heads:
            h.tick(now)
        tilt = tilt_c + tilt_amp * math.sin(2 * math.pi * tilt_hz * t)
        out = []
        for pan, h in ((pan_a, heads[0]), (pan_b, heads[1])):
            dim, beam, halo = h.dart(dim_on, dim_off, False)
            out.append(head_frame(pan, tilt, speed=speed, dimmer=dim, strobe=strobe, beam=beam, halo_rgb=halo))
        return pack(*out)

    return frame, float(seq.get("fps", 18))


def _make_abre_cierra_random(seq: dict):
    speed = int(seq.get("speed", 25))
    strobe = int(seq.get("strobe", 0))
    dim_on = int(seq.get("dimmer_on", 255))
    dim_off = int(seq.get("dimmer_off", 0))
    open_hz = float(seq["open_hz"])
    tilt_hz = float(seq["tilt_hz"])
    spread_min = float(seq["spread_min"])
    spread_max = float(seq["spread_max"])
    pan_c = float(seq.get("pan_center", 128))
    tilt_c = float(seq.get("tilt_center", 128))
    tilt_amp = float(seq.get("tilt_amp", 35))
    heads = [RandomHead(seq), RandomHead(seq)]

    def frame(t, now):
        for h in heads:
            h.tick(now)
        k = 0.5 + 0.5 * math.sin(2 * math.pi * open_hz * t)
        spread = spread_min + (spread_max - spread_min) * k
        tilt = tilt_c + tilt_amp * math.sin(2 * math.pi * tilt_hz * t)
        out = []
        for pan, h in ((pan_c - spread, heads[0]), (pan_c + spread, heads[1])):
            dim, beam, halo = h.dart(dim_on, dim_off, False)
            out.append(head_frame(pan, tilt, speed=speed, dimmer=dim, strobe=strobe, beam=beam, halo_rgb=halo))
        return pack(*out)

    return frame, float(seq.get("fps", 18))


def _halo_hand(t: float, hz: float, hand) -> list[int]:
    phase = (t * hz * 6.0) % 6.0
    i = int(phase)
    frac = phase - i
    segs = [(0, 0, 0)] * 6
    j = (i + 1) % 6
    segs[i] = tuple(clamp(c * (1.0 - frac)) for c in hand)
    segs[j] = tuple(clamp(c * frac) for c in hand)
    out: list[int] = []
    for rgb in segs:
        out.extend(rgb)
    return out


def _make_corona_reloj(seq: dict):
    speed = int(seq.get("speed", 30))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    pan_a = float(seq["pan_a"])
    pan_b = float(seq["pan_b"])
    tilt_c = float(seq.get("tilt_center", 128))
    tilt_amp = float(seq.get("tilt_amp", 70))
    tilt_hz = float(seq["tilt_hz"])
    ring_hz = float(seq.get("ring_hz", 0.7))
    color_period = float(seq.get("color_period", 2.4))
    hand = tuple(seq["hand"])
    palette = seq["palette"]

    def frame(t, _now):
        tilt = tilt_c + tilt_amp * math.sin(2 * math.pi * tilt_hz * t)
        beam = tuple(palette[int(t / color_period) % len(palette)]["beam"])
        halo = _halo_hand(t, ring_hz, hand)
        a = head_frame(pan_a, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam, halo_bytes=halo)
        b = head_frame(pan_b, tilt, speed=speed, dimmer=dimmer, strobe=strobe, beam=beam, halo_bytes=halo)
        return pack(a, b)

    return frame, float(seq.get("fps", 18))


def _make_abanico_tiron_disco(seq: dict):
    speed = int(seq.get("speed", 0))
    dimmer = int(seq.get("dimmer", 255))
    strobe = int(seq.get("strobe", 0))
    period = float(seq.get("period", 2.2))
    pan_a0, pan_a1 = (float(x) for x in seq["pan_a"])
    pan_b0, pan_b1 = (float(x) for x in seq["pan_b"])
    tilt_lo, tilt_hi = (float(x) for x in seq["tilt"])
    heads = [
        RandomHead(seq, halo_always_on=bool(seq.get("halo_always_on", True))),
        RandomHead(seq, halo_always_on=bool(seq.get("halo_always_on", True))),
    ]
    dart_zero = bool(seq.get("dart_off_beam_zero", True))

    def frame(t, now):
        for h in heads:
            h.tick(now)
        phase = (t / period) % 1.0
        tilt = lerp(tilt_lo, tilt_hi, phase)
        pan_a = lerp(pan_a0, pan_a1, phase)
        pan_b = lerp(pan_b0, pan_b1, phase)
        out = []
        for pan, h in ((pan_a, heads[0]), (pan_b, heads[1])):
            dim, beam, halo = h.dart(dimmer, 0, dart_zero)
            out.append(head_frame(pan, tilt, speed=speed, dimmer=dim, strobe=strobe, beam=beam, halo_rgb=halo))
        return pack(*out)

    return frame, float(seq.get("fps", 18))


FRAME_MAKERS = {
    "sweep_mirror": _make_sweep_mirror,
    "sweep_mirror_flash": _make_sweep_flash,
    "sweep_mirror_fade": _make_sweep_fade,
    "abanico_tilt": lambda seq: _make_abanico_tilt(seq, contra=False),
    "contra_tilt": lambda seq: _make_abanico_tilt(seq, contra=True),
    "unison_search": _make_sweep_mirror,
    "simetrico_abre_cierra": _make_abre_cierra,
    "spin_espejo": _make_spin_espejo,
    "circulo_espejo": _make_circulo,
    "paralelo_search": _make_paralelo,
    "tirones_random_calido": _make_tirones_random,
    "abanico_random_frio": _make_abanico_random,
    "abre_cierra_random_andino": _make_abre_cierra_random,
    "corona_reloj_dardo": _make_corona_reloj,
    "abanico_tiron_disco": _make_abanico_tiron_disco,
}


def frame_maker(seq: dict):
    engine = seq.get("engine")
    fn = FRAME_MAKERS.get(engine)
    if fn is None:
        raise SystemExit(f"unknown beam engine {engine!r}")
    return fn(seq)


def preview_frames(seq: dict, count: int = 24, seed: int = 1) -> list[list[int]]:
    """Generate frames at t=n/fps without USB or sleeping. For golden tests."""
    global clock
    random.seed(seed)
    box = [0.0]
    old = clock
    clock = lambda: box[0]
    try:
        make, fps = frame_maker(seq)
        fps = max(1.0, float(fps))
        out: list[list[int]] = []
        for n in range(count):
            t = n / fps
            box[0] = t
            out.append(list(make(t, t)))
        return out
    finally:
        clock = old


def run_sequence(dev, seq: dict, stop=None) -> dict:
    engine = seq.get("engine")
    make, fps = frame_maker(seq)
    stats = _pump(dev, stop, fps, make)
    stats["engine"] = engine
    return stats


def cmd_list(_: argparse.Namespace) -> None:
    print(json.dumps({"sequences": list_sequences()}, indent=2))


def cmd_blackout(_: argparse.Namespace) -> None:
    dev = dmx.open_udmx()
    try:
        blackout_on(dev)
        print(json.dumps({"ok": True, "blackout": True}))
    finally:
        dmx.close_udmx(dev)


def cmd_play(args: argparse.Namespace) -> None:
    path, seq = load_sequence(args.name)
    print(json.dumps({"playing": str(path), "engine": seq.get("engine")}, indent=2), flush=True)
    dev = dmx.open_udmx()
    try:
        stats = run_sequence(dev, seq)
        print(json.dumps(stats), flush=True)
    except KeyboardInterrupt:
        print(json.dumps({"ok": True, "interrupted": True}), flush=True)
    finally:
        try:
            blackout_on(dev)
        except Exception:
            pass
        dmx.close_udmx(dev)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LED 60W Beam+Halo duo A001+A031")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("blackout").set_defaults(func=cmd_blackout)
    play = sub.add_parser("play")
    play.add_argument("name")
    play.set_defaults(func=cmd_play)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
