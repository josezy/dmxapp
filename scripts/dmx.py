#!/usr/bin/env python3
"""Drive the Anyma uDMX adapter and VEVOR JM-P13 PAR (7ch at d001)."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Callable

import usb.backend.libusb1
import usb.core
import usb.util

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "fixtures" / "jm-p13.json"
LOOKS_DIR = ROOT / "looks"
STATE_PATH = ROOT / "state.json"
LIBUSB_CANDIDATES = (
    "/opt/homebrew/lib/libusb-1.0.dylib",
    "/usr/local/lib/libusb-1.0.dylib",
)
LIBUSB = next(
    (p for p in LIBUSB_CANDIDATES if Path(p).exists()),
    LIBUSB_CANDIDATES[0],
)

UDMX_VID = 0x16C0
UDMX_PID = 0x05DC
CMD_SET_SINGLE = 1
CMD_SET_RANGE = 2
BM_REQUEST = (
    usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE | usb.util.CTRL_OUT
)

KEYS = ("dimmer", "r", "g", "b", "w", "feature", "speed")


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def load_look(path: Path) -> dict:
    data = json.loads(path.read_text())
    data = {k: v for k, v in data.items() if not str(k).startswith("_")}
    unknown = set(data) - set(KEYS)
    if unknown:
        raise SystemExit(f"Unknown look keys: {sorted(unknown)}")
    return data


def feature_byte(fixture: dict, value) -> int:
    if isinstance(value, str):
        table = fixture["features"]
        if value not in table:
            raise SystemExit(f"Unknown feature {value!r}. Use {sorted(table)}")
        return int(table[value])
    n = int(value)
    if not 0 <= n <= 255:
        raise SystemExit("feature must be 0-255")
    return n


def clamp_byte(key: str, value) -> int:
    n = int(value)
    if not 0 <= n <= 255:
        raise SystemExit(f"{key} must be 0-255")
    return n


def previous_look() -> dict:
    if not STATE_PATH.exists():
        return {k: 0 for k in KEYS}
    prev = json.loads(STATE_PATH.read_text())
    return {k: prev.get(k, 0) for k in KEYS}


def resolve_look(fixture: dict, look: dict, merge: bool) -> dict:
    merged = previous_look() if merge else {k: 0 for k in KEYS}
    merged.update(look)
    out = {
        "dimmer": clamp_byte("dimmer", merged.get("dimmer", 0)),
        "r": clamp_byte("r", merged.get("r", 0)),
        "g": clamp_byte("g", merged.get("g", 0)),
        "b": clamp_byte("b", merged.get("b", 0)),
        "w": clamp_byte("w", merged.get("w", 0)),
        "feature": merged.get("feature", "dimmer") or "dimmer",
        "speed": clamp_byte("speed", merged.get("speed", 0)),
    }
    out["_feature_byte"] = feature_byte(fixture, out["feature"])
    return out


def channels_for(fixture: dict, look: dict) -> list[int]:
    ch = [0] * fixture["channels"]
    payload = dict(look)
    payload["feature"] = look["_feature_byte"]
    for key in KEYS:
        ch[fixture["map"][key] - 1] = int(payload[key])
    return ch


def save_state(look: dict, channels: list[int]) -> None:
    state = {k: look[k] for k in KEYS}
    state["channels"] = channels
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def open_udmx():
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
    if backend is None:
        raise SystemExit(f"libusb not found at {LIBUSB}")
    dev = usb.core.find(idVendor=UDMX_VID, idProduct=UDMX_PID, backend=backend)
    if dev is None:
        raise SystemExit(
            "uDMX not found (vid=0x16c0 pid=0x05dc). Unplug/replug, quit QLC+, then retry."
        )
    reset_usb_stats()
    return dev


def find_udmx():
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
    if backend is None:
        return None
    return usb.core.find(idVendor=UDMX_VID, idProduct=UDMX_PID, backend=backend)


def udmx_handle_ok(dev) -> bool:
    """True if this open handle still matches a device on the bus."""
    if dev is None:
        return False
    found = find_udmx()
    if found is None:
        return False
    try:
        return int(found.bus) == int(dev.bus) and int(found.address) == int(dev.address)
    except Exception:
        return False


def close_udmx(dev) -> None:
    if dev is None:
        return
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass


_usb = {
    "ok": 0,
    "fail": 0,
    "streak": 0,
    "skipped": 0,
    "last_error": "",
    "last_errno": None,
}

USB_DEAD_STREAK = 20
DISCONNECT_ERRNOS = {19, -4}  # ENODEV, LIBUSB_ERROR_NO_DEVICE
_link_next = 0.0


def reset_usb_stats() -> None:
    global _link_next
    _usb.update(ok=0, fail=0, streak=0, skipped=0, last_error="", last_errno=None)
    _link_next = time.perf_counter() + 1.0


def usb_health() -> dict:
    return dict(_usb)


def usb_is_dead(threshold: int = USB_DEAD_STREAK) -> bool:
    return int(_usb["streak"]) >= threshold


def mark_usb_dead(reason: str) -> None:
    _usb["streak"] = USB_DEAD_STREAK
    _usb["fail"] += 1
    _usb["last_error"] = reason


def link_check_due(interval: float = 1.0) -> bool:
    global _link_next
    now = time.perf_counter()
    if now < _link_next:
        return False
    _link_next = now + interval
    return True


def _note_usb(ok: bool, err: usb.core.USBError | None = None) -> None:
    if ok:
        _usb["ok"] += 1
        _usb["streak"] = 0
        return
    _usb["fail"] += 1
    _usb["streak"] += 1
    if err is not None:
        errno = getattr(err, "errno", None)
        _usb["last_errno"] = errno
        _usb["last_error"] = str(err)
        if errno in DISCONNECT_ERRNOS:
            _usb["streak"] = USB_DEAD_STREAK


def send_range(dev, start_index: int, values: list[int], retries: int = 3, timeout: int = 80) -> int:
    payload = bytearray(values)
    last = None
    attempts = max(1, retries)
    for i in range(attempts):
        try:
            sent = int(
                dev.ctrl_transfer(
                    BM_REQUEST,
                    CMD_SET_RANGE,
                    wValue=len(payload),
                    wIndex=start_index,
                    data_or_wLength=payload,
                    timeout=timeout,
                )
            )
            _note_usb(True)
            return sent
        except usb.core.USBError as exc:
            last = exc
            _note_usb(False, exc)
            if i + 1 < attempts:
                time.sleep(0.03)
    raise SystemExit(f"uDMX transfer failed after retries: {last}")


def send_single(dev, channel_index: int, value: int, timeout: int = 40) -> bool:
    """One DMX channel. False on overflow/busy — caller must not sleep-retry."""
    try:
        dev.ctrl_transfer(
            BM_REQUEST,
            CMD_SET_SINGLE,
            wValue=int(value) & 255,
            wIndex=int(channel_index),
            data_or_wLength=1,
            timeout=timeout,
        )
        return True
    except usb.core.USBError:
        return False


def wait_until(deadline: float) -> None:
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return
        if remain > 0.003:
            time.sleep(remain - 0.001)


def stopped(stop) -> bool:
    return stop is not None and stop.is_set()


def wait_until_busy(deadline: float, stop=None) -> bool:
    """Sleep until deadline. True if stop was set. Does not spin the CPU."""
    while True:
        if stopped(stop):
            return True
        remain = deadline - time.perf_counter()
        if remain <= 0:
            return False
        slice_s = remain if remain < 0.01 else 0.01
        if stop is not None:
            if stop.wait(slice_s):
                return True
        else:
            time.sleep(slice_s)


def sync_frame(t0: float, n: int, step: float, stop=None) -> tuple[int, bool]:
    """Wait for frame n. If we fell behind, skip frames instead of bursting USB."""
    now = time.perf_counter()
    target = t0 + n * step
    if now - target > step:
        jumped = int((now - t0) / step)
        _usb["skipped"] += max(0, jumped - n)
        n = jumped
        target = t0 + n * step
    if wait_until_busy(target, stop):
        return n, True
    return n, False


def sleep_or_stop(seconds: float, stop=None) -> bool:
    if seconds <= 0:
        return stopped(stop)
    if stop is None:
        time.sleep(seconds)
        return False
    return bool(stop.wait(seconds))


def send_range_once(dev, start_index: int, values: list[int], timeout: int = 25) -> bool:
    payload = bytearray(values)
    try:
        dev.ctrl_transfer(
            BM_REQUEST,
            CMD_SET_RANGE,
            wValue=len(payload),
            wIndex=start_index,
            data_or_wLength=payload,
            timeout=timeout,
        )
        _note_usb(True)
        return True
    except usb.core.USBError as exc:
        _note_usb(False, exc)
        return False


def black_channels(fixture: dict) -> list[int]:
    look = resolve_look(fixture, {k: 0 for k in KEYS} | {"feature": "dimmer"}, merge=False)
    return channels_for(fixture, look)


def look_color(color: dict, dimmer: int = 255) -> dict:
    return {
        "dimmer": dimmer,
        "r": int(color.get("r", 0)),
        "g": int(color.get("g", 0)),
        "b": int(color.get("b", 0)),
        "w": int(color.get("w", 0)),
        "feature": "dimmer",
        "speed": 0,
    }


def pump_breathe(
    dev,
    start_index: int,
    fixture: dict,
    color: dict,
    dimmer_lo: int,
    dimmer_hi: int,
    period: float,
    fps: float,
    seconds: float | None,
    stop=None,
) -> dict:
    step = 1.0 / fps
    t0 = time.perf_counter()
    n = 0
    fails = 0
    while not stopped(stop):
        t = n * step
        if seconds is not None and t >= seconds:
            break
        if wait_until_busy(t0 + t, stop):
            break
        u = 0.5 + 0.5 * math.sin(2 * math.pi * t / period - math.pi / 2)
        dim = int(round(dimmer_lo + (dimmer_hi - dimmer_lo) * u))
        frame = channels_for(fixture, resolve_look(fixture, look_color(color, dim), merge=False))
        if not send_range_once(dev, start_index, frame):
            fails += 1
        n += 1
    return {"engine": "breathe", "frames": n, "usb_fail": fails, "stopped": stopped(stop)}


def pump_color_strobe(
    dev,
    start_index: int,
    frames_cycle: list[list[int]],
    hz: float,
    fps: float,
    seconds: float | None,
    stop=None,
) -> dict:
    half = fps / (2.0 * hz)
    if abs(half - round(half)) > 1e-6:
        raise SystemExit(f"fps={fps} must be a multiple of 2*hz={2 * hz}")
    half_i = int(round(half))
    n_colors = len(frames_cycle)
    if n_colors < 2:
        raise SystemExit("strobe_colors needs at least 2 colors")
    step = 1.0 / fps
    t0 = time.perf_counter()
    n = 0
    fails = 0
    while not stopped(stop):
        t = n * step
        if seconds is not None and t >= seconds:
            break
        if wait_until_busy(t0 + t, stop):
            break
        idx = (n // half_i) % n_colors
        if not send_range_once(dev, start_index, frames_cycle[idx]):
            fails += 1
        n += 1
    return {
        "engine": "strobe_colors",
        "frames": n,
        "usb_fail": fails,
        "hz": hz,
        "fps": fps,
        "stopped": stopped(stop),
    }


def pump_color_fade(
    dev,
    start_index: int,
    fixture: dict,
    colors: list[dict],
    seconds_per: float,
    fps: float,
    dimmer: int,
    seconds: float | None,
    stop=None,
) -> dict:
    if len(colors) < 2:
        raise SystemExit("color_fade needs at least 2 colors")
    step = 1.0 / fps
    steps_leg = max(1, int(round(seconds_per * fps)))
    resolved = [
        channels_for(fixture, resolve_look(fixture, look_color(c, dimmer), merge=False))
        for c in colors
    ]
    t0 = time.perf_counter()
    n = 0
    fails = 0
    n_cols = len(resolved)
    while not stopped(stop):
        t = n * step
        if seconds is not None and t >= seconds:
            break
        if wait_until_busy(t0 + t, stop):
            break
        pos = n / steps_leg
        i = int(pos) % n_cols
        j = (i + 1) % n_cols
        u = pos - int(pos)
        a, b = resolved[i], resolved[j]
        frame = [int(round(x + (y - x) * u)) for x, y in zip(a, b)]
        if not send_range_once(dev, start_index, frame):
            fails += 1
        n += 1
    return {"engine": "color_fade", "frames": n, "usb_fail": fails, "stopped": stopped(stop)}


def pump_square(
    dev,
    start_index: int,
    on_frame: list[int],
    off_frame: list[int],
    hz: float,
    seconds: float,
    fps: float,
) -> dict:
    """Stream a square wave sampled on a fixed USB frame clock."""
    frames = int(round(seconds * fps))
    step = 1.0 / fps
    half_cycle = fps / (2.0 * hz)
    if abs(half_cycle - round(half_cycle)) > 1e-6:
        raise SystemExit(f"fps={fps} must be a multiple of 2*hz={2 * hz}")
    half_cycle_i = int(round(half_cycle))
    t0 = time.perf_counter()
    fails = 0
    late_max = 0.0
    for n in range(frames):
        deadline = t0 + n * step
        wait_until_busy(deadline, None)
        late_max = max(late_max, time.perf_counter() - deadline)
        on = ((n // half_cycle_i) % 2) == 0
        if not send_range_once(dev, start_index, on_frame if on else off_frame):
            fails += 1
    return {
        "hz": hz,
        "fps": fps,
        "frames": frames,
        "on_frames": half_cycle_i,
        "off_frames": half_cycle_i,
        "usb_fail": fails,
        "late_max_ms": round(late_max * 1000, 2),
    }


def write_look(dev, fixture: dict, look: dict, merge: bool) -> tuple[dict, list[int]]:
    resolved = resolve_look(fixture, look, merge=merge)
    channels = channels_for(fixture, resolved)
    start = fixture["address"] - 1
    sent = send_range(dev, start, channels)
    if sent != len(channels):
        raise SystemExit(f"short write: {sent}/{len(channels)}")
    public = {k: resolved[k] for k in KEYS}
    save_state(public, channels)
    return public, channels


def apply_look(fixture: dict, look: dict, merge: bool) -> tuple[dict, list[int]]:
    return write_look(open_udmx(), fixture, look, merge)


def blackout_on(dev, fixture: dict) -> list[int]:
    channels = black_channels(fixture)
    send_range(dev, fixture["address"] - 1, channels)
    save_state({k: 0 for k in KEYS} | {"feature": "dimmer"}, channels)
    return channels


def load_sequence(path: Path) -> tuple[Path, dict]:
    path = Path(path)
    if not path.is_file():
        path = ROOT / "sequences" / path
        if not path.suffix:
            path = path.with_suffix(".json")
    return path, json.loads(path.read_text())


def run_sequence(
    dev,
    fixture: dict,
    seq: dict,
    *,
    loop: bool = False,
    stop=None,
    seconds: float | None = None,
    on_cue: Callable[[dict], None] | None = None,
) -> dict:
    start_index = fixture["address"] - 1
    engine = seq.get("engine", "cues")
    if seconds is None and seq.get("seconds") is not None:
        seconds = float(seq["seconds"])
    if engine == "breathe":
        return pump_breathe(
            dev,
            start_index,
            fixture,
            seq["color"],
            int(seq.get("dimmer_lo", 77)),
            int(seq.get("dimmer_hi", 255)),
            float(seq.get("period", 4.0)),
            float(seq.get("fps", 40)),
            seconds,
            stop,
        )
    if engine == "strobe_colors":
        frames = [
            channels_for(fixture, resolve_look(fixture, look_color(c), merge=False))
            for c in seq["colors"]
        ]
        return pump_color_strobe(
            dev,
            start_index,
            frames,
            float(seq.get("hz", 6)),
            float(seq.get("fps", 24)),
            seconds,
            stop,
        )
    if engine == "color_fade":
        return pump_color_fade(
            dev,
            start_index,
            fixture,
            seq["colors"],
            float(seq.get("seconds_per", 2.0)),
            float(seq.get("fps", 30)),
            int(seq.get("dimmer", 255)),
            seconds,
            stop,
        )
    cues = seq["cues"]
    cycle_s = float(seq["duration"]) if seq.get("duration") is not None else None
    last_vals = black_channels(fixture)
    loops = 0
    while not stopped(stop):
        t0 = time.monotonic()
        for cue in cues:
            if stopped(stop):
                break
            target_t = float(cue["t"])
            wait = t0 + target_t - time.monotonic()
            if wait > 0 and sleep_or_stop(wait, stop):
                break
            look = {k: cue[k] for k in KEYS if k in cue}
            look.setdefault("feature", "dimmer")
            look.setdefault("speed", 0)
            end_look = resolve_look(fixture, look, merge=False)
            end_vals = channels_for(fixture, end_look)
            fade = float(cue.get("fade", 0))
            if fade <= 0:
                send_range(dev, start_index, end_vals)
            else:
                steps = max(1, int(fade * 30))
                aborted = False
                for i in range(1, steps + 1):
                    if stopped(stop):
                        aborted = True
                        break
                    u = i / steps
                    frame = [int(round(a + (b - a) * u)) for a, b in zip(last_vals, end_vals)]
                    send_range(dev, start_index, frame)
                    if sleep_or_stop(fade / steps, stop):
                        aborted = True
                        break
                if aborted:
                    break
            last_vals = end_vals
            public = {k: end_look[k] for k in KEYS}
            save_state(public, end_vals)
            if on_cue is not None:
                on_cue(
                    {
                        "t": cue["t"],
                        "name": cue.get("name"),
                        "dmx": end_vals,
                        "late_s": round(time.monotonic() - (t0 + target_t), 3),
                    }
                )
        else:
            if cycle_s is not None:
                remain = t0 + cycle_s - time.monotonic()
                if remain > 0 and sleep_or_stop(remain, stop):
                    break
            loops += 1
            if not loop:
                break
            continue
        break
    return {"engine": "cues", "loops": loops, "stopped": stopped(stop)}


def parse_hex(color: str) -> dict:
    raw = color.strip().lstrip("#")
    if len(raw) != 6:
        raise SystemExit("--hex must be RRGGBB")
    return {
        "r": int(raw[0:2], 16),
        "g": int(raw[2:4], 16),
        "b": int(raw[4:6], 16),
        "w": 0,
        "feature": "dimmer",
        "speed": 0,
    }


def levels_from_args(args: argparse.Namespace) -> dict:
    look = {}
    if args.hex:
        look.update(parse_hex(args.hex))
        if args.dimmer is None:
            look["dimmer"] = 255
    for key in ("dimmer", "r", "g", "b", "w", "speed"):
        val = getattr(args, key)
        if val is not None:
            look[key] = val
    if args.feature is not None:
        look["feature"] = args.feature
    return look


def cmd_status(_: argparse.Namespace) -> None:
    fixture = load_fixture()
    try:
        dev = open_udmx()
        adapter = f"ok bus={getattr(dev, 'bus', None)} addr={getattr(dev, 'address', None)}"
    except SystemExit as exc:
        adapter = f"missing ({exc})"
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else None
    print(
        json.dumps(
            {
                "fixture": fixture["model"],
                "mode": fixture["mode"],
                "address": fixture["address"],
                "adapter": adapter,
                "last": state,
            },
            indent=2,
        )
    )


def cmd_set(args: argparse.Namespace) -> None:
    look = levels_from_args(args)
    if not look:
        raise SystemExit("nothing to set")
    public, channels = apply_look(load_fixture(), look, merge=True)
    print(json.dumps({"ok": True, "look": public, "dmx": channels}, indent=2))


def cmd_look(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if not path.is_file():
        path = LOOKS_DIR / args.path
        if not path.suffix:
            path = path.with_suffix(".json")
    look = load_look(path)
    public, channels = apply_look(load_fixture(), look, merge=False)
    print(json.dumps({"ok": True, "file": str(path), "look": public, "dmx": channels}, indent=2))


def cmd_blackout(_: argparse.Namespace) -> None:
    look = load_look(LOOKS_DIR / "blackout.json")
    public, channels = apply_look(load_fixture(), look, merge=False)
    print(json.dumps({"ok": True, "look": public, "dmx": channels}, indent=2))


def cmd_fade(args: argparse.Namespace) -> None:
    fixture = load_fixture()
    target_patch = levels_from_args(args)
    if not target_patch:
        raise SystemExit("nothing to fade to")
    start_look = resolve_look(fixture, {}, merge=True)
    end_look = resolve_look(fixture, target_patch, merge=True)
    start_vals = channels_for(fixture, start_look)
    end_vals = channels_for(fixture, end_look)
    steps = max(1, int(args.seconds * 30))
    dev = open_udmx()
    start_index = fixture["address"] - 1
    for i in range(1, steps + 1):
        t = i / steps
        frame = [int(round(a + (b - a) * t)) for a, b in zip(start_vals, end_vals)]
        send_range(dev, start_index, frame)
        time.sleep(args.seconds / steps)
    public = {k: end_look[k] for k in KEYS}
    save_state(public, end_vals)
    print(json.dumps({"ok": True, "look": public, "dmx": end_vals}, indent=2))


def cmd_play(args: argparse.Namespace) -> None:
    path, seq = load_sequence(Path(args.path))
    fixture = load_fixture()
    dev = open_udmx()
    if args.preroll > 0:
        time.sleep(args.preroll)
    audio_path = None if getattr(args, "no_audio", False) else (args.audio or seq.get("audio"))
    if audio_path:
        subprocess.Popen(["afplay", str(audio_path)])
    engine = seq.get("engine", "cues")
    loop = bool(args.loop) or engine != "cues"
    print(
        json.dumps(
            {
                "playing": str(path),
                "engine": engine,
                "loop": loop,
                "preroll": args.preroll,
                "audio": str(audio_path) if audio_path else None,
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        stats = run_sequence(
            dev,
            fixture,
            seq,
            loop=loop,
            on_cue=lambda event: print(json.dumps(event), flush=True),
        )
        print(json.dumps(stats), flush=True)
    except KeyboardInterrupt:
        blackout_on(dev, fixture)
        print(json.dumps({"ok": True, "interrupted": True, "blackout": True}), flush=True)
        return
    blackout_on(dev, fixture)
    print(json.dumps({"ok": True, "done": True}), flush=True)


def cmd_strobe(args: argparse.Namespace) -> None:
    fixture = load_fixture()
    look = {
        "dimmer": args.dimmer if args.dimmer is not None else 255,
        "r": args.r if args.r is not None else 20,
        "g": args.g if args.g is not None else 90,
        "b": args.b if args.b is not None else 255,
        "w": args.w if args.w is not None else 190,
        "feature": "dimmer",
        "speed": 0,
    }
    on_look = resolve_look(fixture, look, merge=False)
    off_look = resolve_look(
        fixture,
        {k: 0 for k in KEYS} | {"feature": "dimmer"},
        merge=False,
    )
    on_frame = channels_for(fixture, on_look)
    off_frame = channels_for(fixture, off_look)
    dev = open_udmx()
    start = fixture["address"] - 1
    send_range(dev, start, on_frame, retries=3)
    time.sleep(0.4)
    stats = pump_square(
        dev, start, on_frame, off_frame, hz=args.hz, seconds=args.seconds, fps=args.fps
    )
    send_range(dev, start, off_frame, retries=3)
    stats["blackout"] = True
    print(json.dumps(stats, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VEVOR JM-P13 via uDMX")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="adapter + last look").set_defaults(func=cmd_status)
    sub.add_parser("blackout", help="all channels 0").set_defaults(func=cmd_blackout)

    look = sub.add_parser("look", help="apply a JSON look file")
    look.add_argument("path")
    look.set_defaults(func=cmd_look)

    def add_levels(sp):
        sp.add_argument("--dimmer", type=int)
        sp.add_argument("--r", type=int)
        sp.add_argument("--g", type=int)
        sp.add_argument("--b", type=int)
        sp.add_argument("--w", type=int)
        sp.add_argument("--feature", help="dimmer|jump|gradient|pulse|sound or 0-255")
        sp.add_argument("--speed", type=int)
        sp.add_argument("--hex", help="RRGGBB color, e.g. ff4000")

    setter = sub.add_parser("set", help="set channels (unspecified keys keep last look)")
    add_levels(setter)
    setter.set_defaults(func=cmd_set)

    fade = sub.add_parser("fade", help="lerp from last look")
    add_levels(fade)
    fade.add_argument("--seconds", type=float, default=1.5)
    fade.set_defaults(func=cmd_fade)

    play = sub.add_parser("play", help="run a timed cue sequence (sync with the song)")
    play.add_argument("path")
    play.add_argument("--preroll", type=float, default=0, help="seconds to wait before t=0")
    play.add_argument("--audio", help="afplay this file at t=0 (default: sequence audio field)")
    play.add_argument("--loop", action="store_true", help="repeat the sequence until Ctrl+C")
    play.add_argument("--no-audio", action="store_true", help="lights only")
    play.set_defaults(func=cmd_play)

    strobe = sub.add_parser("strobe", help="software square strobe on a fixed USB frame clock")
    strobe.add_argument("--hz", type=float, default=6.0)
    strobe.add_argument("--seconds", type=float, default=12.0)
    strobe.add_argument("--fps", type=float, default=24.0, help="USB frames/s; must be multiple of 2*hz")
    strobe.add_argument("--dimmer", type=int)
    strobe.add_argument("--r", type=int)
    strobe.add_argument("--g", type=int)
    strobe.add_argument("--b", type=int)
    strobe.add_argument("--w", type=int)
    strobe.set_defaults(func=cmd_strobe)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
