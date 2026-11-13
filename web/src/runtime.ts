import { beamSequences, catalog, lpcSequences } from "./catalog";
import type { Json } from "./engine/json";
import { blackoutBuffer, buildRig, RigError, ShowPlayer, type Rig } from "./engine/show";
import { explainUsbFailure, UdmxLink, type UsbHint } from "./usb";

export interface ShowStatus {
  line: string;
  usb: string;
  scene: string | null;
  mode: "usb" | "sim" | "off";
  frame: number[];
  rig: Rig;
  paletteId: string;
  speedId: string;
  hint: string;
  connected: boolean;
}

export type RuntimeCommand =
  | { type: "boot" }
  | { type: "open" }
  | { type: "simulate" }
  | { type: "rig"; nLpc: number; nBeam: number; order: string }
  | { type: "play"; lookId: string; paletteId: string; speedId: string }
  | { type: "blackout" }
  | { type: "visible"; visible: boolean }
  | { type: "shutdown" };

interface PlayRequest {
  lookId: string;
  paletteId: string;
  speedId: string;
}

function perf(): number {
  return performance.now() / 1000;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class ShowRuntime {
  readonly usb = new UdmxLink();
  rig: Rig = buildRig(0, 2, "lpc_first");
  paletteId = "blanco";
  speedId = "medio";
  scene: string | null = null;
  mode: ShowStatus["mode"] = "off";
  line = "elige el rig";
  hint = "";
  frame: number[] = [];
  private lastGood: number[] = [];
  private play: PlayRequest | null = null;
  private player: ShowPlayer | null = null;
  private lastPose: [number, number][] = [];
  private gen = 0;
  private visible = true;
  private recoverAt = 0;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private onDisconnect = (event: USBConnectionEvent) => {
    if (event.device === this.usb.device) {
      this.usb.markDead("desconectado");
      void this.recover("uDMX desconectado");
    }
  };
  private onConnect = (event: USBConnectionEvent) => {
    if (event.device.vendorId === 0x16c0 && event.device.productId === 0x05dc && this.mode === "usb") {
      void this.recover("uDMX reconectado");
    }
  };

  constructor(private readonly emit: (status: ShowStatus) => void) {
    const usb = this.usb.api;
    usb?.addEventListener("disconnect", this.onDisconnect);
    usb?.addEventListener("connect", this.onConnect);
    this.heartbeat = setInterval(() => void this.beat(), 1000);
  }

  async handle(command: RuntimeCommand): Promise<void> {
    try {
      switch (command.type) {
        case "boot":
          await this.tryAuto();
          break;
        case "open": {
          const resume = this.play;
          const opened = await this.openGranted();
          if (opened && resume) await this.startPlay(resume);
          break;
        }
        case "simulate":
          await this.simulate();
          break;
        case "rig":
          await this.setRig(command.nLpc, command.nBeam, command.order);
          break;
        case "play":
          await this.startPlay(command);
          break;
        case "blackout":
          await this.blackout();
          break;
        case "visible":
          this.visible = command.visible;
          if (command.visible && this.mode === "usb" && !this.usb.isOpen()) {
            await this.recover("pestaña visible");
          } else if (command.visible && this.play && this.player == null) {
            await this.startPlay(this.play);
          }
          this.push();
          break;
        case "shutdown":
          await this.shutdown();
          break;
        default:
          break;
      }
    } catch (err) {
      if (err instanceof RigError) {
        this.line = err.message;
        this.push();
        return;
      }
      const hint = explainUsbFailure(err, "usar");
      this.fail(hint);
    }
  }

  async openDevice(device: USBDevice): Promise<void> {
    try {
      await this.usb.open(device);
    } catch (err) {
      const hint = explainUsbFailure(err, "abrir");
      this.fail(hint);
      return;
    }
    this.mode = "usb";
    this.hint = "";
    this.line = "uDMX listo";
    this.push();
    if (this.lastGood.length && !this.play) await this.usb.sendReliable(this.lastGood);
  }

  async openGranted(): Promise<boolean> {
    const device = await this.usb.findGranted();
    if (!device) {
      this.fail({
        message: "No hay un uDMX autorizado.",
        hint: "Pulsa Conectar y elige el dispositivo 16C0:05DC. En Windows hace falta WinUSB: mira Ayuda.",
      });
      return false;
    }
    await this.openDevice(device);
    return this.usb.isOpen();
  }

  async tryAuto(): Promise<void> {
    if (!this.usb.api) {
      this.mode = "sim";
      this.line = "este navegador no tiene WebUSB · simulando";
      this.hint = "Abre el link en Chrome o Edge. Safari y Firefox no hablan con el uDMX.";
      this.push();
      return;
    }
    const device = await this.usb.findGranted();
    if (!device) {
      this.mode = "sim";
      this.line = "sin uDMX · simulando";
      this.push();
      return;
    }
    await this.openDevice(device);
  }

  private async simulate(): Promise<void> {
    this.gen += 1;
    await this.usb.close();
    this.mode = "sim";
    this.hint = "";
    this.line = "simulando, sin dongle";
    this.push();
    if (this.play) await this.startPlay(this.play);
  }

  private async setRig(nLpc: number, nBeam: number, order: string): Promise<void> {
    this.gen += 1;
    this.rig = buildRig(nLpc, nBeam, order);
    this.player = null;
    this.play = null;
    this.scene = null;
    this.lastPose = [];
    await this.sendBlackout();
    const labels = this.rig.fixtures.map((fixture) => fixture.label).join("  ");
    this.line = labels || "vacío";
    this.push();
  }

  private async startPlay(request: PlayRequest): Promise<void> {
    const look = catalog.looks.get(request.lookId);
    const palette = catalog.paletteById.get(request.paletteId);
    const scale = catalog.speedById.get(request.speedId);
    if (!look || !palette || scale === undefined) {
      this.line = "look, paleta o velocidad desconocida";
      this.push();
      return;
    }
    if (this.rig.span <= 0) {
      this.line = "elige al menos un fixture";
      this.push();
      return;
    }
    const gen = ++this.gen;
    if (this.mode === "off") this.mode = "sim";
    if (this.mode === "usb" && !this.usb.isOpen()) {
      const opened = await this.openGranted();
      if (this.gen !== gen) return;
      if (!opened) return;
    }
    if (this.gen !== gen) return;
    this.play = request;
    this.paletteId = request.paletteId;
    this.speedId = request.speedId;
    this.scene = request.lookId;
    const speedLabel = catalog.speeds.find((speed) => speed.id === request.speedId)?.label ?? request.speedId;
    this.line = `${look.label} · ${palette.label} · ${speedLabel}`;
    this.player = new ShowPlayer(
      this.rig,
      look,
      palette,
      scale,
      beamSequences as Record<string, Json>,
      lpcSequences as Record<string, Json>,
      this.lastPose,
    );
    this.push();
    void this.loop(this.player, gen);
  }

  private async loop(player: ShowPlayer, gen: number): Promise<void> {
    const fps = Math.max(1, player.fps);
    const step = 1 / fps;
    const t0 = perf();
    let n = 0;
    while (this.gen === gen) {
      const now0 = perf();
      let target = t0 + n * step;
      if (now0 - target > step) {
        const jumped = Math.floor((now0 - t0) / step);
        this.usb.noteSkip(Math.max(0, jumped - n));
        n = jumped;
        target = t0 + n * step;
      }
      if (await this.waitUntil(target, gen)) break;
      if (this.mode === "usb" && !this.usb.isOpen()) {
        await this.recover("sin uDMX");
        return;
      }
      const now = perf();
      const frame = player.frame(now, now - t0);
      this.frame = frame;
      if (this.mode === "usb") {
        const ok = await this.usb.sendFrame(frame);
        if (ok) this.lastGood = frame;
        else if (this.usb.isDead()) {
          await this.recover("uDMX saturado");
          return;
        }
      } else {
        this.lastGood = frame;
      }
      this.lastPose = player.lastPose.map((pair) => [pair[0], pair[1]]);
      this.push();
      n += 1;
    }
  }

  private async waitUntil(target: number, gen: number): Promise<boolean> {
    while (this.gen === gen) {
      const remain = target - perf();
      if (remain <= 0) return false;
      await sleep(Math.min(remain, 0.02) * 1000);
    }
    return true;
  }

  private async blackout(): Promise<void> {
    this.gen += 1;
    this.player = null;
    this.play = null;
    this.scene = "blackout";
    this.line = "blackout";
    await this.sendBlackout();
    this.push();
  }

  private async sendBlackout(): Promise<void> {
    const frame = blackoutBuffer(this.rig);
    this.frame = frame;
    this.lastGood = frame;
    if (this.mode === "usb" && this.usb.isOpen() && frame.length) {
      const ok = await this.usb.sendReliable(frame);
      if (!ok) this.line = "blackout · el uDMX no confirmó";
    }
  }

  private async beat(): Promise<void> {
    if (this.mode !== "usb" || !this.usb.isOpen() || !this.lastGood.length) return;
    if (this.player) return;
    const ok = await this.usb.sendFrame(this.lastGood);
    if (!ok && this.usb.isDead()) await this.recover("uDMX desconectado");
    else this.push();
  }

  private async recover(message: string): Promise<void> {
    this.line = message;
    this.push();
    const now = perf();
    if (now < this.recoverAt) return;
    this.recoverAt = now + 1;
    this.gen += 1;
    await this.usb.close();
    if (this.mode !== "usb") return;
    const device = await this.usb.findGranted();
    if (!device) {
      this.hint = explainUsbFailure(new DOMException("no device", "NotFoundError"), "reconectar").hint;
      this.push();
      return;
    }
    try {
      await this.usb.open(device);
    } catch (err) {
      this.fail(explainUsbFailure(err, "reconectar"));
      return;
    }
    this.hint = "";
    this.line = "uDMX reconectado";
    const play = this.play;
    if (play) await this.startPlay(play);
    else if (this.lastGood.length) await this.usb.sendReliable(this.lastGood);
    this.push();
  }

  private fail(hint: UsbHint): void {
    this.line = hint.message;
    this.hint = hint.hint;
    if (this.mode === "usb" && !this.usb.isOpen()) this.mode = "sim";
    this.push();
  }

  private push(): void {
    this.emit({
      line: this.line,
      usb: this.mode === "usb" ? this.usb.line() : this.mode === "sim" ? "simulador" : "usb —",
      scene: this.scene,
      mode: this.mode,
      frame: this.frame.slice(),
      rig: this.rig,
      paletteId: this.paletteId,
      speedId: this.speedId,
      hint: this.hint,
      connected: this.usb.isOpen(),
    });
  }

  private async shutdown(): Promise<void> {
    this.gen += 1;
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.usb.api?.removeEventListener("disconnect", this.onDisconnect);
    this.usb.api?.removeEventListener("connect", this.onConnect);
    await this.sendBlackout();
    await this.usb.close();
  }
}
