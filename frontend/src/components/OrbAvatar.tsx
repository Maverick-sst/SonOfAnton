"use client";

import { cn } from "@/lib/utils";
import { Orb, type AgentState } from "@/components/ui/orb";

export interface OrbAvatarProps {
  size?: "sm" | "md";
  state?: AgentState;
  className?: string;
}

/**
 * Small reusable Orb for chat message avatars. Static by default
 * (no volume refs); pass a `state` to reflect call activity.
 */
export function OrbAvatar({ size = "sm", state = null, className }: OrbAvatarProps) {
  const dim = size === "sm" ? "h-8 w-8" : "h-12 w-12";

  return (
    <div
      className={cn(
        dim,
        "rounded-full overflow-hidden shrink-0 bg-muted ring-1 ring-border",
        className
      )}
    >
      <Orb colors={["#a8c8e8", "#1c1917"]} seed={42} agentState={state} />
    </div>
  );
}
