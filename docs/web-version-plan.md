# Consola de show en el navegador

Plan de una consola que corre entera en Chrome o Edge, se publica como sitio estático y habla con el Anyma uDMX por WebUSB. No hay servidor Python. Este documento no implementa esa consola: fija el alcance, el orden de trabajo y la puerta de entrada.

La recomendación es esta. La v1 es la consola de show (la de `panel_show.py`, hoy en `127.0.0.1:8766`): rig de LPC008 7CH y cabezas LED 60W Beam+Halo 30CH, paleta y velocidad compartidas, lista de looks. El sitio es Vite + TypeScript, sin framework de UI, desplegado en Vercel. Python sigue siendo la fuente de verdad de los frames; el navegador se compara contra los goldens que ya usa Kotlin. Antes de portar el motor hay un spike de una página: abrir el uDMX y medir si un `SET_RANGE` de 60 y de 74 bytes aguanta 12–18 fps en el Mac y en el Seeker. Si ese spike falla, el porte se detiene y se siguen usando el panel Python y la APK.

El APK del Seeker se queda. Chrome no puede sostener un servicio en primer plano con el USB abierto cuando el teléfono se apaga o se cambia de app. La APK sí (`DmxService`, `PARTIAL_WAKE_LOCK`, tipo `connectedDevice`).

## Qué hay hoy

Un solo proceso es dueño del dongle. El uDMX retransmite el último frame para siempre. QLC+, el panel Python y la APK no pueden estar abiertos a la vez.

| Pieza | Dónde | Qué hace |
|---|---|---|
| USB | `scripts/dmx.py` | vid `0x16c0`, pid `0x05dc`. `SET_RANGE` = bRequest 2, `bmRequestType` vendor + device + host-to-device (`0x40`). `wValue` = largo, `wIndex` = canal inicial (0 en el show), datos = el frame. Timeout del camino caliente: 25 ms (`send_range_once`). |
| La misma transfer en Android | `android/.../usb/UdmxUsb.kt` | `controlTransfer` con los mismos números. Reclama la interfaz 0. |
| Mapa del rig | `scripts/show_rig.py` | Hasta 8 PAR y 8 BEAM. `lpc_first` o `beam_first`, desde el canal 1. 2 BEAM → direcciones 1 y 31, 60 bytes. 2 PAR → 1 y 8, 14 bytes. 2+2 con PAR primero → A001 A008 A015 A045, 74 bytes. |
| Motor del show | `scripts/show_dispatch.py` | `ShowPlayer.frame(now, t)`. Geometría a ~18 fps (el `fps` de la secuencia). Looks de luz a 12 fps. Paleta y escala de velocidad se aplican encima de la secuencia. |
| Frames de las cabezas | `scripts/beam_halo_duo.py` | 16 motores en `FRAME_MAKERS`. El show usa los 18 JSON de `beam-halo-duo/sequences/`. |
| Looks de luz | `LightGesture` en `show_dispatch.py` | breathe, strobe, chase, fade, relámpago, random. El relámpago reutiliza `_Bolt` de `scripts/lpc008_duo.py`. CH6 del PAR en modo lineal es 25. |
| UI | `panel_show.py` | HTML embebido. Home (cuentas, orden, mapa) y pad (paletas, velocidades, grupos, BLACKOUT, reconectar). `localStorage`: `deo.show.rig` y `deo.show.tune`. Default del pad: 0 PAR, 2 BEAM, orden `lpc_first`, paleta `blanco`, velocidad `medio`. |
| Reloj | `dmx.sync_frame` | Paso `1/fps` con `perf_counter`. Si el USB se atrasa, se saltan frames; no se recupera en ráfaga. A los 20 fallos seguidos el enlace se da por muerto y se reconecta. Cada 1 s, si no hay look, se reenvía el último buffer. |
| Teléfono | `android/`, paquete `org.deovolente.beam` | El mismo show. Los JSON entran al APK como assets. El hilo del USB es un `Thread` con `Thread.sleep`, no el hilo de UI. |
| Pruebas | `scripts/test_show_console.py`, `GoldenFrameTest.kt`, `ShowConsoleTest.kt` | 14 secuencias deterministas, 24 frames, semilla 1. Los goldens viven en `android/app/src/test/resources/goldens/` y los genera `android/scripts/dump_goldens.py`. |

`SET_SINGLE` (bRequest 1) existe en `dmx.py` para el CLI del JM-P13. La consola de show no lo usa. La v1 tampoco.

Datos que el sitio importa tal cual, sin copiarlos a otro formato:

- `show/looks.json` — 5 velocidades (`medio` = escala 1) y 24 looks en 5 grupos.
- `show/palettes.json` — colores con `r,g,b` y, cuando hace falta, `w` y `halo`. Disco tiene 5.
- `beam-halo-duo/sequences/*.json` — las 18 secuencias que citan los looks de geometría.
- Cinco secuencias de luz en `lpc008-duo/sequences/`: `breathe-calida`, `strobe-primario-medio`, `chase-primario-medio`, `fade-medio`, `relampago-blanco`. El look `random` no tiene archivo: los tiempos van en el propio look (`holdMin` 0.35, `holdMax` 1.4, `fps` 12).

`beam-halo-duo/show.json` es el pad viejo de solo cabezas. La APK ya no es ese pad. La v1 no lo muestra.

El blackout de una cabeza no es un buffer de ceros. `blackout_frame()` deja pan 128, tilt 128 y speed 180, y apaga dimmer, strobe, beam, halo y reset. Un cero en pan/tilt manda el motor al tope. El PAR sí se apaga con 7 ceros (CH6 = 0 es off en el LPC008). Cualquier prueba con las cabezas enchufadas usa ese frame.

## Crystal Ball

Las notas actuales describen una bola RGB de 6 canales en A001 (`fixtures/crystal-ball.json`, `crystal-ball/looks.json`, `panel_crystal_ball.py`, manual en PDF). En este repo no están esos archivos. `SKILL.md` commiteado tampoco la nombra. La v1 no la incluye y no inventa su mapa. Cuando esos archivos entren al repo, puede ser un panel aparte: no comparte universo con un LPC008 que también esté en A001.

## 1. WebUSB y el uDMX

El camino de bytes ya está resuelto en dos lenguajes. Falta saber si el navegador deja hacer esa misma transfer.

La llamada equivalente a `send_range_once` es:

```js
await device.controlTransferOut(
  {
    requestType: "vendor",
    recipient: "device",
    request: 2,
    value: payload.byteLength,
    index: 0,
  },
  payload,
);
```

`value` y el largo del `Uint8Array` tienen que coincidir, como en pyusb y en `UdmxUsb.sendRangeOnce`. `index` es el canal DMX inicial, 0 para el universo del show.

El firmware público de uDMX (V-USB, low-speed, 1.5 Mbit/s) suele presentarse así: VID/PID compartidos de obdev para libusb (`0x16c0` / `0x05dc`), paquete máximo del endpoint 0 de 8 bytes, una interfaz, cero endpoints de datos, toda la conversación por el pipe de control. El spike tiene que loguear el descriptor real (`manufacturerName`, `productName`, clase de la interfaz, número de endpoints, `bMaxPacketSize0`). Si el aparato de Jose no coincide, se anota y se decide con ese log, no con el firmware de memoria.

Chrome parte una escritura de control más larga que 8 bytes en varios paquetes. pyusb ya manda el frame entero de una vez (60 bytes en el dúo, 74 en 2 PAR + 2 BEAM, 296 bytes en el tope de 8+8) y el firmware lo acepta. El navegador debería poder hacer lo mismo. Si solo acepta ráfagas de 8 bytes, el spike prueba el plan B: varios `SET_RANGE` con `index` creciente. Eso multiplica los viajes por frame y puede no llegar a 12 fps. Ese resultado es un no, no un motivo para portar el motor igual.

### Navegadores y sistemas

| Dónde | Qué esperar |
|---|---|
| Chrome y Edge en el Mac | El caso principal. Contexto seguro: `https://` o `localhost`. El uDMX no tiene driver de Apple; Chrome lo abre directo. Hay que cerrar QLC+ y `panel_show.py` antes, porque el dispositivo es exclusivo. El primer `requestDevice()` exige un click. Después, `getDevices()` recupera el permiso para ese origen. |
| Chrome en el Seeker, OTG | El teléfono ya es host USB con la APK. Chrome Android tiene WebUSB en una pestaña de primer plano. El spike de teléfono no puede usar el `localhost` del Mac: el puerto OTG lo ocupa el dongle, así que no hay ADB por el mismo cable. Hace falta un HTTPS público (el preview de Vercel). |
| Windows | WebUSB solo ve el dispositivo si el driver es WinUSB. El uDMX viejo no trae el descriptor WCID, así que hay que instalar WinUSB con Zadig para `16C0/05DC`. Ese cambio puede romper pyusb en esa máquina. Fuera de la v1 salvo que Jose lo pida. |
| iPhone / iPad | Sin WebUSB. Safari y el resto de navegadores en iOS son WebKit. Fuera de alcance. |
| Firefox | Sin WebUSB. |

El pid `0x05dc` lo comparten otros aparatos V-USB. Después de abrir, si `productName` no parece uDMX, se suelta el dispositivo y se avisa. El filtro de `requestDevice` igual limita por vid y pid.

### Reloj, pestaña y pantalla

El show no es un loop de dibujo. A 18 fps el presupuesto es 55 ms; a 12 fps, 83 ms. El bucle copia el de `sync_frame`: `performance.now()`, esperar hasta el deadline, armar el frame, una transfer, y si llegamos tarde se salta el índice. `requestAnimationFrame` se deja para pintar el simulador. rAF se para cuando la pestaña no se ve y va enganchado al refresco de la pantalla, no al paso de 1/18 s.

`setTimeout` en primer plano tiene resolución de sobra para 55 ms. En segundo plano Chrome aplasta los timers (y también los de un worker) a 1 s o peor, y acaba congelando la página. Un worker no salva eso. La Screen Wake Lock (`navigator.wakeLock.request("screen")`) evita que el Mac o el teléfono atenúen la pantalla mientras la pestaña está visible. No es el `PARTIAL_WAKE_LOCK` de la APK: si Jose cambia de app, bloquea el Seeker o el navegador manda la pestaña a dormir, el bucle se detiene y el uDMX se queda en el último frame. Las luces no hacen blackout solas.

Cerrar la pestaña tiene el mismo límite. `pagehide` puede intentar un blackout, y hay que intentarlo, pero el navegador puede cortar la transfer a mitad. El botón BLACKOUT es el camino fiable. Conviene decirlo en la propia UI.

Criterio práctico para dar el USB por bueno, medido en el spike y otra vez con el motor real:

- 10 s seguidos, payload de 60 bytes a 18 fps, y de 74 bytes a 12 y a 18 fps.
- Menos de un 5 % de transfers fallidas, sin racha de 20.
- Mediana de la transfer por debajo de 20 ms. Entre 20 y 30 ms se anota y se baja el fps de geometría. Por encima de 30 ms, o si hay que trocear a 8 bytes y no se sostienen 12 fps, WebUSB no sirve para este show.

El tope de 12 fps que las notas marcan para el estrobo de dos colores del JM-P13 es de ese motor viejo (`scripts/dmx.py`), no del show. Los looks de luz del show ya nacen a 12 fps. La geometría pide 18 porque es lo que las secuencias declaran y lo que la APK ya sostiene.

### Spike mínimo (fase 0, puerta de entrada)

Una sola página estática, sin motor y sin Vite si estorba. Botón «Conectar uDMX».

1. `requestDevice({ filters: [{ vendorId: 0x16c0, productId: 0x05dc }] })`.
2. `open()`, `selectConfiguration(1)` si hace falta, `claimInterface(0)`.
3. Log del descriptor: nombres, clase, endpoints, tamaño de paquete.
4. Con las cabezas desconectadas, o con un frame seguro si están conectadas: 7 bytes (un PAR en rojo, dimmer 255), 30, 60 y 74 bytes. Nunca un buffer de ceros contra una cabeza: pan/tilt 128, speed 180, dimmer 0.
5. Durante 10 s, contar ok, fallos y milisegundos por transfer a 12 y a 18 fps.
6. Blackout con el frame seguro y soltar la interfaz.
7. Repetir en Chrome del Mac (`localhost` vale) y en Chrome del Seeker contra un preview HTTPS.
8. Probar el choque: con `panel_show.py` abierto, el `open()` del navegador tiene que fallar con un mensaje claro, y al revés.

Salida escrita en el README del spike, con los números. Verde: se pasa a la fase 1. Rojo (no reclama la interfaz, `controlTransferOut` rechazado, o no hay 12 fps ni troceando): se cierra el experimento y se sigue con Python y la APK. No se porta el motor «por si acaso».

## 2. Arquitectura

### Framework

Vite + TypeScript, DOM a mano, un solo `index.html` con las dos pantallas que ya tiene `panel_show.py` (home y pad). La UI actual son ~250 líneas de HTML/CSS/JS dentro de ese archivo. React o Next sobran: no hay rutas, no hay servidor, no hay datos remotos.

El proyecto vive en `web/`. Vite mete los JSON en el bundle al importarlos. El build de Vercel se lanza desde la raíz del repo (`npm ci --prefix web && npm --prefix web run build`, salida `web/dist`) para que `../show`, `../beam-halo-duo/sequences` y `../lpc008-duo/sequences` existan durante el build. Si el «Root Directory» de Vercel se pone en `web/`, hay que confirmar que el build sigue viendo esos padres; si no, se deja la raíz del repo.

No hay funciones, ni middleware, ni base de datos. El dongle está en la máquina de Jose; un servidor no puede hablar con él.

### Qué se porta

Se traduce el recorte del show, con el Kotlin como mapa (ahí ya están `pythonRound` y `pythonMod`) y con Python como oráculo.

| Se porta | No se porta en v1 |
|---|---|
| `show_rig.build_rig` | `scripts/dmx.py` más allá de la transfer: CLI, looks del JM-P13, pumps de breathe/fade |
| Catálogo, paleta, velocidad, `ShowPlayer`, `LightGesture`, `beam_fan_heads`, `blackout_buffer` | Los pumps USB de `lpc008_duo.py` (el gesto de luz ya está reescrito en `LightGesture`) |
| `head_frame`, `clamp`, `blackout_frame`, los 16 `FRAME_MAKERS`, `RandomHead` | `panel.py`, `panel_lpc008.py`, `panel_lpc008_duo.py`, `panel_beam_halo_duo.py` |
| `_Bolt` / `_strike_queue` para el relámpago | Los ~60 JSON de `lpc008-duo/sequences/` que ningún look del show cita |
| Bucle tipo `pump` / `sync_frame`, salud USB, heartbeat de 1 s | Kotlin/JS, Pyodide, un servidor puente |

El motor Kotlin del show ( `ShowConsole.kt`, `BeamEngines.kt`, `Head.kt`, `RandomHead.kt` y el reloj de `FramePump.kt` ) son unas 1.300 líneas. El TypeScript es una traducción de ese tamaño, más la UI y `udmx.ts`. No es un diseño de luces nuevo.

Tres detalles numéricos que el porte tiene que copiar, no redescubrir:

- `round` de Python 3 es half-to-even. `Math.round(0.5)` en JS da 1; Python da 0. `Head.kt` ya tiene `pythonRound`. Los dimmers de breathe y los fades pasan por `int(round(...))`.
- El módulo de Python devuelve resto positivo. `(-1) % 256` es 255 en Python y −1 en JS. Hace falta `pythonMod` en cada fase, aunque `t` del show sea ≥ 0.
- `Math.sin` puede diferir de `math.sin` en 1 ulp. El assert de los goldens es sobre bytes, no sobre floats. Si un frame cae a un lado del .5, se corrige el redondeo; no se afloja el test.

El reloj de preview de Python (`preview_frames`) fija `random.seed(1)` y sustituye `clock()` por `t = n/fps`. El TS tiene que aceptar un `now` inyectado. Si un motor aleatorio lee `performance.now()` por su cuenta, el golden no puede cerrar.

### RNG

Los 14 goldens dejan fuera los motores aleatorios (`tirones-random-calido`, `abanico-random-frio`, `abre-cierra-random-andino`, `abanico-tiron-disco`) y también el relámpago y el look `random`. Kotlin usa `kotlin.random.Random`, que no es el Mersenne Twister de CPython. Hoy Python y la APK no son bit a bit en esos looks; se parecen en los rangos (`hold_min`, `hold_max`, ráfagas).

Para el navegador, la paridad que se exige en v1 es la que ya está testeada: goldens deterministas y los asserts de `test_show_console.py` / `ShowConsoleTest.kt`. Los looks aleatorios se portan con los mismos parámetros. Un RNG compatible con `random.Random` de CPython entra solo si Jose quiere goldens con semilla también para relámpago y random. No bloquea el spike ni el simulador.

### Bucle y estado

Un solo bucle async en el hilo principal, una transfer en vuelo, la misma lógica de salto que `sync_frame`. A 18 fps el hilo aguanta: el frame es un `Uint8Array` corto y la UI son botones. Un worker queda como salida si el pad se traba, y el spike anota si `USBDevice` se puede usar dentro de un dedicated worker en el Chrome que Jose tiene. No es requisito de la v1.

Estado en `localStorage`, misma forma que el panel y que las prefs `deo.show` de la APK:

- `deo.show.rig`: `{ nLpc, nBeam, order }`
- `deo.show.tune`: `{ palette, speed }`
- `deo.show.look`: el id activo, para volver a arrancar el último look al reconectar (el panel hoy no lo guarda; la web sí puede)

El origen de Vercel y el de `127.0.0.1:8766` no comparten `localStorage`. Las claves coinciden para que el código se entienda, no para migrar solo.

Modos de salida, excluyentes: `usb` o `sim`. El simulador no abre el dispositivo.

## 3. Alcance de la v1

Entra la consola de show, completa:

- Home: 0–8 LPC008, 0–8 BEAM, PAR primero o BEAM primero, mapa de direcciones (A001, A008, …).
- Pad: grupos de `show/looks.json`, paleta y velocidad que no se mueven al cambiar de look, BLACKOUT, reconectar, línea de estado USB (ok, fail, racha, saltos).
- Geometría con N=1 (solo la cabeza A del dúo), N=2 (el dúo) y N>2 (abanico alrededor de 128).
- Looks de luz en PAR y en BEAM, con las cabezas quietas en el centro. Una paleta de más de dos colores rota; disco se ve en beam y en halo.
- Simulador sin dongle.
- Wake lock y aviso cuando `document.visibilityState` deja de ser `visible`.

Queda para después, a propósito:

- Paneles sueltos: JM-P13 (`panel.py`, `looks/`, `sequences/`), LPC008 solo, dúo LPC008 con su catálogo largo, pad viejo de solo Beam+Halo.
- Crystal Ball, hasta que sus archivos estén en el repo.
- Modos de sonido / micrófono del aparato. El show no los usa.
- iOS, Firefox, Windows (salvo respuesta de Jose).
- Editar looks en el navegador.
- Dos clientes a la vez. El dongle tiene un solo dueño; un segundo teléfono no puede compartir el USB.
- Sustituir la APK. Se revalúa si, con el sitio en el Seeker, a Jose le basta tener Chrome delante durante el show.

## 4. Paridad con Python y Kotlin

Python genera el byte. Kotlin y, cuando exista, TypeScript se comparan con eso. Un cambio de motor en Python no llega solo al navegador ni al teléfono: hay que regenerar goldens y actualizar el porte. Es el mismo trato que ya hay entre `dump_goldens.py` y `GoldenFrameTest`.

La v1 queda en verde cuando:

1. Vitest (o `node:test`) lee `android/app/src/test/resources/goldens/*.json` y el JSON de la secuencia, corre el frame maker TS en `t = n/fps` con semilla 1 y `now` inyectado, y los 24 frames coinciden byte a byte. También el `fps`.
2. Los casos de `scripts/test_show_console.py` y de `ShowConsoleTest.kt` existen en TS: direcciones del rig, tope de 8, abre-cierra con paleta sangre en 2 PAR (`[255,255,0,8,0,25,0]` y `[255,200,0,0,0,25,0]`), disco de 5 colores ciclando el beam, breathe con las cabezas en pan/tilt 128, `prepare` de `abanico-tiron-disco` y `corona-reloj-dardo` con la paleta disco.
3. `python scripts/test_show_console.py` sigue pasando. Los dos se corren en CI cuando el repo tenga el workflow; hasta entonces, en local antes de dar la fase 2 por cerrada.

Hace falta un golden de show, no solo de dúo. Los 14 archivos actuales son 60 bytes de dos cabezas con la paleta nativa de la secuencia. El navegador casi siempre manda otra cosa: paleta aplicada, PAR delante, o N distinto de 2. Al portar, se agregan 2 o 3 capturas desde `ShowPlayer` (por ejemplo abre-cierra N=2 con paleta nativa, 2 PAR + 1 BEAM en breathe en un `t` fijo, y un fan de 3 BEAM) generadas por Python y commiteadas al lado de los goldens actuales. Si TS y Python discrepan, manda Python.

Los looks aleatorios, en v1, se assertan como la APK: largo correcto y bytes en 0–255. Bit a bit con semilla queda en la pregunta abierta del RNG.

## 5. Despliegue y cómo se usa

Sitio estático en Vercel, HTTPS del `*.vercel.app`. WebUSB exige contexto seguro; ese dominio lo es. `index.html` sin caché larga, para que un deploy nuevo aparezca al recargar. Los assets con hash pueden cachearse. No hace falta `vercel.ts` ni funciones: un `output` estático alcanza.

El link enseña el catálogo de looks a quien lo tenga. El USB no se puede disparar a distancia: sin el dongle, la página solo simula, y el permiso del dispositivo lo da el navegador en esa máquina. Si el catálogo no debe ser público, Vercel Deployment Protection (password) se enciende después; no cambia el código.

### En el Mac

1. Cerrar QLC+ y no dejar corriendo `panel_show.py` ni otro panel.
2. Chrome o Edge, abrir el link.
3. Enchufar el uDMX.
4. «Conectar uDMX» y elegir el dispositivo en el diálogo.
5. Home y pad, igual que en el puerto 8766.
6. Dejar esa pestaña delante. La página pide wake lock al conectar.

### En el Seeker

1. Cable OTG, uDMX, Chrome. La APK cerrada: si no, el USB está ocupado.
2. El mismo link, «Conectar uDMX», aceptar el permiso.
3. Chrome en primer plano, pantalla encendida, aviso de batería si el sistema ofrece restringir a Chrome.
4. Para un show con el teléfono en el bolsillo, seguir con la APK. El navegador no reemplaza ese caso.

### Simulador

Botón «Simular» en la pantalla de conectar, también cuando `navigator.usb` no existe (Safari incluido), para poder enseñar el sitio sin el dongle.

El simulador corre el mismo `ShowPlayer` y el mismo reloj. Cada frame pinta:

- El buffer que se habría mandado, byte por byte, con la dirección DMX.
- Cada LPC008 como una pastilla del color `dimmer × RGB` y sus 7 números.
- Cada BEAM como un punto en un cuadrado (pan y tilt, 128 en el centro), el color del beam (canales 8–11) y los 6 segmentos del halo (canales 12–29), con el dimmer del canal 6.

Así se ve un look mal portado sin encender las luces. El dibujo puede ir en rAF leyendo el último buffer; el reloj del look sigue siendo el de 12/18 fps, para que el tiempo no dependa del refresco del monitor.

## 6. Fases, riesgos, preguntas

El spike es la puerta. Si sale mal, el esfuerzo se queda en la fase 0. Si sale bien, el resto es traducir un motor que ya existe dos veces y envolverlo en la UI que ya está diseñada.

| Fase | Tamaño | Qué se entrega | Se cierra cuando |
|---|---|---|---|
| 0. Spike | Chico. Una página, sin motor. Depende de tener el uDMX en el Mac y en el Seeker. | `web/spike` o un HTML suelto, más el log de los números. Preview HTTPS para el teléfono. | Criterio de la sección 1, en los dos aparatos. |
| 1. Cáscara y simulador | Chico. La UI ya está en `panel_show.py`. | Vite, home, pad, catálogo real, simulador con un buffer falso o el motor a medias. Deploy de Vercel para mirarlo desde el teléfono. | Se puede clickear un look y ver canales, aunque el motor aún no sea el de Python. |
| 2. Motor y paridad | El grueso. Traducción del orden de las ~1.300 líneas del motor Kotlin, más tests. | `ShowPlayer` TS, secuencias importadas, vitest contra goldens y contra los asserts del rig. | Los tests de la sección 4 en verde, simulador moviendo looks de verdad. |
| 3. USB de verdad | Chico si la fase 0 pasó. El protocolo es una transfer. | `udmx.ts`: abrir, reclamar, `SET_RANGE`, racha, reconectar, heartbeat, wake lock, aviso de pestaña oculta, blackout en `pagehide` como intento. | Mac y Seeker con el rig real, los fps del criterio, BLACKOUT visible. |
| 4. Cierre | Chico. | Persistencia, textos en español, nota corta de uso junto al panel, los dos tests corriendo en local (y en CI si se agrega el workflow). | Jose entra al link y corre un look sin el panel Python. |

Orden: 0 antes que 2. La fase 1 puede ir en paralelo con el spike porque no toca USB. La fase 3 no empieza con el criterio en rojo.

### Riesgos

| Riesgo | Qué pasa | Respuesta |
|---|---|---|
| `claimInterface(0)` falla en una interfaz sin endpoints | No hay USB desde Chrome | Fin del experimento en la fase 0. Siguen Python y la APK. |
| Solo pasan transfers de 8 bytes | 74 bytes son ~10 viajes; 18 fps se cae | Medir en el spike. Si no hay 12 fps sostenidos, mismo fin. |
| El Seeker duerme a Chrome | El look se congela en el último frame | Aviso en pantalla, wake lock, y la APK para ese uso. No prometer bolsillo. |
| Cerrar la pestaña no apaga | El uDMX sigue emitiendo | Botón BLACKOUT grande. `pagehide` como intento, dicho en la UI. |
| Otro programa tiene el dongle | `open()` falla | El texto de error nombra a QLC+ y al panel Python. |
| Otro aparato con el mismo VID/PID | Se abre el dispositivo equivocado | Chequear `productName` y soltar. |
| Tres motores se desfasan | Un look se ve distinto en la web | Goldens en el test de TS. Python manda. No hay generación automática de TS. |
| `Math.round` o `%` | Un dimmer a un byte de distancia, fácil de no ver | Tests antes de dar la fase 2 por buena. Copiar `pythonRound` / `pythonMod`. |
| Cabeza al tope en una prueba | Pan/tilt 0 | Frames de prueba con 128/128/180. El simulador enseña el byte antes de darle al USB. |
| El link es público | Alguien ve los nombres de los looks | Pregunta abierta. El USB sigue siendo local. |

### Preguntas para Jose

1. ¿Corremos el spike en tu Mac y en el Seeker, con el uDMX, antes de portar el motor? Es la recomendación. Sin ese ensayo no hay cómo saber si Chrome acepta el aparato.
2. ¿La v1 es solo la consola de show, y la APK se queda como respaldo del teléfono? Es lo que este plan asume.
3. ¿Crystal Ball espera a que subas sus archivos, o la dejamos fuera aunque aparezcan pronto?
4. ¿Te sirve que, al cerrar la pestaña o al bloquear el Seeker, las luces se queden en el último frame? El uDMX no se apaga solo, y el navegador no garantiza el blackout al salir.
5. ¿Hace falta paridad bit a bit en relámpago y en los looks random (RNG de CPython, con semilla), o alcanza con que los tiempos y los colores salgan de los mismos parámetros?
6. ¿Te basta un `*.vercel.app` o quieres un dominio propio?
7. ¿Windows entra? Si sí, Zadig + WinUSB para `16C0/05DC`, y hay que asumir que pyusb en esa máquina puede dejar de ver el dongle.
8. ¿El link puede ser público? Quien lo abra ve el catálogo y, sin dongle, el simulador. El permiso USB no viaja. Si prefieres password de Vercel, se activa al desplegar.
9. ¿Mantenemos los tres motores (Python, Kotlin, TS) o, si la web te convence en el Mac, congelamos la APK y solo la tocamos cuando un look nuevo tenga que seguir en el teléfono?
10. ¿El rig por defecto sigue siendo 0 PAR y 2 BEAM, PAR primero, como el panel y la APK?
