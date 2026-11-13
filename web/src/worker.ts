import { ShowRuntime, type RuntimeCommand, type ShowStatus } from "./runtime";

const scope = self as unknown as {
  postMessage(data: unknown): void;
  onmessage: ((event: MessageEvent<RuntimeCommand>) => void) | null;
};
const usb = (navigator as Navigator).usb;
const runtime = new ShowRuntime((status: ShowStatus) => {
  scope.postMessage({ type: "status", status });
});

scope.postMessage({ type: "ready", usbInWorker: Boolean(usb) });

let chain: Promise<void> = Promise.resolve();
scope.onmessage = (event: MessageEvent<RuntimeCommand>) => {
  chain = chain.then(() => runtime.handle(event.data));
};
