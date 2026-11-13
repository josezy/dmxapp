#!/usr/bin/env python3
"""Dump deterministic ShowPlayer frames so the TypeScript port can match Python."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import beam_halo_duo as beam  # noqa: E402
from show_dispatch import ShowPlayer, load_catalog, prepare_beam_sequence  # noqa: E402
from show_rig import build_rig  # noqa: E402

OUT = ROOT / "web" / "test" / "fixtures" / "show-frames.json"


def add(cases: list, catalog: dict, name: str, n_lpc: int, n_beam: int, order: str, look: str, pal: str, scale: float, times: list) -> None:
    player = ShowPlayer(
        build_rig(n_lpc, n_beam, order),
        catalog["looks"][look],
        catalog["paletteById"][pal],
        scale,
    )
    cases.append(
        {
            "name": name,
            "nLpc": n_lpc,
            "nBeam": n_beam,
            "order": order,
            "look": look,
            "palette": pal,
            "scale": scale,
            "fps": player.fps,
            "samples": [
                {"t": t, "now": now, "frame": player.frame(now, t)} for t, now in times
            ],
        }
    )


def main() -> None:
    catalog = load_catalog()
    cases: list = []
    add(cases, catalog, "sangre-pars", 2, 0, "lpc_first", "abre-cierra", "sangre", 1.0, [(0.0, 0.0)])
    add(
        cases,
        catalog,
        "disco-cycle",
        0,
        2,
        "lpc_first",
        "abre-cierra",
        "disco",
        1.0,
        [(i * 1.2, i * 1.2) for i in range(5)],
    )
    add(cases, catalog, "breathe-mixed", 2, 1, "lpc_first", "breathe", "calida", 1.0, [(0.4, 1.0), (1.0, 1.0)])
    add(cases, catalog, "abanico-fan", 0, 3, "lpc_first", "abanico", "sangre", 1.0, [(0.0, 0.0), (0.25, 0.25)])
    add(
        cases,
        catalog,
        "golpe-duo",
        0,
        2,
        "lpc_first",
        "golpe",
        "blanco",
        1.0,
        [(n / 18, n / 18) for n in range(4)],
    )
    add(
        cases,
        catalog,
        "strobe-pars",
        2,
        0,
        "lpc_first",
        "strobe",
        "rojo-cian",
        1.0,
        [(0.0, 0.0), (0.25, 0.25), (0.5, 0.5), (1.0, 1.0)],
    )
    add(cases, catalog, "chase-pars", 2, 0, "lpc_first", "chase", "rojo-cian", 1.0, [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
    add(cases, catalog, "fade-mixed", 2, 2, "lpc_first", "fade", "arcoiris", 1.0, [(0.5, 0.5), (1.0, 1.0)])
    add(
        cases,
        catalog,
        "corona-disco",
        0,
        2,
        "lpc_first",
        "corona",
        "disco",
        1.0,
        [(0.0, 0.0), (0.5, 0.5), (2.4, 2.4)],
    )
    add(cases, catalog, "verse-beam-first", 2, 2, "beam_first", "verse", "azul", 1.0, [(0.2, 0.2)])
    add(cases, catalog, "one-beam", 0, 1, "lpc_first", "abre-cierra", "sangre", 1.0, [(0.0, 0.0)])
    add(cases, catalog, "fast-golpe", 0, 2, "lpc_first", "golpe", "blanco", 2.0, [(0.1, 0.1)])

    _path, golpe = beam.load_sequence("golpe-blanco")
    fast = prepare_beam_sequence(golpe, None, 2.0)
    _path, tiron = beam.load_sequence("abanico-tiron-disco")
    painted = prepare_beam_sequence(tiron, catalog["paletteById"]["disco"], 1.0)
    _path, corona = beam.load_sequence("corona-reloj-dardo")
    crowned = prepare_beam_sequence(corona, catalog["paletteById"]["disco"], 1.0)
    meta = {
        "golpe_pan_hz": golpe["pan_hz"],
        "fast_pan_hz": fast["pan_hz"],
        "golpe_speed": golpe["speed"],
        "fast_speed": fast["speed"],
        "tiron_palette_len": len(painted["palette"]),
        "tiron_palette_0_beam": list(painted["palette"][0]["beam"]),
        "tiron_palette_0_halo": list(painted["palette"][0]["halo"]),
        "tiron_palette_4_halo": list(painted["palette"][4]["halo"]),
        "corona_palette_len": len(crowned["palette"]),
        "corona_hand": list(crowned["hand"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "cases": cases}) + "\n")
    print(f"wrote {OUT} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
