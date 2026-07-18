import { MessageSquarePlus, Search, MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/lib/chat-data";

const groupLabels: Record<Conversation["group"], string> = {
  today: "محادثات اليوم",
  yesterday: "الأمس",
  older: "أقدم",
};

export function ChatHistorySidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
}: {
  conversations: Conversation[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const groups: Conversation["group"][] = ["today", "yesterday", "older"];
  return (
    <aside className="hidden w-72 shrink-0 flex-col border-l border-border bg-card lg:flex">
      <div className="border-b border-border p-4">
        <Button
          onClick={onNew}
          className="h-10 w-full justify-start gap-2 rounded-xl bg-primary text-primary-foreground shadow-soft hover:bg-primary/90"
        >
          <MessageSquarePlus className="h-5 w-5" />
          محادثة جديدة
        </Button>
        <div className="relative mt-3">
          <Search className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="ابحث في المحادثات..." className="h-10 rounded-xl bg-secondary pr-10" />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {groups.map((g) => {
          const items = conversations.filter((c) => c.group === g);
          if (!items.length) return null;
          return (
            <div key={g} className="mb-4">
              <div className="mb-2 px-2 text-xs font-semibold text-muted-foreground">{groupLabels[g]}</div>
              <div className="space-y-1">
                {items.map((c) => {
                  const active = c.id === activeId;
                  return (
                    <button
                      key={c.id}
                      onClick={() => onSelect(c.id)}
                      className={cn(
                        "flex w-full items-start gap-3 rounded-xl p-3 text-right transition-colors",
                        active
                          ? "bg-primary-soft text-foreground"
                          : "hover:bg-secondary",
                      )}
                    >
                      <MessageCircle className={cn("mt-0.5 h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold">{c.title}</div>
                        <div className="truncate text-xs text-muted-foreground">{c.preview}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
