# Consola de show en el navegador

La misma consola que `panel_show.py` (LPC008 de 7 canales y Beam+Halo de 30), sin servidor Python. Chrome o Edge hablan con el Anyma uDMX por WebUSB. Sin el dongle, la página simula: pastillas de color, posición de las cabezas y el valor de cada canal.

Python sigue siendo el motor de referencia. `npm test` compara este porte con los goldens de `android/app/src/test/resources/goldens/` y con frames de `ShowPlayer` volcados por `scripts/dump_show_fixtures.py`.

## En local

Desde `web/`, con Node 22:

```bash
npm ci
python3 scripts/dump_show_fixtures.py   # solo si cambian los motores Python
npm test
npm run dev
```

Abre `http://localhost:5173/`. En el Mac, localhost ya es un contexto seguro: WebUSB funciona sin HTTPS. Cierra QLC+ y `panel_show.py` antes de pulsar **Conectar uDMX**. **Simular** no abre el USB.

`npm run build` deja el sitio estático en `web/dist/`. `npm run preview` lo sirve.

## Vercel

El proyecto de Vercel usa esta carpeta como raíz, no el repo entero. Los looks y las secuencias viven al lado, en `show/`, `beam-halo-duo/` y `lpc008-duo/`.

1. Importa el repo.
2. Root Directory: `web`.
3. Activa **Include source files outside of the Root Directory in the Build Step**. Si no, el build no ve `../show/looks.json` y `npm run build` falla con ese aviso.
4. Framework preset: Other.
5. Build command: `npm run build` (también está en `vercel.json`).
6. Output directory: `dist`.
7. Install command: el de npm (`npm ci` si hay lockfile).

No hay variables de entorno ni funciones. El link `*.vercel.app` es HTTPS, que es lo que WebUSB pide. Puede ser público: sin el dongle solo se ve el simulador, y el permiso del USB lo da el navegador en esa máquina.

## Windows (WinUSB)

Chrome en Windows no abre el uDMX si el driver es el de libusb que usan pyusb y QLC+. Hay que instalar **WinUSB** con [Zadig](https://zadig.akeo.ie/). La misma explicación está en el botón **Ayuda** de la consola.

1. Cierra Chrome, QLC+ y el panel Python.
2. Abre Zadig → Options → **List All Devices**.
3. Elige el uDMX. El USB ID tiene que ser **16C0 05DC**.
4. Driver destino: **WinUSB** → Replace Driver.
5. Desenchufa y vuelve a enchufar. En Chrome, **Conectar uDMX**.

Ese cambio sustituye el driver anterior. En esa máquina, pyusb y QLC+ pueden dejar de ver el dongle hasta que lo reviertas.

Para volver atrás: Zadig, el mismo 16C0:05DC, driver destino **libusb-win32** o **libusbK** (el que tenías), Replace Driver. Si no recuerdas cuál era, en el Administrador de dispositivos desinstala el uDMX marcando «eliminar el driver», desenchufa y enchufa, y vuelve a instalar libusb-win32 con Zadig.

Si el aparato no sale en el diálogo de Chrome, o la consola dice que no pudo abrirlo, el estado repite esta pista.

## Límites

- Safari, Firefox e iPhone no tienen WebUSB.
- Un solo programa es dueño del dongle.
- Si la pestaña queda atrás o el teléfono se bloquea, el navegador puede frenar los timers. La página pide Screen Wake Lock, manda los frames desde un worker cuando el navegador lo permite, y al volver a verse (o al reaparecer el USB) retoma el look. No es un servicio en primer plano: para el Seeker en el bolsillo sigue la APK.
- Cerrar la pestaña intenta un blackout, pero el navegador puede cortarlo. El uDMX se queda en el último frame. El botón BLACKOUT es el camino seguro.
- Los looks aleatorios (tirones, relámpago, random) usan los mismos tiempos que Python. No repiten la semilla de CPython, así que un frame suelto no va a coincidir byte a byte.
- Crystal Ball no está en esta versión.
