import { VoicePanel } from "@/components/VoicePanel";
import { ChatPanel } from "@/components/ChatPanel";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col bg-background text-foreground">
      {/* Header — minimal, centered, no orb (PRD §9 + §12) */}
      <header className="h-14 border-b border-border/60 px-6 flex items-center justify-center bg-background/80 backdrop-blur-md sticky top-0 z-20">
        <h1 className="text-base font-semibold tracking-tight">
          Son of Anton
        </h1>
      </header>

      {/* Two-panel layout: Voice (left, fixed) + Chat (right, scrolls) */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
        <section
          aria-label="Voice panel"
          className="md:fixed md:left-0 md:top-14 md:bottom-0 md:w-80 lg:w-96 md:border-r border-b md:border-b-0 border-border/60 p-6 flex flex-col items-center justify-start bg-background md:overflow-y-auto"
        >
          <VoicePanel />
        </section>

        <section
          aria-label="Chat panel"
          className="flex-1 flex flex-col min-h-0 bg-background md:ml-80 lg:ml-96"
        >
          <ChatPanel />
        </section>
      </div>
    </main>
  );
}
