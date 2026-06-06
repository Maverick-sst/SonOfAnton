"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Mic, MicOff, PhoneOff } from "lucide-react";
import { Orb, type AgentState } from "@/components/ui/orb";
import { LiveWaveform } from "@/components/ui/live-waveform";
import { ShimmeringText } from "@/components/ui/shimmering-text";
import { PhoneCard } from "@/components/PhoneCard";
import { Button } from "@/components/ui/button";
import { getVapi, requestMicrophonePermission } from "@/lib/vapi";
import { cn } from "@/lib/utils";

type CallState = "idle" | "connecting" | "active" | "ended";

const STATUS_TEXT: Record<CallState, string> = {
  idle: "Click to speak with Son of Anton",
  connecting: "Connecting…",
  active: "Live — Son of Anton is listening",
  ended: "Call ended",
};

const RESET_DELAY_MS = 3000;

export function VoicePanel() {
  const [callState, setCallState] = useState<CallState>("idle");
  const [orbState, setOrbState] = useState<AgentState>(null);
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);

  const inputVolRef = useRef(0);
  const outputVolRef = useRef(0);
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const getInputVolume = useCallback(() => inputVolRef.current, []);
  const getOutputVolume = useCallback(() => outputVolRef.current, []);

  // ─── Vapi event wiring ────────────────────────────────────────────────────
  // Probe whether the public Vapi key is present at mount, so we can show
  // a friendly error message instead of crashing on first interaction.
  // getVapi() itself is called lazily inside the event listeners effect.
  const vapiReady = useMemo(
    () => Boolean(process.env.NEXT_PUBLIC_VAPI_PUBLIC_KEY),
    []
  );

  const configError = vapiReady
    ? null
    : "Voice is not configured. Set NEXT_PUBLIC_VAPI_PUBLIC_KEY in frontend/.env.local.";

  useEffect(() => {
    if (vapiReady !== true) return;

    const vapi = getVapi();

    const onCallStart = () => {
      setError(null);
      setCallState("active");
      setOrbState("listening");
    };

    const onCallEnd = () => {
      setCallState("ended");
      setOrbState(null);
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
      resetTimerRef.current = setTimeout(() => {
        setCallState("idle");
      }, RESET_DELAY_MS);
    };

    const onSpeechStart = () => {
      // Son of Anton is talking
      setOrbState("talking");
    };

    const onSpeechEnd = () => {
      // Son of Anton finished, user can speak
      setOrbState("listening");
    };

    const onVolumeLevel = (vol: number) => {
      // The SDK reports the assistant's audio output level (0..1).
      // We mirror it to both for now; mic-level tracking would need a
      // separate Web Audio analyser and is out of scope for v1.
      const v = Math.min(1, Math.max(0, vol));
      outputVolRef.current = v;
      inputVolRef.current = v * 0.6;
    };

    const onError = (e: unknown) => {
      console.error("[Vapi] error", e);
      setError("Call failed. Please try again.");
      setCallState("idle");
      setOrbState(null);
    };

    vapi.on("call-start", onCallStart);
    vapi.on("call-end", onCallEnd);
    vapi.on("speech-start", onSpeechStart);
    vapi.on("speech-end", onSpeechEnd);
    vapi.on("volume-level", onVolumeLevel);
    vapi.on("error", onError);

    return () => {
      vapi.removeAllListeners();
      if (resetTimerRef.current) {
        clearTimeout(resetTimerRef.current);
        resetTimerRef.current = null;
      }
    };
  }, [vapiReady]);

  // ─── Call control handlers ────────────────────────────────────────────────
  const startCall = useCallback(async () => {
    setError(null);
    setCallState("connecting");
    setOrbState("thinking");
    try {
      const assistantId = process.env.NEXT_PUBLIC_VAPI_ASSISTANT_ID;
      if (!assistantId) {
        throw new Error(
          "NEXT_PUBLIC_VAPI_ASSISTANT_ID is not set. Add it to frontend/.env.local."
        );
      }
      const perm = await requestMicrophonePermission();
      if (!perm.granted) {
        setError(perm.reason);
        setCallState("idle");
        setOrbState(null);
        return;
      }
      // Stop our probe track; Vapi/Daily will open its own.
      perm.stream.getTracks().forEach((t) => t.stop());
      const vapi = getVapi();
      await vapi.start(assistantId);
    } catch (e) {
      console.error("[Vapi] start failed", e);
      setError(e instanceof Error ? e.message : "Could not start the call.");
      setCallState("idle");
      setOrbState(null);
    }
  }, []);

  const endCall = useCallback(() => {
    try {
      const vapi = getVapi();
      vapi.stop();
    } catch (e) {
      console.error("[Vapi] stop failed", e);
      setCallState("idle");
      setOrbState(null);
    }
  }, []);

  const toggleMute = useCallback(() => {
    try {
      const vapi = getVapi();
      const next = !muted;
      vapi.setMuted(next);
      setMuted(next);
    } catch (e) {
      console.error("[Vapi] setMuted failed", e);
    }
  }, [muted]);

  const isActive = callState === "active";
  const isConnecting = callState === "connecting";
  const isEnded = callState === "ended";

  return (
    <div className="flex flex-col items-center gap-6 w-full">
      {/* Orb + status */}
      <div className="flex flex-col items-center gap-3">
        <button
          type="button"
          onClick={callState === "idle" ? startCall : isActive ? endCall : undefined}
          disabled={isConnecting || isEnded}
          aria-label={
            isActive ? "End call" : isConnecting ? "Connecting" : "Start call"
          }
          className={cn(
            "relative h-40 w-40 rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background transition-transform",
            callState === "idle" && "hover:scale-[1.03] active:scale-[0.98] cursor-pointer",
            isActive && "cursor-pointer",
            (isConnecting || isEnded) && "cursor-default"
          )}
        >
          <Orb
            colors={["#a8c8e8", "#1c1917"]}
            agentState={orbState}
            getInputVolume={getInputVolume}
            getOutputVolume={getOutputVolume}
            className="h-full w-full"
          />
        </button>

        <ShimmeringText
          text={STATUS_TEXT[callState]}
          className="text-sm"
          duration={isConnecting || isEnded ? 1.6 : 3.2}
        />

        {(error || configError) && (
          <p className="text-xs text-destructive text-center max-w-[260px]">
            {error || configError}
          </p>
        )}
      </div>

      {/* Waveform during active call */}
      {isActive && (
        <div className="w-full">
          <LiveWaveform
            active
            mode="static"
            barColor="#a8c8e8"
            height={48}
            fadeEdges
            className="w-full"
          />
        </div>
      )}

      {/* In-call controls */}
      <div className="flex items-center gap-2 min-h-[40px]">
        {isActive && (
          <>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={toggleMute}
              aria-label={muted ? "Unmute" : "Mute"}
              title={muted ? "Unmute" : "Mute"}
              className="text-muted-foreground hover:text-foreground"
            >
              {muted ? (
                <MicOff className="size-4" />
              ) : (
                <Mic className="size-4" />
              )}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={endCall}
              className="text-destructive hover:text-destructive hover:bg-destructive/10"
            >
              <PhoneOff className="size-4 mr-1.5" />
              End call
            </Button>
          </>
        )}
      </div>

      {/* Phone number card */}
      <div className="w-full">
        <PhoneCard />
      </div>
    </div>
  );
}
