#!/usr/bin/env python3
"""Two LPC008 PARs at A001 (ch1-7) and A008 (ch8-14). Complementary A vs B."""

from __future__ import annotations

import json
import math
import queue
import random
import threading
import time
from pathlib import Path

import dmx

ROOT = Path(__file__).resolve().parents[1]
LOOKS_DIR = ROOT / "lpc008-duo" / "looks"
SEQ_DIR = ROOT / "lpc008-duo" / "sequences"
START = 0
CH6_LINEAR = 25
_last_frame = [0] * 14


def seven(look: dict) -> list[int]:
    data = {k: v for k, v in look.items() if not str(k).startswith("_")}
    return [
        int(data.get("dimmer", 255)),
        int(data.get("r", 0)),
        int(data.get("g", 0)),
        int(data.get("b", 0)),
        0,
        int(data.get("feature", CH6_LINEAR)),
        int(data.get("speed", 0)),
    ]


def pack(a: dict, b: dict) -> list[int]:
    return seven(a) + seven(b)


def rgb(r: int, g: int, b: int, dimmer: int = 255) -> dict:
    return {"dimmer": dimmer, "r": r, "g": g, "b": b, "feature": CH6_LINEAR, "speed": 0}


def hard_off() -> dict:
    return {"dimmer": 0, "r": 0, "g": 0, "b": 0, "feature": 0, "speed": 0}


def send(dev, values: list[int]) -> None:
    global _last_frame
    sent = dmx.send_range(dev, START, values)
    if sent != len(values):
        raise SystemExit(f"short write: {sent}/{len(values)}")
    _last_frame = list(values)


def send_once(dev, values: list[int]) -> bool:
    global _last_frame
    ok = dmx.send_range_once(dev, START, values)
    if ok:
        _last_frame = list(values)
    return ok


def keepalive(dev) -> bool:
    return send_once(dev, _last_frame)


def _link_dead(dev) -> bool:
    if dmx.link_check_due() and not dmx.udmx_handle_ok(dev):
        dmx.mark_usb_dead("No such device")
        return True
    return dmx.usb_is_dead()


def _usb_tick(dev, frame: list[int], *, twice: bool = False) -> tuple[int, bool]:
    """Send one DMX frame. Returns (fail_delta, dead)."""
    ok = send_once(dev, frame)
    if twice:
        ok = send_once(dev, frame) or ok
    return (0 if ok else 1, _link_dead(dev) or dmx.usb_is_dead())


def blackout_on(dev) -> list[int]:
    values = [0] * 14
    send(dev, values)
    return values


def load_look(name: str) -> dict:
    path = Path(name)
    if not path.is_file():
        path = LOOKS_DIR / name
        if not path.suffix:
            path = path.with_suffix(".json")
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not str(k).startswith("_")}


def write_look(dev, look: dict) -> list[int]:
    values = pack(look["a"], look["b"])
    send(dev, values)
    return values


def load_sequence(name: str) -> tuple[Path, dict]:
    path = Path(name)
    if not path.is_file():
        path = SEQ_DIR / name
        if not path.suffix:
            path = path.with_suffix(".json")
    return path, json.loads(path.read_text())


def _color(c: dict, dimmer: int | None = None) -> dict:
    return rgb(int(c["r"]), int(c["g"]), int(c["b"]), int(c.get("dimmer", dimmer or 255)))


def pump_two_cycle(
    dev,
    frames: list[list[int]],
    hz: float,
    fps: float,
    stop=None,
    engine: str = "two_cycle",
    reliable: bool = False,
) -> dict:
    n_frames = len(frames)
    if n_frames < 2:
        raise SystemExit("two_cycle needs at least 2 frames")
    slot = fps / (n_frames * hz)
    if abs(slot - round(slot)) > 1e-6:
        raise SystemExit(f"fps={fps} must be a multiple of {n_frames}*hz={n_frames * hz}")
    slot_i = int(round(slot))
    step = 1.0 / fps
    keepalive = max(1, int(round(fps)))
    t0 = time.perf_counter()
    n = 0
    fails = 0
    last_idx = None
    while not dmx.stopped(stop):
        n, halt = dmx.sync_frame(t0, n, step, stop)
        if halt:
            break
        if _link_dead(dev):
            return {
                "engine": engine,
                "frames": n,
                "usb_fail": fails,
                "hz": hz,
                "usb_dead": True,
            }
        idx = (n // slot_i) % n_frames
        frame = frames[idx]
        changed = idx != last_idx
        if changed or n % keepalive == 0:
            delta, dead = _usb_tick(dev, frame, twice=reliable and changed)
            fails += delta
            if dead:
                return {
                    "engine": engine,
                    "frames": n,
                    "usb_fail": fails,
                    "hz": hz,
                    "usb_dead": True,
                }
        last_idx = idx
        n += 1
    return {"engine": engine, "frames": n, "usb_fail": fails, "hz": hz, "usb_dead": False}


def pump_chase(dev, color_a: dict, color_b: dict, hz: float, fps: float, stop=None) -> dict:
    """Both on; they swap colors. Not a strobe."""
    frames = [
        pack(_color(color_a), _color(color_b)),
        pack(_color(color_b), _color(color_a)),
    ]
    return pump_two_cycle(dev, frames, hz, fps, stop, "chase")


def pump_alt_strobe(dev, color_a: dict, color_b: dict, hz: float, fps: float, stop=None) -> dict:
    """A on / both black / B on / both black. CH6=0 on black so the PAR actually goes off."""
    off = hard_off()
    both_off = pack(off, off)
    frames = [
        pack(_color(color_a), off),
        both_off,
        pack(off, _color(color_b)),
        both_off,
    ]
    return pump_two_cycle(dev, frames, hz, fps, stop, "alt_strobe", reliable=True)


def _as_palette(value) -> list[dict]:
    if isinstance(value, list):
        if not value:
            raise SystemExit("lightning palette is empty")
        return value
    return [value]


def _strike_queue(
    palette: list[dict],
    fps: float,
    flash_min: float,
    flash_max: float,
    bursts_min: int,
    bursts_max: int,
    burst_gap_min: float,
    burst_gap_max: float,
) -> list[dict]:
    """One bolt: 1–N flashes with black gaps, like a lightning flicker."""
    off = hard_off()
    color = random.choice(palette)
    n_bursts = random.randint(bursts_min, bursts_max)
    frames: list[dict] = []
    for i in range(n_bursts):
        dim = 255 if i == 0 else random.randint(90, 200)
        n_on = max(1, int(round(random.uniform(flash_min, flash_max) * fps)))
        frames.extend([_color(color, dim)] * n_on)
        if i + 1 < n_bursts:
            n_off = max(1, int(round(random.uniform(burst_gap_min, burst_gap_max) * fps)))
            frames.extend([off] * n_off)
    return frames


class _Bolt:
    """One PAR: idle (hard off) until a random gap, then play a strike queue."""

    def __init__(
        self,
        palette: list[dict],
        gap_min: float,
        gap_max: float,
        fps: float,
        flash_min: float,
        flash_max: float,
        bursts_min: int,
        bursts_max: int,
        burst_gap_min: float,
        burst_gap_max: float,
    ) -> None:
        self.palette = palette
        self.gap_min = gap_min
        self.gap_max = gap_max
        self.fps = fps
        self.flash_min = flash_min
        self.flash_max = flash_max
        self.bursts_min = bursts_min
        self.bursts_max = bursts_max
        self.burst_gap_min = burst_gap_min
        self.burst_gap_max = burst_gap_max
        self.queue: list[dict] = []
        self.next_t = random.uniform(0.05, gap_max * 0.5)

    def look_at(self, t: float) -> dict:
        if self.queue:
            return self.queue.pop(0)
        if t >= self.next_t:
            self.queue = _strike_queue(
                self.palette,
                self.fps,
                self.flash_min,
                self.flash_max,
                self.bursts_min,
                self.bursts_max,
                self.burst_gap_min,
                self.burst_gap_max,
            )
            strike_s = len(self.queue) / self.fps
            self.next_t = t + strike_s + random.uniform(self.gap_min, self.gap_max)
            return self.queue.pop(0)
        return hard_off()


def pump_lightning(dev, seq: dict, stop=None) -> dict:
    """Independent random bolts per PAR. Black uses CH6=0."""
    fps = float(seq.get("fps", 12))
    gap_min = float(seq.get("gap_min", 0.5))
    gap_max = float(seq.get("gap_max", 2.4))
    if gap_max < gap_min:
        raise SystemExit("lightning gap_max must be >= gap_min")
    kw = dict(
        gap_min=gap_min,
        gap_max=gap_max,
        fps=fps,
        flash_min=float(seq.get("flash_min", 0.05)),
        flash_max=float(seq.get("flash_max", 0.14)),
        bursts_min=int(seq.get("bursts_min", 1)),
        bursts_max=int(seq.get("bursts_max", 3)),
        burst_gap_min=float(seq.get("burst_gap_min", 0.04)),
        burst_gap_max=float(seq.get("burst_gap_max", 0.11)),
    )
    a = _Bolt(_as_palette(seq["a"]), **kw)
    b = _Bolt(_as_palette(seq["b"]), **kw)
    step = 1.0 / fps
    keepalive = max(1, int(round(fps)))
    t0 = time.perf_counter()
    n = 0
    fails = 0
    last: list[int] | None = None
    while not dmx.stopped(stop):
        n, halt = dmx.sync_frame(t0, n, step, stop)
        if halt:
            break
        if _link_dead(dev):
            return {"engine": "lightning", "frames": n, "usb_fail": fails, "usb_dead": True}
        t = n * step
        look_a = a.look_at(t)
        look_b = b.look_at(t)
        frame = pack(look_a, look_b)
        if frame != last or n % keepalive == 0:
            delta, dead = _usb_tick(dev, frame)
            fails += delta
            last = frame
            if dead:
                return {"engine": "lightning", "frames": n, "usb_fail": fails, "usb_dead": True}
        n += 1
    return {"engine": "lightning", "frames": n, "usb_fail": fails, "usb_dead": False}


def pump_dual_breathe(
    dev,
    color_a: dict,
    color_b: dict,
    dimmer_lo: int,
    dimmer_hi: int,
    period: float,
    fps: float,
    stop=None,
) -> dict:
    step = 1.0 / fps
    t0 = time.perf_counter()
    n = 0
    fails = 0
    while not dmx.stopped(stop):
        n, halt = dmx.sync_frame(t0, n, step, stop)
        if halt:
            break
        if _link_dead(dev):
            return {"engine": "dual_breathe", "frames": n, "usb_fail": fails, "usb_dead": True}
        t = n * step
        u = 0.5 + 0.5 * math.sin(2 * math.pi * t / period - math.pi / 2)
        dim_a = int(round(dimmer_lo + (dimmer_hi - dimmer_lo) * u))
        dim_b = int(round(dimmer_lo + (dimmer_hi - dimmer_lo) * (1.0 - u)))
        frame = pack(_color(color_a, dim_a), _color(color_b, dim_b))
        delta, dead = _usb_tick(dev, frame)
        fails += delta
        if dead:
            return {"engine": "dual_breathe", "frames": n, "usb_fail": fails, "usb_dead": True}
        n += 1
    return {"engine": "dual_breathe", "frames": n, "usb_fail": fails, "usb_dead": False}


def pump_dual_fade(
    dev,
    colors: list[dict],
    seconds_per: float,
    fps: float,
    dimmer: int,
    stop=None,
) -> dict:
    if len(colors) < 2:
        raise SystemExit("dual_fade needs at least 2 colors")
    n_cols = len(colors)
    offset = n_cols // 2
    resolved = [
        seven(_color(c, dimmer))
        for c in colors
    ]
    step = 1.0 / fps
    steps_leg = max(1, int(round(seconds_per * fps)))
    t0 = time.perf_counter()
    n = 0
    fails = 0
    while not dmx.stopped(stop):
        n, halt = dmx.sync_frame(t0, n, step, stop)
        if halt:
            break
        if _link_dead(dev):
            return {"engine": "dual_fade", "frames": n, "usb_fail": fails, "usb_dead": True}
        pos = n / steps_leg
        i = int(pos) % n_cols
        j = (i + 1) % n_cols
        u = pos - int(pos)
        ia = i
        ja = j
        ib = (i + offset) % n_cols
        jb = (ib + 1) % n_cols
        a0, a1 = resolved[ia], resolved[ja]
        b0, b1 = resolved[ib], resolved[jb]
        a = [int(round(x + (y - x) * u)) for x, y in zip(a0, a1)]
        b = [int(round(x + (y - x) * u)) for x, y in zip(b0, b1)]
        delta, dead = _usb_tick(dev, a + b)
        fails += delta
        if dead:
            return {"engine": "dual_fade", "frames": n, "usb_fail": fails, "usb_dead": True}
        n += 1
    return {"engine": "dual_fade", "frames": n, "usb_fail": fails, "usb_dead": False}


def _child_stop(parent, seconds: float) -> threading.Event:
    """Fires when parent stops or the hold time elapses."""
    ev = threading.Event()

    def wait_out() -> None:
        if parent is None:
            time.sleep(seconds)
            ev.set()
            return
        parent.wait(seconds)
        ev.set()

    threading.Thread(target=wait_out, daemon=True).start()
    return ev


def _hold_look(dev, seconds: float, stop) -> bool:
    """Keep a static look alive. True if USB died."""
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if dmx.stopped(stop):
            return False
        if _link_dead(dev):
            return True
        remain = deadline - time.perf_counter()
        if dmx.sleep_or_stop(min(1.0, max(0.0, remain)), stop):
            return False
        if not keepalive(dev) and dmx.usb_is_dead():
            return True
    return False


def pump_show(dev, seq: dict, stop=None) -> dict:
    """Cycle looks/plays: random pick or auto order."""
    steps = seq.get("steps") or []
    if not steps:
        raise SystemExit("show needs steps")
    mode = seq.get("mode", "random")
    hold_min = float(seq.get("hold_min", 4.0))
    hold_max = float(seq.get("hold_max", hold_min))
    if hold_max < hold_min:
        hold_max = hold_min
    idx = 0
    prev = None
    fails = 0
    while not dmx.stopped(stop):
        if mode == "random":
            pick = random.choice(steps)
            if len(steps) > 1:
                for _ in range(8):
                    if pick != prev:
                        break
                    pick = random.choice(steps)
            prev = pick
        else:
            pick = steps[idx % len(steps)]
            idx += 1
        kind = pick.get("kind", "look")
        name = pick["name"]
        hold = hold_min if mode == "auto" else random.uniform(hold_min, hold_max)
        if kind == "look":
            write_look(dev, load_look(name))
            if _hold_look(dev, hold, stop):
                return {"engine": "show", "mode": mode, "usb_fail": fails, "usb_dead": True}
            continue
        _path, inner = load_sequence(name)
        if inner.get("engine") == "show":
            continue
        child = _child_stop(stop, hold)
        stats = run_sequence(dev, inner, stop=child)
        fails += int(stats.get("usb_fail") or 0)
        if stats.get("usb_dead"):
            return {"engine": "show", "mode": mode, "usb_fail": fails, "usb_dead": True}
        if dmx.stopped(stop):
            break
    return {"engine": "show", "mode": mode, "usb_fail": fails, "usb_dead": False}


def _mic_rms(block) -> float:
    import numpy as np

    x = np.asarray(block, dtype=np.float32).reshape(-1)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x))) + 1e-12)


def _open_mic(samplerate: int, blocksize: int):
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise SystemExit(
            "falta sounddevice en el venv DMX. uv pip install --python dmx/.venv/bin/python sounddevice numpy"
        ) from exc
    chunks: queue.Queue = queue.Queue(maxsize=12)

    def callback(indata, frames, time_info, status) -> None:  # noqa: ARG001
        try:
            chunks.put_nowait(indata.copy())
        except queue.Full:
            try:
                chunks.get_nowait()
            except queue.Empty:
                pass
            try:
                chunks.put_nowait(indata.copy())
            except queue.Full:
                pass

    try:
        stream = sd.InputStream(
            channels=1,
            samplerate=samplerate,
            blocksize=blocksize,
            dtype="float32",
            callback=callback,
        )
        stream.start()
    except Exception as exc:
        raise SystemExit(
            f"micrófono no abre ({exc}). En macOS: Ajustes → Privacidad → Micrófono, permite Terminal/Cursor."
        ) from exc
    return stream, chunks


def _sound_hit(dev, style: str, pair: list[dict], side: int, flash_s: float, stop) -> bool:
    """Play one hit. True if USB died. side 0=A, 1=B for split/bolt."""
    off = hard_off()
    a_c = _color(pair[0])
    b_c = _color(pair[1] if len(pair) > 1 else pair[0])
    if style == "chase":
        frame = pack(a_c, b_c) if side % 2 == 0 else pack(b_c, a_c)
        delta, dead = _usb_tick(dev, frame)
        return dead
    if style == "flash":
        frame = pack(a_c, a_c)
    elif style == "split":
        frame = pack(a_c, off) if side % 2 == 0 else pack(off, b_c)
    else:  # bolt
        frame = pack(a_c, off) if side % 2 == 0 else pack(off, a_c)
    delta, dead = _usb_tick(dev, frame, twice=True)
    if dead:
        return True
    if dmx.sleep_or_stop(flash_s, stop):
        return False
    delta, dead = _usb_tick(dev, pack(off, off))
    return dead


def pump_sound(dev, seq: dict, stop=None) -> dict:
    """Mac mic onsets drive color/motion. Fixture sound mode is yellow-only."""
    style = seq.get("style", "split")
    if style not in ("flash", "split", "chase", "bolt"):
        raise SystemExit(f"unknown sound style {style!r}")
    pairs = seq.get("pairs")
    if not pairs:
        raise SystemExit("sound needs pairs")
    thresh = float(seq.get("threshold", 3.2))
    min_level = float(seq.get("min_level", 0.025))
    cooldown = float(seq.get("cooldown", 0.12))
    flash_s = float(seq.get("flash", 0.11))
    samplerate = int(seq.get("samplerate", 16000))
    blocksize = int(seq.get("blocksize", 512))
    stream, chunks = _open_mic(samplerate, blocksize)
    floor = 1e-3
    last_hit = 0.0
    hit_n = 0
    fails = 0
    pair_i = 0
    try:
        send(dev, pack(hard_off(), hard_off()))
        while not dmx.stopped(stop):
            if _link_dead(dev):
                return {"engine": "sound", "style": style, "hits": hit_n, "usb_fail": fails, "usb_dead": True}
            try:
                block = chunks.get(timeout=0.2)
            except queue.Empty:
                continue
            rms = _mic_rms(block)
            floor = 0.97 * floor + 0.03 * rms
            now = time.perf_counter()
            if rms < max(floor * thresh, min_level) or now - last_hit < cooldown:
                continue
            last_hit = now
            pair = pairs[pair_i % len(pairs)]
            if style == "bolt":
                side = random.randint(0, 1)
                pair = [random.choice(pair), random.choice(pair)]
            else:
                side = hit_n
            if _sound_hit(dev, style, pair, side, flash_s, stop):
                return {"engine": "sound", "style": style, "hits": hit_n, "usb_fail": fails, "usb_dead": True}
            hit_n += 1
            if style != "split" or hit_n % 2 == 0:
                pair_i += 1
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        try:
            send_once(dev, pack(hard_off(), hard_off()))
        except Exception:
            pass
    return {"engine": "sound", "style": style, "hits": hit_n, "usb_fail": fails, "usb_dead": False}


def run_sequence(dev, seq: dict, *, stop=None) -> dict:
    engine = seq.get("engine")
    if engine in ("alt_strobe", "strobe"):
        return pump_alt_strobe(
            dev,
            seq["a"],
            seq["b"],
            float(seq.get("hz", 1)),
            float(seq.get("fps", 8)),
            stop,
        )
    if engine in ("chase", "swap_strobe"):
        return pump_chase(
            dev,
            seq["a"],
            seq["b"],
            float(seq.get("hz", 1)),
            float(seq.get("fps", 8)),
            stop,
        )
    if engine == "dual_breathe":
        return pump_dual_breathe(
            dev,
            seq["a"],
            seq["b"],
            int(seq.get("dimmer_lo", 40)),
            int(seq.get("dimmer_hi", 255)),
            float(seq.get("period", 4.0)),
            float(seq.get("fps", 12)),
            stop,
        )
    if engine == "dual_fade":
        return pump_dual_fade(
            dev,
            seq["colors"],
            float(seq.get("seconds_per", 2.0)),
            float(seq.get("fps", 12)),
            int(seq.get("dimmer", 255)),
            stop,
        )
    if engine == "lightning":
        return pump_lightning(dev, seq, stop)
    if engine == "show":
        return pump_show(dev, seq, stop)
    if engine == "sound":
        return pump_sound(dev, seq, stop)
    raise SystemExit(f"unknown duo engine {engine!r}")
