"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { OrbAvatar } from "@/components/OrbAvatar";
import { ShimmeringText } from "@/components/ui/shimmering-text";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

const WELCOME: Message = {
  id: "welcome",
  role: "assistant",
  content:
    "Hi! I'm Son of Anton — Rehan's AI representative. Ask me anything about his background, projects, or schedule an interview.",
  timestamp: new Date(),
};

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

const uuid = (): string => {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `id_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
};

const getOrCreateSessionId = (): string => {
  // Session id is persisted to localStorage so the conversation survives
  // page reloads. Per PRD §12 we do NOT persist message contents — only the
  // session identifier. The backend's Redis handles the actual history.
  if (typeof window === "undefined") return `session_${Date.now()}`;
  const existing = window.localStorage.getItem("anton_session_id");
  if (existing) return existing;
  const fresh = `session_${Date.now().toString(36)}_${Math.random()
    .toString(36)
    .slice(2, 8)}`;
  window.localStorage.setItem("anton_session_id", fresh);
  return fresh;
};

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const sessionIdRef = useRef<string>("");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    sessionIdRef.current = getOrCreateSessionId();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  // ─── SSE stream consumer ──────────────────────────────────────────────────
  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming) return;

    const userMsg: Message = {
      id: uuid(),
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };
    const assistantId = uuid();
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: "assistant", content: "", timestamp: new Date() },
    ]);
    setInput("");
    setIsStreaming(true);

    try {
      const res = await fetch(`${BACKEND_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          session_id: sessionIdRef.current,
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let acc = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // SSE events are separated by a blank line ("\n\n")
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const lines = part.split("\n").filter((l) => l.length > 0);
          for (const raw of lines) {
            // Skip named-event metadata frames (e.g. "event: meta")
            if (raw.startsWith("event:") || raw.startsWith("id:")) continue;
            if (!raw.startsWith("data:")) continue;

            const payload = raw.slice(5).trim();
            if (payload === "[DONE]") {
              return;
            }

            try {
              const parsed = JSON.parse(payload) as {
                choices?: Array<{
                  delta?: { content?: string };
                  finish_reason?: string | null;
                }>;
              };
              const delta = parsed.choices?.[0]?.delta?.content ?? "";
              if (delta) {
                acc += delta;
                const snapshot = acc;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId ? { ...m, content: snapshot } : m
                  )
                );
              }
              if (parsed.choices?.[0]?.finish_reason === "stop") {
                return;
              }
            } catch {
              // Non-JSON data line — ignore (could be a comment heartbeat).
            }
          }
        }
      }
    } catch (e) {
      console.error("[Chat] stream error", e);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content:
                  "I'm having trouble reaching my knowledge base. Please check that the backend server is running and try again.",
              }
            : m
        )
      );
    } finally {
      setIsStreaming(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isStreaming]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void send(input);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0 w-full">
      {/* Message list */}
      <div className="chat-scroll flex-1 overflow-y-auto px-4 md:px-6 py-6 space-y-5">
        {messages.map((msg) => (
          <MessageRow key={msg.id} message={msg} isStreaming={isStreaming} />
        ))}

        {/* Streaming placeholder while the first token hasn't arrived yet */}
        {isStreaming &&
          messages.length > 0 &&
          messages[messages.length - 1]?.content === "" && (
            <div className="flex items-start gap-2.5">
              <OrbAvatar size="sm" />
              <div className="rounded-2xl rounded-tl-sm bg-card/60 border border-border px-4 py-2.5">
                <ShimmeringText text="Son of Anton is thinking…" className="text-xs" />
              </div>
            </div>
          )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input bar */}
      <form
        onSubmit={onSubmit}
        className="border-t border-border bg-background/60 backdrop-blur-sm px-4 md:px-6 py-4 flex items-end gap-2"
      >
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask Son of Anton anything…"
          disabled={isStreaming}
          rows={1}
          className={cn(
            "flex-1 resize-none bg-card/60 border border-border rounded-xl px-4 py-2.5",
            "text-sm text-foreground placeholder:text-muted-foreground",
            "focus:outline-none focus:ring-1 focus:ring-ring focus:border-ring",
            "disabled:opacity-50 max-h-32"
          )}
        />
        <Button
          type="submit"
          size="icon"
          variant="ghost"
          disabled={isStreaming || !input.trim()}
          aria-label="Send message"
          className="text-muted-foreground hover:text-foreground shrink-0 h-10 w-10"
        >
          <Send className="size-4" />
        </Button>
      </form>
    </div>
  );
}

function MessageRow({
  message,
  isStreaming,
}: {
  message: Message;
  isStreaming: boolean;
}) {
  const isUser = message.role === "user";
  const isEmptyAssistant =
    !isUser && message.content === "" && isStreaming;

  return (
    <div
      className={cn(
        "flex items-start gap-2.5 w-full",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      {isUser ? (
        <div className="h-8 w-8 rounded-full bg-card/80 border border-border flex items-center justify-center text-xs text-muted-foreground shrink-0">
          You
        </div>
      ) : (
        <OrbAvatar size="sm" />
      )}

      <div
        className={cn(
          "max-w-[78%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-foreground/5 border border-border text-foreground rounded-tr-sm"
            : "bg-card/60 border border-border text-foreground/90 rounded-tl-sm"
        )}
      >
        {isEmptyAssistant ? null : (
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        )}
      </div>
    </div>
  );
}
