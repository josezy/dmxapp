#!/usr/bin/env python3
"""Dump deterministic Beam Halo frames for Kotlin golden tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import beam_halo_duo as beam  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "app" / "src" / "test" / "resources" / "goldens"
COUNT = 24
DETERMINISTIC = (
    "golpe-blanco",
    "drop-blanco-rojo",
    "barrido-sangre",
    "barrido-flash-sangre-oro",
    "verse-azul",
    "ballad-fade-calido",
    "abanico-tilt",
    "simetrico-abre-cierra",
    "unison-search",
    "contra-tilt",
    "spin-espejo",
    "circulo-espejo",
    "paralelo-search",
    "corona-reloj-dardo",
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in DETERMINISTIC:
        _path, seq = beam.load_sequence(name)
        frames = beam.preview_frames(seq, count=COUNT, seed=1)
        payload = {
            "sequence": name,
            "engine": seq.get("engine"),
            "fps": float(seq.get("fps", 18)),
            "frames": frames,
        }
        dest = OUT / f"{name}.json"
        dest.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
        print(f"wrote {dest.name} ({len(frames)} x {len(frames[0])} bytes)")


if __name__ == "__main__":
    main()
