import { Clock } from "lucide-react";
import { timeSlots } from "@/lib/booking-data";
import { cn } from "@/lib/utils";

export function StepTime({
  selected,
  onSelect,
}: {
  selected?: string;
  onSelect: (t: string) => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-6 shadow-card">
      <div className="mb-5 flex items-center gap-2 text-sm text-muted-foreground">
        <Clock className="h-4 w-4 text-primary" />
        الأوقات المتاحة
      </div>
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-5">
        {timeSlots.map((t) => {
          const active = selected === t;
          return (
            <button
              key={t}
              onClick={() => onSelect(t)}
              className={cn(
                "rounded-xl border-2 py-3 text-sm font-semibold transition-all",
                active
                  ? "border-primary bg-primary text-primary-foreground shadow-soft"
                  : "border-border bg-secondary text-foreground hover:border-primary hover:bg-primary-soft",
              )}
            >
              {t}
            </button>
          );
        })}
      </div>
    </div>
  );
}
