import { useState } from "react";
import { Calendar, Stethoscope, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Widget {
  doctor: string;
  specialty: string;
  date: string;
  slots: string[];
}

export function BookingWidget({ widget, onConfirm }: { widget: Widget; onConfirm?: (slot: string) => void }) {
  const [slot, setSlot] = useState<string>();
  const [done, setDone] = useState(false);

  if (done) {
    return (
      <div className="w-full max-w-md rounded-xl border border-success/30 bg-success/10 p-4 text-sm text-success-foreground">
        <div className="flex items-center gap-2 font-semibold text-success">
          <Check className="h-5 w-5" />
          تم تأكيد الحجز في {slot}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md overflow-hidden rounded-xl border border-border bg-card shadow-card">
      <div className="bg-gradient-to-l from-primary to-cyan-600 p-4 text-primary-foreground">
        <div className="text-xs opacity-90">حجز موعد مقترح</div>
        <div className="mt-1 flex items-center gap-2 text-base font-bold">
          <Stethoscope className="h-4 w-4" />
          {widget.doctor}
        </div>
        <div className="text-xs opacity-90">{widget.specialty}</div>
      </div>
      <div className="space-y-3 p-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Calendar className="h-4 w-4 text-primary" />
          {widget.date}
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-muted-foreground">المواعيد المتاحة</div>
          <div className="grid grid-cols-2 gap-2">
            {widget.slots.map((s) => (
              <button
                key={s}
                onClick={() => setSlot(s)}
                className={cn(
                  "rounded-xl border py-2 text-sm font-semibold transition-all",
                  slot === s
                    ? "border-primary bg-primary text-primary-foreground shadow-soft"
                    : "border-border bg-secondary hover:border-primary/40 hover:bg-primary-soft",
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <Button
          disabled={!slot}
          onClick={() => {
            if (slot) {
              onConfirm?.(slot);
              setDone(true);
            }
          }}
          className="h-10 w-full rounded-xl bg-primary hover:bg-primary/90"
        >
          تأكيد الحجز
        </Button>
      </div>
    </div>
  );
}
