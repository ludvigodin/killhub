/** Plane 1 browser types for the read-only subset of the noVNC client API. */
declare module "@novnc/novnc" {
  export default class RFB extends EventTarget {
    constructor(
      target: HTMLElement,
      url: string,
      options: { shared: boolean; wsProtocols: string[] },
    );
    viewOnly: boolean;
    scaleViewport: boolean;
    disconnect(): void;
  }
}
