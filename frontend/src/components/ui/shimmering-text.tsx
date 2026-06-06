"use client";

import { cn } from "@/lib/utils";

export interface ShimmeringTextProps {
  text: string;
  className?: string;
  duration?: number;
}

export function ShimmeringText({
  text,
  className,
  duration = 2.4,
}: ShimmeringTextProps) {
  return (
    <span
      className={cn("shimmering-text inline-block", className)}
      style={{ ["--shimmer-duration" as string]: `${duration}s` }}
    >
      {text}
    </span>
  );
}
