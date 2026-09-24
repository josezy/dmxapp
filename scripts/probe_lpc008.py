#!/usr/bin/env python3
"""Walk LPC008 7ch (A001) functions. Confirm each step on the PAR. Ctrl+C blackouts."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dmx  # noqa: E402

FIXTURE_PATH = ROOT / "fixtures" / "lpc008.json"


def frame(
    dimmer: int = 0,
    r: int = 0,
    g: int = 0,
    b: int = 0,
    strobe: int = 0,
    feature: int = 25,
    speed: int = 0,
) -> list[int]:
    return [dimmer, r, g, b, strobe, feature, speed]


def send(dev, fixture: dict, values: list[int], *, duo: bool = False) -> None:
    payload = values + values if duo else values
    start = 0 if duo else fixture["address"] - 1
    sent = dmx.send_range(dev, start, payload)
    if sent != len(payload):
        raise SystemExit(f"short write: {sent}/{len(payload)}")


def pause(auto: float | None, prompt: str) -> None:
    print(prompt, flush=True)
    if auto is not None:
        time.sleep(auto)
        return
    input("  [Enter] siguiente  ·  Ctrl+C blackout\n")


def dump_ch(values: list[int]) -> str:
    names = ("ch1 dim", "ch2 R", "ch3 G", "ch4 B", "ch5", "ch6 mode", "ch7")
    return "  ".join(f"{n}={v}" for n, v in zip(names, values))


FULL_STEPS: list[tuple[str, str, list[int]]] = [
    (
        "1 blackout",
        "Debería apagarse por completo.",
        frame(),
    ),
    (
        "2a dimmer 0",
        "RGB a tope, ch6=25 (banda DMX). Con dimmer 0 no debería verse nada.",
        frame(dimmer=0, r=255, g=255, b=255, feature=25),
    ),
    (
        "2b dimmer 80",
        "Debería subir a un blanco/RGB medio. Si no cambia, ch1 no es dimmer.",
        frame(dimmer=80, r=255, g=255, b=255, feature=25),
    ),
    (
        "2c dimmer 255",
        "Tope.",
        frame(dimmer=255, r=255, g=255, b=255, feature=25),
    ),
    (
        "3a solo rojo",
        "Solo rojo. Si ves otro color, el mapa RGB está cruzado.",
        frame(dimmer=255, r=255, feature=25),
    ),
    (
        "3b solo verde",
        "Solo verde.",
        frame(dimmer=255, g=255, feature=25),
    ),
    (
        "3c solo azul",
        "Solo azul.",
        frame(dimmer=255, b=255, feature=25),
    ),
    (
        "4 blanco RGB",
        "R+G+B=255. Este PAR no tiene W.",
        frame(dimmer=255, r=255, g=255, b=255, feature=25),
    ),
    (
        "5 skip",
        "ch5=40/120/200 con ch6=25 NO parpadeó (sonda 2026-08-27). Caza en --strobe.",
        frame(dimmer=255, r=255, strobe=0, feature=25),
    ),
    (
        "6a ch6=25 DMX",
        "Rojo estático. Referencia lineal.",
        frame(dimmer=255, r=255, strobe=0, feature=25, speed=0),
    ),
    (
        "6b ch6=75 macros, ch7=40",
        "Confirmado: verde estático. ch7 elige color.",
        frame(dimmer=255, r=255, g=40, b=0, strobe=0, feature=75, speed=40),
    ),
    (
        "6c ch6=75 macros, ch7=200",
        "Confirmado: azul. ch7 es selector en esta banda.",
        frame(dimmer=255, r=255, g=40, b=0, strobe=0, feature=75, speed=200),
    ),
    (
        "6d ch6=125 shade, ch7=10",
        "Confirmado: cicla. ch7=80 ya iba rápido; 10 debería ir más lento.",
        frame(dimmer=255, r=255, g=255, b=255, strobe=0, feature=125, speed=10),
    ),
    (
        "6e ch6=125 shade, ch7=220",
        "Confirmado: más rápido. ch7 = speed de shade.",
        frame(dimmer=255, r=255, g=255, b=255, strobe=0, feature=125, speed=220),
    ),
    (
        "6f ch6=175 fade, ch7=80",
        "Confirmado: fade entre colores (no jump), lento.",
        frame(dimmer=255, r=255, g=255, b=255, strobe=0, feature=175, speed=80),
    ),
    (
        "6g ch6=175 fade, ch7=220",
        "Mismo fade, ch7 alto. Debería acelerar el lerp.",
        frame(dimmer=255, r=255, g=255, b=255, strobe=0, feature=175, speed=220),
    ),
    (
        "6h ch6=225 pulse, ch7=80",
        "Confirmado: pulso suave, no llega a 0.",
        frame(dimmer=255, r=255, g=80, b=0, strobe=0, feature=225, speed=80),
    ),
    (
        "6i ch6=225 pulse, ch7=220",
        "Pulse más rápido. Sigue sin apagar.",
        frame(dimmer=255, r=255, g=80, b=0, strobe=0, feature=225, speed=220),
    ),
    (
        "7 mic ch6=253, ch7=128",
        "251–255 sound. Haz ruido / palmas.",
        frame(dimmer=255, r=255, g=255, b=255, strobe=0, feature=253, speed=128),
    ),
    (
        "8 blackout",
        "Apagado final.",
        frame(),
    ),
]


SOUND_STEPS: list[tuple[str, str, list[int]]] = [
    (
        "snd0 baseline blanco ch7=128",
        "Ya vimos destello amarillo. Referencia. Aplaude.",
        frame(dimmer=255, r=255, g=255, b=255, feature=253, speed=128),
    ),
    (
        "snd1 solo R",
        "¿El destello pasa a rojo o sigue amarillo?",
        frame(dimmer=255, r=255, g=0, b=0, feature=253, speed=128),
    ),
    (
        "snd2 solo G",
        "¿Verde o amarillo?",
        frame(dimmer=255, r=0, g=255, b=0, feature=253, speed=128),
    ),
    (
        "snd3 solo B",
        "¿Azul o amarillo?",
        frame(dimmer=255, r=0, g=0, b=255, feature=253, speed=128),
    ),
    (
        "snd4 R+G",
        "Si RGB pintara, esto es amarillo de verdad. ¿Cambia algo vs baseline?",
        frame(dimmer=255, r=255, g=255, b=0, feature=253, speed=128),
    ),
    (
        "snd5 magenta R+B",
        "¿Magenta o amarillo?",
        frame(dimmer=255, r=255, g=0, b=255, feature=253, speed=128),
    ),
    (
        "snd6 ch7=0",
        "¿Más sordo, otro color, o igual?",
        frame(dimmer=255, r=255, g=255, b=255, feature=253, speed=0),
    ),
    (
        "snd7 ch7=40",
        "ch7 bajo. ¿Sensibilidad o paleta?",
        frame(dimmer=255, r=255, g=255, b=255, feature=253, speed=40),
    ),
    (
        "snd8 ch7=200",
        "ch7 alto. ¿Más sensible, otro color, o igual?",
        frame(dimmer=255, r=255, g=255, b=255, feature=253, speed=200),
    ),
    (
        "snd9 dimmer 40",
        "¿El destello se ve más flojo o el dimmer no cuenta?",
        frame(dimmer=40, r=255, g=255, b=255, feature=253, speed=128),
    ),
    (
        "snd10 ch5=120",
        "ch5 en sound. ¿Cambia el flash o se ignora?",
        frame(dimmer=255, r=255, g=255, b=255, strobe=120, feature=253, speed=128),
    ),
    (
        "snd11 ch6=251 borde",
        "Banda sound 251–255. ¿Sigue reaccionando?",
        frame(dimmer=255, r=255, g=255, b=255, feature=251, speed=128),
    ),
    (
        "snd12 ch6=255 tope",
        "ch6 al máximo. ¿Igual que 253?",
        frame(dimmer=255, r=255, g=255, b=255, feature=255, speed=128),
    ),
]

STROBE_STEPS: list[tuple[str, str, list[int]]] = [
    (
        "s0 rojo base",
        "Rojo estático. ch6=25 DMX, ch5=0, ch7=0. Si parpadea, algo quedó sucio.",
        frame(dimmer=255, r=255, strobe=0, feature=25, speed=0),
    ),
    (
        "s1 ch6=0 ch5=40",
        "Misma idea de strobe pero ch6=0 (no 25). ¿Parpadea?",
        frame(dimmer=255, r=255, strobe=40, feature=0, speed=0),
    ),
    (
        "s2 ch6=0 ch5=200",
        "ch6=0, ch5 alto. ¿Strobe más rápido?",
        frame(dimmer=255, r=255, strobe=200, feature=0, speed=0),
    ),
    (
        "s3 ch6=25 ch5=8",
        "Algunos PARs: 0–7 off, 8+ strobe. ch5=8 mínimo.",
        frame(dimmer=255, r=255, strobe=8, feature=25, speed=0),
    ),
    (
        "s4 ch6=25 ch5=255",
        "ch5 al tope. Si sigue estático, ch5 no es strobe.",
        frame(dimmer=255, r=255, strobe=255, feature=25, speed=0),
    ),
    (
        "s5 ch5=0 ch7=40",
        "Hipótesis: en DMX el strobe es ch7. ¿Parpadea rojo lento?",
        frame(dimmer=255, r=255, strobe=0, feature=25, speed=40),
    ),
    (
        "s6 ch5=0 ch7=120",
        "ch7 medio. ¿Más frecuente?",
        frame(dimmer=255, r=255, strobe=0, feature=25, speed=120),
    ),
    (
        "s7 ch5=0 ch7=200",
        "ch7 rápido. Si nada parpadeó, strobe interno no está en ch5 ni ch7+DMX.",
        frame(dimmer=255, r=255, strobe=0, feature=25, speed=200),
    ),
    (
        "s8 ch6=75 ch7=40",
        "Macros otra vez (verde). Si este modo parpadea, el strobe del menú es la paleta 8 colores.",
        frame(dimmer=255, r=255, strobe=0, feature=75, speed=40),
    ),
    (
        "s9 blackout",
        "Apagado.",
        frame(),
    ),
]

MACRO_STROBE_STEPS: list[tuple[str, str, list[int]]] = [
    (
        "m0 ch6=1 rojo",
        "ch6=0 era negro. ch6=1 debería ser DMX lineal (rojo). Si está negro, la banda lineal empieza más arriba.",
        frame(dimmer=255, r=255, strobe=0, feature=1, speed=0),
    ),
    (
        "m1 ch6=10 rojo",
        "ch6=10, todavía 1–50. Rojo estático.",
        frame(dimmer=255, r=255, strobe=0, feature=10, speed=0),
    ),
    (
        "m2 macros verde ch5=0",
        "ch6=75 ch7=40 verde estático (confirmado). Base.",
        frame(dimmer=255, r=255, strobe=0, feature=75, speed=40),
    ),
    (
        "m3 macros verde ch5=40",
        "Menú: 1–8 = colors strobe. ¿El verde parpadea con ch5=40?",
        frame(dimmer=255, r=255, strobe=40, feature=75, speed=40),
    ),
    (
        "m4 macros verde ch5=120",
        "ch5 medio sobre el mismo macro. ¿Más frecuente? No uses 8 ni 255 (apagan).",
        frame(dimmer=255, r=255, strobe=120, feature=75, speed=40),
    ),
    (
        "m5 macros verde ch5=200",
        "ch5 alto. Si sigue estático, no hay strobe interno usable: hay que hacerlo por script.",
        frame(dimmer=255, r=255, strobe=200, feature=75, speed=40),
    ),
    (
        "m6 macros azul ch5=120",
        "ch7=200 azul + ch5=120. ¿Strobe de otro color de paleta?",
        frame(dimmer=255, r=255, strobe=120, feature=75, speed=200),
    ),
    (
        "m7 blackout",
        "Apagado.",
        frame(),
    ),
]


def run_steps(
    dev,
    fixture: dict,
    steps: list[tuple[str, str, list[int]]],
    auto: float | None,
    *,
    duo: bool = False,
) -> None:
    black = frame()
    try:
        for title, expect, values in steps:
            print(f"\n=== {title} ===", flush=True)
            print(dump_ch(values), flush=True)
            send(dev, fixture, values, duo=duo)
            pause(auto, expect)
    except KeyboardInterrupt:
        send(dev, fixture, black, duo=duo)
        print(json.dumps({"ok": True, "interrupted": True, "blackout": True}), flush=True)
        raise SystemExit(0)
    send(dev, fixture, black, duo=duo)


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Big Dipper LPC008 7ch at A001")
    parser.add_argument(
        "--auto",
        type=float,
        default=None,
        metavar="SEC",
        help="hold each step this many seconds instead of waiting for Enter",
    )
    parser.add_argument(
        "--strobe",
        action="store_true",
        help="hunt strobe on ch5/ch7 in DMX linear (already: no usable strobe)",
    )
    parser.add_argument(
        "--macros-strobe",
        action="store_true",
        help="hunt strobe on ch5 while ch6 is in the 8-color macro band",
    )
    parser.add_argument(
        "--sound",
        action="store_true",
        help="sweep RGB/ch5/ch7/dimmer while ch6 is in the sound band (251-255)",
    )
    parser.add_argument(
        "--duo",
        action="store_true",
        help="mirror the 7ch frame to A001 and A008 (14 bytes)",
    )
    args = parser.parse_args()
    fixture = json.loads(FIXTURE_PATH.read_text())
    print(
        f"{fixture['brand']} {fixture['model']}  {fixture['mode']}  "
        f"address {fixture['address']}  {fixture['channels']}ch  RGB (no W)",
        flush=True,
    )
    print("Cierra QLC+ y el panel.\n", flush=True)
    if args.strobe and args.macros_strobe:
        raise SystemExit("usa --strobe o --macros-strobe, no ambos")
    if args.sound:
        print("Sound por DMX: aplaude en cada paso. ¿RGB/ch7/ch5 cambian el destello?", flush=True)
        steps = SOUND_STEPS
    elif args.macros_strobe:
        print("Caza strobe sobre macros (ch6=75). ch6=0 apaga; ch5=8/255 apagan.", flush=True)
        steps = MACRO_STROBE_STEPS
    elif args.strobe:
        print("Caza strobe DMX: ya vimos que ch5/ch7 en lineal no parpadean.", flush=True)
        steps = STROBE_STEPS
    else:
        print("Walk completo. Strobe interno: --macros-strobe (lineal no tiene).\n", flush=True)
        steps = FULL_STEPS
    dev = dmx.open_udmx()
    run_steps(dev, fixture, steps, args.auto, duo=args.duo)
    if args.sound:
        print(
            "\nAnota por paso: color del destello, si ch7 cambia sensibilidad, "
            "si dimmer/ch5 hacen algo. Cierra en negro.",
            flush=True,
        )
    elif args.macros_strobe:
        print(
            "\nAnota: ¿ch6=1 enciende? ¿ch5 sobre verde/azul parpadea?",
            flush=True,
        )
    elif args.strobe:
        print(
            "\nDMX lineal: ch6=0 negro; ch5=8/255 destello luego negro; "
            "ch7 no es strobe. Siguiente: --macros-strobe.",
            flush=True,
        )
    else:
        print(
            "\nch1 dimmer, ch2-4 RGB, ch6 modo (0=off), ch7 selector/speed. "
            "Strobe interno: --macros-strobe.",
            flush=True,
        )


if __name__ == "__main__":
    main()
