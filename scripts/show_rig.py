"""DMX address map for a mixed LPC008 (7CH) + BEAM 60W (30CH) rig."""

from __future__ import annotations

UNIVERSE = 512
LPC_CH = 7
BEAM_CH = 30
MAX_EACH = 8


class RigError(ValueError):
    pass


def build_rig(n_lpc: int, n_beam: int, order: str = "lpc_first") -> dict:
    """Pack fixtures from channel 1. `lpc_first` matches the old PAR duo when beams are 0,
    and the old beam duo (A001+A031) when PARs are 0.
    """
    if order not in ("lpc_first", "beam_first"):
        raise RigError(f"unknown order {order!r}")
    for name, n in (("LPC008", n_lpc), ("BEAM", n_beam)):
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise RigError(f"{name} count must be >= 0")
        if n > MAX_EACH:
            raise RigError(f"{name} count {n} is above {MAX_EACH}")
    blocks = [("lpc", n_lpc, LPC_CH), ("beam", n_beam, BEAM_CH)]
    if order == "beam_first":
        blocks.reverse()
    fixtures: list[dict] = []
    cursor = 0
    seen = {"lpc": 0, "beam": 0}
    for kind, count, channels in blocks:
        for _ in range(count):
            if cursor + channels > UNIVERSE:
                raise RigError(
                    f"el mapa pasa de {UNIVERSE} canales ({kind} en {cursor + 1})"
                )
            fixtures.append(
                {
                    "type": kind,
                    "index": seen[kind],
                    "address": cursor + 1,
                    "start": cursor,
                    "channels": channels,
                    "label": f"A{cursor + 1:03d}",
                }
            )
            seen[kind] += 1
            cursor += channels
    return {
        "order": order,
        "nLpc": n_lpc,
        "nBeam": n_beam,
        "fixtures": fixtures,
        "span": cursor,
    }


def fixtures_of(rig: dict, kind: str) -> list[dict]:
    return [f for f in rig["fixtures"] if f["type"] == kind]
