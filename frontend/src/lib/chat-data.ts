export interface ChatMessage {
  id: string;
  role: "user" | "ai";
  text?: string;
  time: string;
  widget?: { type: "booking"; doctor: string; specialty: string; date: string; slots: string[] };
  escalation?: { receptionist: string; wait: string };
}

export interface Conversation {
  id: string;
  title: string;
  group: "today" | "yesterday" | "older";
  preview: string;
  messages: ChatMessage[];
}

export const suggestedQuestions = [
  { icon: "calendar", label: "حجز موعد" },
  { icon: "user", label: "البحث عن طبيب" },
  { icon: "flask", label: "نتائج التحاليل" },
  { icon: "file", label: "التقارير الطبية" },
  { icon: "map", label: "موقع العيادة" },
];

export const quickActions = [
  { icon: "calendar-plus", label: "حجز موعد", tone: "primary" as const },
  { icon: "calendar-x", label: "إلغاء موعد", tone: "muted" as const },
  { icon: "calendar-clock", label: "إعادة جدولة", tone: "muted" as const },
  { icon: "siren", label: "طوارئ", tone: "destructive" as const },
];

export const conversations: Conversation[] = [
  {
    id: "c1",
    title: "استفسار عن أعراض القلب",
    group: "today",
    preview: "أشعر بألم في الصدر منذ يومين...",
    messages: [
      {
        id: "m1",
        role: "ai",
        text: "مرحباً محمد 👋 أنا مساعدك الطبي الذكي. كيف يمكنني مساعدتك اليوم؟",
        time: "10:24 ص",
      },
    ],
  },
  { id: "c2", title: "حجز موعد أسنان", group: "today", preview: "أريد حجز موعد لتنظيف الأسنان", messages: [] },
  { id: "c3", title: "نتائج تحليل الدم", group: "yesterday", preview: "متى ستكون النتائج جاهزة؟", messages: [] },
  { id: "c4", title: "استفسار عن التأمين", group: "yesterday", preview: "هل التأمين يغطي...", messages: [] },
  { id: "c5", title: "موعد مراجعة الطبيب", group: "older", preview: "تأكيد الموعد القادم", messages: [] },
  { id: "c6", title: "روشتة الأدوية", group: "older", preview: "طلب تجديد الروشتة", messages: [] },
];

export const mockBookingWidget = {
  type: "booking" as const,
  doctor: "د. أحمد المنصور",
  specialty: "استشاري أمراض القلب",
  date: "الأربعاء، 22 يوليو 2026",
  slots: ["09:00 ص", "10:30 ص", "12:00 م", "02:00 م"],
};

export const mockEscalation = {
  receptionist: "أ. لينا الشهري",
  wait: "~ 3 دقائق",
};
