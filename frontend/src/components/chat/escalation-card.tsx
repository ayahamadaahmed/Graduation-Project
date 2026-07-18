import { Headset, Clock, MessageCircle, PhoneCall } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";

export function EscalationCard({ escalation }: { escalation: { receptionist: string; wait: string } }) {
  return (
    <div className="w-full max-w-md overflow-hidden rounded-xl border border-warning/30 bg-warning/10 shadow-card">
      <div className="flex items-center gap-2 border-b border-warning/20 bg-warning/15 px-4 py-2.5 text-sm font-semibold text-warning-foreground">
        <Headset className="h-4 w-4" />
        هل تحتاج مساعدة بشرية؟
      </div>
      <div className="space-y-4 p-4">
        <p className="text-sm text-foreground">
          يبدو أن استفسارك يحتاج تدخل موظف الاستقبال. يمكنك التواصل الآن مع:
        </p>
        <div className="flex items-center gap-3 rounded-xl bg-card p-3">
          <Avatar className="h-10 w-11">
            <AvatarFallback className="bg-primary-soft font-bold text-primary">لش</AvatarFallback>
          </Avatar>
          <div className="flex-1">
            <div className="text-sm font-bold">{escalation.receptionist}</div>
            <div className="text-xs text-muted-foreground">موظفة استقبال</div>
          </div>
          <div className="flex items-center gap-1 rounded-lg bg-primary-soft px-2 py-1 text-xs font-semibold text-primary">
            <Clock className="h-3.5 w-3.5" />
            {escalation.wait}
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="outline" className="h-10 flex-1 rounded-xl">
            <MessageCircle className="ml-2 h-4 w-4" />
            متابعة مع المساعد
          </Button>
          <Button className="h-10 flex-1 rounded-xl bg-primary hover:bg-primary/90">
            <PhoneCall className="ml-2 h-4 w-4" />
            التحويل لموظف
          </Button>
        </div>
      </div>
    </div>
  );
}
