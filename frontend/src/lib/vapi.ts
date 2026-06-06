/**
 * Vapi Web SDK singleton.
 *
 * Vapi must be instantiated once and reused. Do NOT create it inside a
 * component — re-instantiation on every render destroys the underlying
 * Daily call object and breaks active calls.
 *
 * PRD §7: "Vapi must be instantiated once and reused."
 */

import Vapi from "@vapi-ai/web";

let vapiInstance: Vapi | null = null;

export function getVapi(): Vapi {
  if (vapiInstance === null) {
    const apiKey = process.env.NEXT_PUBLIC_VAPI_PUBLIC_KEY;
    if (!apiKey) {
      throw new Error(
        "NEXT_PUBLIC_VAPI_PUBLIC_KEY is not set. Add it to frontend/.env.local."
      );
    }
    vapiInstance = new Vapi(apiKey, undefined, {
      alwaysIncludeMicInPermissionPrompt: true,
    });
  }
  return vapiInstance;
}

/**
 * Proactively request microphone permission so the browser shows its
 * permission prompt before we hand control to Vapi. Vapi's underlying Daily
 * call object will otherwise ask later, and the prompt can be invisible or
 * appear with no microphone listed if the OS has no audio input device.
 *
 * Resolves with `{ granted: true }` if a mic track was produced, otherwise
 * `{ granted: false, reason }` so the caller can show a useful error.
 */
export async function requestMicrophonePermission(): Promise<
  { granted: true; stream: MediaStream } | { granted: false; reason: string }
> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return { granted: false, reason: "This browser does not support microphone access (mediaDevices.getUserMedia unavailable)." };
  }
  // Check what devices the browser can see so the error message is useful
  // even when no mic is plugged in.
  let deviceInfo = "";
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter((d) => d.kind === "audioinput");
    if (inputs.length === 0) {
      deviceInfo = " The browser reports 0 audio input devices (check OS sound settings, or you may be in a VM/container without audio passthrough).";
    } else {
      const labels = inputs.map((d) => d.label || "(no label)").join(", ");
      deviceInfo = ` The browser sees ${inputs.length} input(s): ${labels}.`;
    }
  } catch {
    // ignore
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    return { granted: true, stream };
  } catch (e) {
    const err = e as DOMException;
    if (err.name === "NotAllowedError" || err.name === "SecurityError") {
      return { granted: false, reason: "Microphone permission was denied. Click the mic icon in the address bar to allow it, then reload." + deviceInfo };
    }
    if (err.name === "NotFoundError" || err.name === "OverconstrainedError") {
      return { granted: false, reason: "No microphone found. Connect a microphone and reload the page." + deviceInfo };
    }
    if (err.name === "NotReadableError") {
      return { granted: false, reason: "Microphone is in use by another application. Close other tabs/apps that may be using it and try again." + deviceInfo };
    }
    return { granted: false, reason: `Microphone error (${err.name || "unknown"}).` + deviceInfo };
  }
}
