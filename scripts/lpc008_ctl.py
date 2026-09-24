#!/usr/bin/env python3
"""LPC008 A001 7ch: looks, sequences, and engines. CH5 always 0."""

from __future__ import annotations

import json
from pathlib import Path

import dmx

ROOT = Path(__file__).resolve().parents[1]
LPC_FIXTURE_PATH = ROOT / "fixtures" / "lpc008.json"
LOOKS_DIR = ROOT / "lpc008" / "looks"
SEQ_DIR = ROOT / "lpc008" / "sequences"
KEYS = ("dimmer", "r", "g", "b", "strobe", "feature", "speed")


def load_raw() -> dict:
    return json.loads(LPC_FIXTURE_PATH.read_text())


def pump_fixture() -> dict:
    raw = load_raw()
    return {
        "address": int(raw["address"]),
        "channels": 7,
        "map": {
            "dimmer": 1,
            "r": 2,
            "g": 3,
            "b": 4,
            "w": 5,
            "feature": 6,
            "speed": 7,
        },
        "features": raw["features"],
    }


def to_dmx_look(look: dict) -> dict:
    data = {k: v for k, v in look.items() if not str(k).startswith("_")}
    feature = data.get("feature", 25)
    if feature in (0, "off"):
        feature = 0
    return {
        "dimmer": int(data.get("dimmer", 0)),
        "r": int(data.get("r", 0)),
        "g": int(data.get("g", 0)),
        "b": int(data.get("b", 0)),
        "w": 0,
        "feature": feature,
        "speed": int(data.get("speed", 0)),
    }


def load_look(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        path = LOOKS_DIR / path
        if not path.suffix:
            path = path.with_suffix(".json")
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not str(k).startswith("_")}


def write_look(dev, look: dict) -> list[int]:
    fixture = pump_fixture()
    _public, channels = dmx.write_look(dev, fixture, to_dmx_look(look), merge=False)
    return channels


def blackout_on(dev) -> list[int]:
    fixture = pump_fixture()
    channels = [0, 0, 0, 0, 0, 0, 0]
    dmx.send_range(dev, fixture["address"] - 1, channels)
    return channels


def load_sequence(name: str) -> tuple[Path, dict]:
    path = Path(name)
    if not path.is_file():
        path = SEQ_DIR / name
        if not path.suffix:
            path = path.with_suffix(".json")
    return path, json.loads(path.read_text())


def run_sequence(dev, seq: dict, *, loop: bool = False, stop=None) -> dict:
    fixture = pump_fixture()
    colors = seq.get("colors")
    if colors:
        seq = dict(seq)
        seq["colors"] = [{**c, "w": 0} for c in colors]
    color = seq.get("color")
    if color:
        seq = dict(seq)
        seq["color"] = {**color, "w": 0}
    return dmx.run_sequence(dev, fixture, seq, loop=loop, stop=stop)
