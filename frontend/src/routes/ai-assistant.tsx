import { useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  Bot,
  CalendarPlus,
  CalendarX,
  CalendarClock,
  Siren,
  Calendar,
  User,
  FlaskConical,
  FileText,
  MapPin,
  Sparkles,
} from "lucide-react";
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { AppSidebar } from "@/components/app-sidebar";
import { AppHeader } from "@/components/app-header";
import { ChatHistorySidebar } from "@/components/chat/chat-history-sidebar";
import { MessageBubble, TypingBubble } from "@/components/chat/message-bubble";
import { MessageComposer } from "@/components/chat/message-composer";
import {
  conversations as seedConversations,
  mockBookingWidget,
  mockEscalation,
  type ChatMessage,
  type Conversation,
} from "@/lib/chat-data";

export const Route = createFileRoute("/ai-assistant")({
  component: AIAssistantPage,
});

const suggestions = [
  { icon: Calendar, label: "حجز موعد" },
  { icon: User, label: "البحث عن طبيب" },
  { icon: FlaskConical, label: "نتائج التحاليل" },
  { icon: FileText, label: "التقارير الطبية" },
  { icon: MapPin, label: "موقع العيادة" },
];

const quickActions = [
  { icon: CalendarPlus, label: "حجز موعد", cls: "bg-primary text-primary-foreground hover:bg-primary/90" },
  { icon: CalendarX, label: "إلغاء موعد", cls: "bg-secondary text-foreground hover:bg-primary-soft" },
  { icon: CalendarClock, label: "إعادة جدولة", cls: "bg-secondary text-foreground hover:bg-primary-soft" },
  { icon: Siren, label: "طوارئ", cls: "bg-destructive/10 text-destructive hover:bg-destructive/15" },
];

const nowTime = () =>
  new Date().toLocaleTimeString("ar-SA", { hour: "2-digit", minute: "2-digit" });

function AIAssistantPage() {
  const [conversations, setConversations] = useState<Conversation[]>(seedConversations);
  const [activeId, setActiveId] = useState(seedConversations[0].id);
  const [typing, setTyping] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const active = useMemo(
    () => conversations.find((c) => c.id === activeId) ?? conversations[0],
    [conversations, activeId],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [active.messages, typing]);

  const updateActive = (fn: (c: Conversation) => Conversation) =>
    setConversations((prev) => prev.map((c) => (c.id === activeId ? fn(c) : c)));

  const pushMessage = (m: ChatMessage) =>
    updateActive((c) => ({ ...c, messages: [...c.messages, m], preview: m.text ?? c.preview }));

  const handleSend = (text: string) => {
    pushMessage({ id: crypto.randomUUID(), role: "user", text, time: nowTime() });
    setTyping(true);
    setTimeout(() => {
      const lower = text.toLowerCase();
      const reply: ChatMessage = {
        id: crypto.randomUUID(),
        role: "ai",
        time: nowTime(),
      };
      if (text.includes("حجز") || text.includes("موعد") || lower.includes("book")) {
        reply.text = "بالتأكيد! وجدت لك أقرب موعد متاح مع طبيب مناسب:";
        reply.widget = mockBookingWidget;
      } else if (text.includes("طوارئ") || text.includes("مستعجل") || text.includes("موظف")) {
        reply.text = "أحتاج تحويلك لموظف الاستقبال لمساعدتك بشكل أفضل.";
        reply.escalation = mockEscalation;
      } else {
        reply.text =
          "شكراً لتواصلك. يمكنني مساعدتك في حجز المواعيد، معرفة نتائج التحاليل، أو الإجابة على استفساراتك الطبية. ما الذي تحتاجه؟";
      }
      pushMessage(reply);
      setTyping(false);
    }, 1100);
  };

  const handleNew = () => {
    const id = crypto.randomUUID();
    const next: Conversation = {
      id,
      title: "محادثة جديدة",
      group: "today",
      preview: "ابدأ محادثة مع المساعد الذكي",
      messages: [
        {
          id: crypto.randomUUID(),
          role: "ai",
          text: "مرحباً 👋 أنا مساعدك الطبي الذكي. كيف يمكنني مساعدتك اليوم؟",
          time: nowTime(),
        },
      ],
    };
    setConversations((prev) => [next, ...prev]);
    setActiveId(id);
  };

  const empty = active.messages.length === 0;

  return (
    <SidebarProvider defaultOpen>
      <AppSidebar />
      <SidebarInset className="bg-background">
        <AppHeader />
        <div className="flex flex-1 overflow-hidden">
          <ChatHistorySidebar
            conversations={conversations}
            activeId={activeId}
            onSelect={setActiveId}
            onNew={handleNew}
          />
          <div className="flex flex-1 flex-col overflow-hidden">
            {/* Chat header */}
            <div className="flex items-center justify-between gap-3 border-b border-border bg-card px-4 py-3 md:px-6">
              <div className="flex items-center gap-3">
                <div className="relative">
                  <Avatar className="h-10 w-11 border-2 border-primary/20">
                    <AvatarFallback className="bg-primary-soft text-primary">
                      <Bot className="h-6 w-6" />
                    </AvatarFallback>
                  </Avatar>
                  <span className="absolute bottom-0 left-0 h-3 w-3 rounded-full bg-success ring-2 ring-card" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h1 className="truncate text-base font-bold">المساعد الطبي الذكي</h1>
                    <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[10px] font-semibold text-primary">AI</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="h-1.5 w-1.5 rounded-full bg-success" />
                    متصل الآن • يخدم محمد الأحمد
                  </div>
                </div>
              </div>
              <Button variant="outline" size="sm" className="hidden rounded-xl md:inline-flex">
                <Sparkles className="ml-2 h-4 w-4 text-primary" />
                محادثة جديدة
              </Button>
            </div>

            {/* Conversation */}
            <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6 md:px-8">
              <div className="mx-auto flex max-w-3xl flex-col gap-5">
                {empty ? (
                  <div className="flex flex-col items-center py-12 text-center">
                    <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-primary-soft text-primary shadow-soft">
                      <Bot className="h-8 w-8" />
                    </div>
                    <h2 className="mt-4 text-xl font-bold">كيف يمكنني مساعدتك؟</h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      اسأل عن أعراضك، احجز موعداً، أو استفسر عن خدماتنا الطبية
                    </p>
                  </div>
                ) : (
                  active.messages.map((m) => (
                    <MessageBubble
                      key={m.id}
                      message={m}
                      onConfirmSlot={(s) =>
                        pushMessage({
                          id: crypto.randomUUID(),
                          role: "ai",
                          text: `تم تأكيد موعدك في ${s}. سنرسل لك تذكيراً قبل الموعد بيوم.`,
                          time: nowTime(),
                        })
                      }
                    />
                  ))
                )}
                {typing && <TypingBubble />}
              </div>
            </div>

            {/* Composer area */}
            <div className="border-t border-border bg-card/60 px-4 py-4 md:px-8">
              <div className="mx-auto max-w-3xl space-y-3">
                {/* Suggested questions */}
                <div className="flex flex-wrap gap-2">
                  {suggestions.map((s) => (
                    <button
                      key={s.label}
                      onClick={() => handleSend(s.label)}
                      className="flex items-center gap-2 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-semibold text-foreground shadow-card transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-primary-soft hover:text-primary"
                    >
                      <s.icon className="h-3.5 w-3.5 text-primary" />
                      {s.label}
                    </button>
                  ))}
                </div>

                <MessageComposer onSend={handleSend} disabled={typing} />

                {/* Quick actions */}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {quickActions.map((q) => (
                    <button
                      key={q.label}
                      onClick={() => handleSend(q.label)}
                      className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-semibold shadow-card transition-all hover:-translate-y-0.5 ${q.cls}`}
                    >
                      <q.icon className="h-4 w-4" />
                      {q.label}
                    </button>
                  ))}
                </div>

                <p className="text-center text-[11px] text-muted-foreground">
                  المساعد الذكي قد يخطئ. تحقق من المعلومات الطبية المهمة مع طبيبك.
                </p>
              </div>
            </div>
          </div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
