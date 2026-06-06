"use client";

import { Phone } from "lucide-react";
import { CopyButton } from "@/components/CopyButton";

export function PhoneCard() {
  const phone = process.env.NEXT_PUBLIC_ANTON_PHONE_NUMBER;

  if (!phone) {
    return (
      <div className="rounded-xl border border-border bg-card/50 p-4 text-xs text-muted-foreground">
        Phone number not configured.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card/50 p-4 flex items-center gap-3 backdrop-blur-sm">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-muted-foreground shrink-0">
        <Phone className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-0.5">
          Prefer to call?
        </p>
        <p className="text-base font-mono font-medium tracking-wide truncate">
          {phone}
        </p>
      </div>
      <CopyButton value={phone} label="Copy phone number" />
    </div>
  );
}
