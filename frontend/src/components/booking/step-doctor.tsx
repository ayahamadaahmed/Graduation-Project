import { Star, Briefcase, Wallet } from "lucide-react";
import { doctors, type Doctor } from "@/lib/booking-data";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function StepDoctor({
  selected,
  onSelect,
}: {
  selected?: string;
  onSelect: (d: Doctor) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {doctors.map((d) => {
        const active = selected === d.id;
        return (
          <button
            key={d.id}
            onClick={() => onSelect(d)}
            className={cn(
              "flex flex-col gap-4 rounded-xl border-2 bg-card p-5 text-right shadow-card transition-all hover:shadow-soft hover:-translate-y-0.5",
              active ? "border-primary ring-2 ring-primary/20" : "border-border hover:border-primary/40",
            )}
          >
            <div className="flex items-start gap-4">
              <div
                className={cn(
                  "flex h-16 w-16 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-lg font-bold text-white",
                  d.color,
                )}
              >
                {d.initials}
              </div>
              <div className="flex-1">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-base font-bold text-foreground">{d.name}</h3>
                  {d.availableToday && (
                    <Badge className="bg-success/15 text-success hover:bg-success/20 border-0 text-[10px]">
                      متاح اليوم
                    </Badge>
                  )}
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{d.specialty}</p>
                <div className="mt-2 flex items-center gap-1">
                  <Star className="h-4 w-4 fill-yellow-500 text-yellow-500" />
                  <span className="text-sm font-semibold">{d.rating}</span>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 border-t border-border pt-4">
              <div className="flex items-center gap-2 text-sm">
                <Briefcase className="h-4 w-4 text-primary" />
                <span className="text-muted-foreground">{d.experience} سنة خبرة</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <Wallet className="h-4 w-4 text-primary" />
                <span className="font-semibold text-foreground">{d.fee} ر.س</span>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
