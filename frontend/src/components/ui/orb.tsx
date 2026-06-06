"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export type AgentState =
  | null
  | "thinking"
  | "talking"
  | "listening"
  | null;

export interface OrbProps {
  colors?: [string, string];
  agentState?: AgentState;
  getInputVolume?: () => number;
  getOutputVolume?: () => number;
  className?: string;
  seed?: number;
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

export function Orb({
  colors = ["#a8c8e8", "#0c0a09"],
  agentState = null,
  getInputVolume,
  getOutputVolume,
  className,
  seed = 1,
}: OrbProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputVolRef = useRef(0);
  const outputVolRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const tick = () => {
      const inVol = Math.min(1, Math.max(0, getInputVolume?.() ?? 0));
      const outVol = Math.min(1, Math.max(0, getOutputVolume?.() ?? 0));
      inputVolRef.current = lerp(inputVolRef.current, inVol, 0.25);
      outputVolRef.current = lerp(outputVolRef.current, outVol, 0.25);

      const el = rootRef.current;
      if (el) {
        el.style.setProperty("--vol-in", inputVolRef.current.toFixed(3));
        el.style.setProperty("--vol-out", outputVolRef.current.toFixed(3));
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [getInputVolume, getOutputVolume]);

  const stateClass =
    agentState === "talking"
      ? "orb--talking"
      : agentState === "listening"
        ? "orb--listening"
        : agentState === "thinking"
          ? "orb--thinking"
          : "orb--idle";

  const seedHue = (seed * 137) % 360;

  return (
    <div
      ref={rootRef}
      className={cn("orb relative inline-block select-none", stateClass, className)}
      style={
        {
          "--orb-color-1": colors[0],
          "--orb-color-2": colors[1],
          "--seed-hue": `${seedHue}deg`,
        } as React.CSSProperties
      }
      aria-hidden="true"
    >
      <div className="orb__halo" />
      <div className="orb__sphere" />
      <div className="orb__highlight" />
    </div>
  );
}
