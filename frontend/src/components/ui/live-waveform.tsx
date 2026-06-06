"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface LiveWaveformProps {
  active?: boolean;
  mode?: "static" | "reactive";
  barColor?: string;
  height?: number;
  fadeEdges?: boolean;
  barCount?: number;
  className?: string;
}

export function LiveWaveform({
  active = true,
  mode = "static",
  barColor = "#a8c8e8",
  height = 48,
  fadeEdges = true,
  barCount = 28,
  className,
}: LiveWaveformProps) {
  const [phase, setPhase] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active || mode !== "static") return;
    const start = performance.now();
    const tick = (now: number) => {
      setPhase(((now - start) % 4000) / 4000);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [active, mode]);

  const bars = Array.from({ length: barCount });

  return (
    <div
      className={cn(
        "live-waveform relative flex items-center justify-center gap-[3px] w-full overflow-hidden",
        !active && "live-waveform--idle",
        className
      )}
      style={
        {
          height: `${height}px`,
          ["--lw-bar-color" as string]: barColor,
        } as React.CSSProperties
      }
      aria-hidden="true"
    >
      {bars.map((_, i) => {
        const t = (i / barCount + phase) % 1;
        const center = 1 - Math.abs((i - barCount / 2) / (barCount / 2));
        const wave =
          0.25 +
          0.75 * Math.abs(Math.sin(t * Math.PI * 2)) * (0.5 + 0.5 * center);
        const h = Math.max(0.08, Math.min(1, wave));
        return (
          <span
            key={i}
            className="live-waveform__bar"
            style={{
              height: `${h * 100}%`,
              opacity: fadeEdges ? 0.35 + 0.65 * center : 1,
            }}
          />
        );
      })}
    </div>
  );
}
