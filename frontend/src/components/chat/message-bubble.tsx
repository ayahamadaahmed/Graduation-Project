import { Bot } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/chat-data";
import { BookingWidget } from "./booking-widget";
import { EscalationCard } from "./escalation-card";

export function MessageBubble({ message, onConfirmSlot }: { message: ChatMessage; onConfirmSlot?: (slot: string) => void }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex w-full gap-3 animate-fade-in", isUser ? "flex-row-reverse" : "flex-row")}>
      <Avatar className="h-9 w-9 shrink-0">
        {isUser ? (
          <AvatarFallback className="bg-gradient-to-br from-primary to-cyan-600 text-sm font-semibold text-primary-foreground">
            مأ
          </AvatarFallback>
        ) : (
          <AvatarFallback className="bg-primary-soft text-primary">
            <Bot className="h-5 w-5" />
          </AvatarFallback>
        )}
      </Avatar>
      <div className={cn("flex max-w-[85%] flex-col gap-1", isUser ? "items-end" : "items-start")}>
        {message.text && (
          <div
            className={cn(
              "rounded-xl px-4 py-3 text-sm leading-relaxed shadow-card",
              isUser
                ? "rounded-tr-sm bg-primary text-primary-foreground"
                : "rounded-tl-sm bg-card text-foreground border border-border",
            )}
          >
            {message.text}
          </div>
        )}
        {message.widget?.type === "booking" && (
          <BookingWidget widget={message.widget} onConfirm={onConfirmSlot} />
        )}
        {message.escalation && <EscalationCard escalation={message.escalation} />}
        <span className="px-1 text-[11px] text-muted-foreground">{message.time}</span>
      </div>
    </div>
  );
}

export function TypingBubble() {
  return (
    <div className="flex w-full gap-3 animate-fade-in">
      <Avatar className="h-9 w-9 shrink-0">
        <AvatarFallback className="bg-primary-soft text-primary">
          <Bot className="h-5 w-5" />
        </AvatarFallback>
      </Avatar>
      <div className="flex items-center gap-1.5 rounded-xl rounded-tl-sm border border-border bg-card px-4 py-3 shadow-card">
        <span className="h-2 w-2 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
        <span className="h-2 w-2 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
        <span className="h-2 w-2 animate-bounce rounded-full bg-primary" />
      </div>
    </div>
  );
}
