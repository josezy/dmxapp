#!/usr/bin/env python3
"""Rig map + N=2 beam goldens (native palette, speed medio)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import beam_halo_duo as beam  # noqa: E402
from show_dispatch import (  # noqa: E402
    ShowPlayer,
    load_catalog,
    native_palette,
    prepare_beam_sequence,
    preview_beam_duo,
)
from show_rig import RigError, build_rig  # noqa: E402

GOLDEN = ROOT / "android" / "app" / "src" / "test" / "resources" / "goldens"
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


def check_rig() -> None:
    duo = build_rig(0, 2)
    assert [f["address"] for f in duo["fixtures"]] == [1, 31]
    assert duo["span"] == 60
    pars = build_rig(2, 0)
    assert [f["address"] for f in pars["fixtures"]] == [1, 8]
    assert pars["span"] == 14
    mixed = build_rig(2, 2, "lpc_first")
    assert [f["label"] for f in mixed["fixtures"]] == ["A001", "A008", "A015", "A045"]
    assert mixed["span"] == 14 + 60
    flipped = build_rig(2, 2, "beam_first")
    assert [f["address"] for f in flipped["fixtures"]] == [1, 31, 61, 68]
    try:
        build_rig(9, 0)
        raise AssertionError("expected cap")
    except RigError:
        pass


def check_goldens(catalog: dict) -> None:
    assert catalog["speedById"]["medio"] == 1.0
    for name in DETERMINISTIC:
        _path, seq = beam.load_sequence(name)
        got = preview_beam_duo(seq, native_palette(seq), catalog["speedById"]["medio"])
        plain = beam.preview_frames(seq, count=24, seed=1)
        assert got == plain, name
        golden = json.loads((GOLDEN / f"{name}.json").read_text())
        assert golden["sequence"] == name
        want = [list(frame) for frame in golden["frames"]]
        assert got == want, f"{name} diverges from golden"
    _path, golpe = beam.load_sequence("golpe-blanco")
    fast = prepare_beam_sequence(golpe, None, catalog["speedById"]["rapido"])
    assert abs(fast["pan_hz"] - golpe["pan_hz"] * 2) < 1e-9
    assert fast["speed"] == beam.clamp(golpe["speed"] * 2)
    same = prepare_beam_sequence(golpe, native_palette(golpe), 1.0)
    assert same["a"]["w"] == golpe["a"]["w"]
    assert same["pan_hz"] == golpe["pan_hz"]


def check_adapt(catalog: dict) -> None:
    pal = catalog["paletteById"]["sangre"]
    look = catalog["looks"]["abre-cierra"]
    pars = ShowPlayer(build_rig(2, 0), look, pal, 1.0)
    buf = pars.frame(0.0, 0.0)
    assert buf[:7] == [255, 255, 0, 8, 0, 25, 0]
    assert buf[7:14] == [255, 200, 0, 0, 0, 25, 0]
    one = ShowPlayer(build_rig(0, 1), look, pal, 1.0)
    assert len(one.frame(0.0, 0.0)) == 30
    fan = ShowPlayer(build_rig(0, 3), catalog["looks"]["abanico"], pal, 1.0)
    wide = fan.frame(0.0, 0.25)
    assert len(wide) == 90
    assert all(0 <= b <= 255 for b in wide)
    light = ShowPlayer(
        build_rig(2, 1),
        catalog["looks"]["breathe"],
        catalog["paletteById"]["calida"],
        1.0,
        last_pose=[(20.0, 200.0)],
    )
    frame = light.frame(1.0, 0.4)
    assert len(frame) == 14 + 30
    assert frame[0] > 0
    assert frame[14] == 128 and frame[16] == 128

    disco = catalog["paletteById"]["disco"]
    cycling = ShowPlayer(build_rig(0, 2), catalog["looks"]["abre-cierra"], disco, 1.0)
    seen = {tuple(cycling.frame(t, t)[7:11]) for t in (i * 1.2 for i in range(5))}
    assert seen == {tuple(slot["beam"]) for slot in disco["colors"]}
    breathing = ShowPlayer(build_rig(2, 0), catalog["looks"]["breathe"], disco, 1.0)
    par_colors = {tuple(breathing.frame(t, t)[1:4]) for t in (i * 1.2 + 0.2 for i in range(5))}
    assert len(par_colors) == 5

    assert len(disco["colors"]) == 5
    _path, seq = beam.load_sequence("abanico-tiron-disco")
    painted = prepare_beam_sequence(seq, disco, 1.0)
    assert len(painted["palette"]) == 5
    assert painted["palette"][0]["beam"] == [255, 0, 160, 0]
    assert painted["palette"][0]["halo"] == [0, 230, 240]
    assert painted["palette"][4]["halo"] == [255, 220, 0]
    _path, corona = beam.load_sequence("corona-reloj-dardo")
    crowned = prepare_beam_sequence(corona, disco, 1.0)
    assert len(crowned["palette"]) == 5
    assert crowned["hand"] == corona["hand"]


def main() -> None:
    check_rig()
    catalog = load_catalog()
    check_goldens(catalog)
    check_adapt(catalog)
    print(f"ok  rig + {len(DETERMINISTIC)} goldens + adapt")


if __name__ == "__main__":
    main()
