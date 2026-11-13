interface USBControlTransferParameters {
  requestType: "standard" | "class" | "vendor";
  recipient: "device" | "interface" | "endpoint" | "other";
  request: number;
  value: number;
  index: number;
}

interface USBTransferResult {
  status: "ok" | "stall" | "babble";
}

interface USBInterface {
  interfaceNumber: number;
}

interface USBConfiguration {
  configurationValue: number;
  interfaces: USBInterface[];
}

interface USBDevice {
  vendorId: number;
  productId: number;
  productName?: string | null;
  manufacturerName?: string | null;
  opened: boolean;
  configuration: USBConfiguration | null;
  configurations: USBConfiguration[];
  open(): Promise<void>;
  close(): Promise<void>;
  selectConfiguration(configurationValue: number): Promise<void>;
  claimInterface(interfaceNumber: number): Promise<void>;
  releaseInterface(interfaceNumber: number): Promise<void>;
  controlTransferOut(setup: USBControlTransferParameters, data?: BufferSource): Promise<USBTransferResult>;
}

interface USBConnectionEvent extends Event {
  device: USBDevice;
}

interface USB {
  requestDevice(options: { filters: { vendorId?: number; productId?: number }[] }): Promise<USBDevice>;
  getDevices(): Promise<USBDevice[]>;
  addEventListener(type: "connect" | "disconnect", listener: (event: USBConnectionEvent) => void): void;
  removeEventListener(type: "connect" | "disconnect", listener: (event: USBConnectionEvent) => void): void;
}

interface Navigator {
  usb: USB;
}
