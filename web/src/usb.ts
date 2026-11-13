export const VID = 0x16c0;
export const PID = 0x05dc;
export const USB_DEAD_STREAK = 20;

export interface UsbHealth {
  ok: number;
  fail: number;
  streak: number;
  skipped: number;
  lastError: string;
}

export function emptyHealth(): UsbHealth {
  return { ok: 0, fail: 0, streak: 0, skipped: 0, lastError: "" };
}

export function usbLine(health: UsbHealth, extra = ""): string {
  const tail = health.streak > 0 && health.lastError ? `  ·  ${health.lastError}` : "";
  const chunk = extra ? `  ·  ${extra}` : "";
  return `usb  ok ${health.ok}  fail ${health.fail}  racha ${health.streak}  saltos ${health.skipped}${tail}${chunk}`;
}

export interface UsbHint {
  message: string;
  hint: string;
}

const WINDOWS_HINT =
  "En Windows, Chrome solo abre el uDMX si el driver es WinUSB. Con Zadig, elige el dispositivo 16C0:05DC e instala WinUSB. Eso puede dejar de funcionar pyusb y QLC+ en esa máquina hasta que vuelvas a poner libusb-win32 o libusbK. Los pasos están en Ayuda.";

export function explainUsbFailure(err: unknown, phase: string): UsbHint {
  const name = err instanceof DOMException ? err.name : "";
  const raw = err instanceof Error ? err.message : String(err);
  const busy = /access|denied|busy|in use|claimed|protected/i.test(raw);
  if (name === "NotFoundError") {
    return {
      message: "No se eligió un uDMX.",
      hint: `En el diálogo tiene que aparecer un dispositivo 16C0:05DC. Si no aparece, cierra QLC+ y el panel Python, desenchufa y vuelve a enchufar. ${WINDOWS_HINT}`,
    };
  }
  if (name === "SecurityError" || name === "NotAllowedError") {
    return {
      message: "El navegador bloqueó el USB.",
      hint: "WebUSB funciona en Chrome o Edge, en HTTPS o en localhost. Safari y Firefox no sirven. El botón Conectar tiene que ser un click tuyo, no un arranque automático.",
    };
  }
  if (name === "NetworkError" || name === "InvalidStateError" || busy) {
    return {
      message: `No se pudo ${phase} el uDMX.`,
      hint: `Ciérralo en QLC+ y en el panel de Python: un solo programa puede tener el dongle. Desenchufa y vuelve a enchufar. ${WINDOWS_HINT}`,
    };
  }
  return {
    message: `No se pudo ${phase} el uDMX${name ? ` (${name})` : ""}.`,
    hint: raw ? `${raw} ${WINDOWS_HINT}` : WINDOWS_HINT,
  };
}

export function isUdmx(device: USBDevice): boolean {
  return device.vendorId === VID && device.productId === PID;
}

export function looksLikeUdmx(device: USBDevice): boolean {
  const label = `${device.productName ?? ""} ${device.manufacturerName ?? ""}`.trim();
  if (!device.productName) return true;
  return /dmx|anyma/i.test(label);
}

function usbApi(): USB | undefined {
  return (navigator as Navigator).usb;
}

export class UdmxLink {
  device: USBDevice | null = null;
  health: UsbHealth = emptyHealth();
  /** Byte size of each SET_RANGE after the whole frame was rejected. Null sends one transfer. */
  chunk: number | null = null;
  private wholeFails = 0;

  get api(): USB | undefined {
    return usbApi();
  }

  isOpen(): boolean {
    return this.device?.opened === true;
  }

  isDead(): boolean {
    return this.health.streak >= USB_DEAD_STREAK;
  }

  markDead(reason: string): void {
    this.health.streak = USB_DEAD_STREAK;
    this.health.fail += 1;
    this.health.lastError = reason;
  }

  noteSkip(n: number): void {
    if (n > 0) this.health.skipped += n;
  }

  line(): string {
    const extra = this.chunk ? `trozos de ${this.chunk}` : "";
    return usbLine(this.health, extra);
  }

  async pick(): Promise<USBDevice> {
    const usb = this.api;
    if (!usb) {
      throw new DOMException("Este navegador no tiene WebUSB.", "NotSupportedError");
    }
    return usb.requestDevice({ filters: [{ vendorId: VID, productId: PID }] });
  }

  async findGranted(): Promise<USBDevice | null> {
    const usb = this.api;
    if (!usb) return null;
    const devices = await usb.getDevices();
    const matches = devices.filter(isUdmx);
    return matches.find(looksLikeUdmx) ?? matches[0] ?? null;
  }

  async open(device: USBDevice): Promise<void> {
    await this.close();
    if (!isUdmx(device)) {
      throw new Error("Ese USB no es un uDMX (16C0:05DC).");
    }
    try {
      await device.open();
    } catch (err) {
      this.markDead("open");
      throw err;
    }
    if (!looksLikeUdmx(device)) {
      const name = device.productName || "desconocido";
      try {
        await device.close();
      } catch {
        /* already closing */
      }
      throw new Error(`«${name}» usa el mismo VID/PID pero no parece un uDMX.`);
    }
    try {
      if (device.configuration == null) {
        const value = device.configurations[0]?.configurationValue ?? 1;
        await device.selectConfiguration(value);
      }
      const iface = device.configuration?.interfaces[0]?.interfaceNumber ?? 0;
      await device.claimInterface(iface);
    } catch (err) {
      try {
        await device.close();
      } catch {
        /* ignore */
      }
      this.markDead("claimInterface");
      throw err;
    }
    this.device = device;
    this.health = emptyHealth();
    this.chunk = null;
    this.wholeFails = 0;
  }

  async close(): Promise<void> {
    const device = this.device;
    this.device = null;
    if (!device) return;
    try {
      if (device.opened && device.configuration) {
        const iface = device.configuration.interfaces[0]?.interfaceNumber ?? 0;
        await device.releaseInterface(iface);
      }
    } catch {
      /* unplugged */
    }
    try {
      await device.close();
    } catch {
      /* unplugged */
    }
  }

  async sendFrame(values: number[]): Promise<boolean> {
    if (!values.length) return true;
    if (!this.isOpen()) {
      this.noteFail("no connection");
      return false;
    }
    try {
      if (this.chunk != null) {
        const ok = await this.sendChunks(values, this.chunk);
        if (ok) this.noteOk();
        else this.noteFail(`controlTransfer en trozos de ${this.chunk}`);
        return ok;
      }
      const whole = await this.transfer(0, values);
      if (whole) {
        this.wholeFails = 0;
        this.noteOk();
        return true;
      }
      this.wholeFails += 1;
      if (this.wholeFails >= 3 && this.isOpen()) {
        for (const size of [32, 8]) {
          if (await this.sendChunks(values, size)) {
            this.chunk = size;
            this.noteOk();
            this.health.lastError = `el frame entero falló; sigo de a ${size} bytes`;
            return true;
          }
        }
      }
      this.noteFail("controlTransfer");
      return false;
    } catch (err) {
      this.noteFail(err instanceof Error ? err.message : String(err));
      return false;
    }
  }

  async sendReliable(values: number[], retries = 3): Promise<boolean> {
    const attempts = Math.max(1, retries);
    for (let i = 0; i < attempts; i++) {
      if (await this.sendFrame(values)) return true;
      if (i + 1 < attempts) await new Promise((resolve) => setTimeout(resolve, 30));
    }
    return false;
  }

  private async sendChunks(values: number[], size: number): Promise<boolean> {
    for (let offset = 0; offset < values.length; offset += size) {
      const ok = await this.transfer(offset, values.slice(offset, offset + size));
      if (!ok) return false;
    }
    return true;
  }

  private async transfer(start: number, values: number[]): Promise<boolean> {
    const device = this.device;
    if (!device?.opened) return false;
    const data = Uint8Array.from(values);
    const result = await device.controlTransferOut(
      {
        requestType: "vendor",
        recipient: "device",
        request: 2,
        value: data.byteLength,
        index: start,
      },
      data,
    );
    return result.status === "ok";
  }

  private noteOk(): void {
    this.health.ok += 1;
    this.health.streak = 0;
  }

  private noteFail(reason: string): void {
    this.health.fail += 1;
    this.health.streak += 1;
    this.health.lastError = reason;
  }
}
