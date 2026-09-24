---
name: dmx-par
description: Control Deo Volente stage lights over Anyma uDMX — JM-P13 PAR, LPC008, and LED 60W Beam+Halo duo (web pad + Android on Seeker). Use when the user mentions DMX, uDMX, PAR, JM-P13, beam halo, A001, A031, Seeker, show.json, lighting pad, or the Android beam app.
---

# DMX (`~/deovolente/dmx`)

Anyma **uDMX** holds the last frame. Quit QLC+ first. Do not run two panels (or panel + CLI) at the same time. USB from this chat needs `required_permissions: ["all"]`.

## Beam Halo duo (A001 + A031)

Two LED 60W Beam+Halo heads, 30CH each (60-byte frames). Iterate on the **web pad**, then rebuild the phone.

Shared sources (web and Android both read these):

| File | What |
|------|------|
| `beam-halo-duo/show.json` | Pad groups, scene names, labels, subtitle |
| `beam-halo-duo/sequences/*.json` | Cues. Android copies them into APK assets at build |

Engines are **not** shared runtime: web uses `scripts/beam_halo_duo.py`; the phone is a Kotlin port (`android/app/src/main/java/org/deovolente/beam/engine/`). Goldens catch drift. A Python engine change does not reach Seeker until Kotlin is updated.

Layout CSS vs native buttons is per platform. Changing `show.json` is enough for buttons/groups.

```bash
PANEL_BEAM="/Users/joseb/deovolente/dmx/.venv/bin/python /Users/joseb/deovolente/dmx/panel_beam_halo_duo.py"
$PANEL_BEAM   # http://127.0.0.1:8765/
```

The phone build of the beam-only pad is superseded by the show console below. Seeker is USB **host**; plug uDMX via OTG.

## Show console (LPC008 7CH + BEAM 30CH)

Home picks how many of each fixture and shows the DMX map (PAR first from channel 1, or BEAM first). One look list. Palette and speed are one shared setting and stay put when the look changes. A palette can be two colors or more (disco is five, each with its own beam and halo). Motor looks move only the BEAMs; the PARs take the palette. Light looks (breathe, strobe, chase, fade, relámpago, random) run on both and park the BEAMs at center.

```bash
PANEL_SHOW="/Users/joseb/deovolente/dmx/.venv/bin/python /Users/joseb/deovolente/dmx/panel_show.py"
$PANEL_SHOW   # http://127.0.0.1:8766/
```

Catalog: `show/looks.json`, `show/palettes.json`. Do not run this together with another panel. The Seeker app (`android/`, `org.deovolente.beam`) is this same console: rig, shared palette and speed, and the look list. Build the APK with `android/scripts/install-seeker.sh` (Docker — macOS `aapt2` hangs).

# DMX PAR (JM-P13)

7-channel VEVOR JM-P13 at address **1** (`d001`).

## Run

```bash
DMX="/Users/joseb/deovolente/dmx/.venv/bin/python /Users/joseb/deovolente/dmx/scripts/dmx.py"
PANEL="/Users/joseb/deovolente/dmx/.venv/bin/python /Users/joseb/deovolente/dmx/panel.py"
```

USB needs `required_permissions: ["all"]`. Do not run two panels at once.

```bash
$PANEL
$DMX look tungsteno
$DMX play sangre-breathe --no-audio
$DMX blackout
```

LPC008 uno (A001): `panel_lpc008.py`. Duo (A001+A008, complementary):

```bash
PANEL_LPC="/Users/joseb/deovolente/dmx/.venv/bin/python /Users/joseb/deovolente/dmx/panel_lpc008.py"
PANEL_DUO="/Users/joseb/deovolente/dmx/.venv/bin/python /Users/joseb/deovolente/dmx/panel_lpc008_duo.py"
$PANEL_DUO
```

`$DMX look <name>` for static / internal strobe. `$DMX play <name> --no-audio` for engines (Ctrl+C → blackout). Cue loops need `--loop`. The panel loops cue sequences until another button; engines run until the next click. Closing the window blackouts.

## Scene bank

Speed: internal ch7 **40 / 120 / 200**. Two-color script **2 Hz / 12 fps** (tope USB); lento **1 Hz / 8 fps**. Breathe never goes to dimmer 0.

### Camas (`look`)

| Name | Mood |
|------|------|
| `blackout` | cortes |
| `blanco` | hits (`white` alias) |
| `tungsteno` | verso (`warm` alias) |
| `sangre` | coro (`red` alias) |
| `acero` | intro fría |
| `hueco` | puente |
| `fuego` | reentrada |
| `verde` | contraste |

### Strobe 1 color (`look`, ch6 interno)

`strobe-rojo-lento` · `strobe-rojo` · `strobe-rojo-rapido` · `strobe-verde-lento` · `strobe-verde` · `strobe-blanco-medio` · `strobe-azul-lento`

Ramps (`play --loop --no-audio`): `strobe-rojo-velocidad` · `strobe-verde-velocidad`

### Breathe (`play --no-audio`)

`azul-blanco-breathe` · `tungsteno-breathe` · `sangre-breathe` · `hueco-breathe`

### Strobe 2 colores (`play --no-audio`, tope USB)

`strobe-azul-morado` · `strobe-rojo-azul` · `strobe-rojo-blanco` · `strobe-rojo-azul-lento`

### Fade / build

`fade-colores` · `fade-calor` · `fade-frio` · `build-verso-coro` (`--loop`)

Song: `play fallar` (audio in the JSON). Demo leftovers: `fx-demo`.

## What the fixture cannot do (script engines)

| Limit | Engine | Use |
|-------|--------|-----|
| Pulse is 0–full, no floor | `breathe` | `*-breathe` |
| Strobe is one color | `strobe_colors` | `strobe-rojo-azul` etc. 2 Hz @ 12 fps |
| Gradient is a fixed palette | `color_fade` | `fade-calor` / `fade-frio` |

Do not use fixture pulse, gradient, jump, or mic. Do not run two-color strobe above 2 Hz / 12 fps.

## Channels

Ch1 dimmer, ch2–5 RGBW, ch6 `dimmer` 0 / `strobe` 32 / `jump` 75 / `gradient` 125 / `pulse` 175, ch7 speed.

## Workflow

1. `status`. Missing adapter → quit QLC+, reseat USB.
2. One scene at a time (panel or CLI). Print CLI JSON.
3. `blackout`, panel BLACKOUT, or Ctrl+C on a play engine.

Do not open QLC+.
