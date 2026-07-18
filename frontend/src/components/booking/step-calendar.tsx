import { useMemo } from "react";
import { ChevronRight, ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const dayNames = ["أحد", "إثنين", "ثلاثاء", "أربعاء", "خميس", "جمعة", "سبت"];
const monthNames = [
  "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
  "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
];

export function StepCalendar({
  selected,
  onSelect,
  month,
  onMonthChange,
}: {
  selected?: Date;
  onSelect: (d: Date) => void;
  month: Date;
  onMonthChange: (d: Date) => void;
}) {
  const { days, unavailable } = useMemo(() => {
    const y = month.getFullYear();
    const m = month.getMonth();
    const first = new Date(y, m, 1).getDay();
    const total = new Date(y, m + 1, 0).getDate();
    const arr: (Date | null)[] = [];
    for (let i = 0; i < first; i++) arr.push(null);
    for (let d = 1; d <= total; d++) arr.push(new Date(y, m, d));
    // deterministic "unavailable" set: fridays + a few dates
    const unavail = new Set<number>();
    arr.forEach((d) => {
      if (!d) return;
      if (d.getDay() === 5) unavail.add(d.getDate());
      if ([3, 11, 22].includes(d.getDate())) unavail.add(d.getDate());
    });
    return { days: arr, unavailable: unavail };
  }, [month]);

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-card md:p-6">
      <div className="mb-6 flex items-center justify-between">
        <Button
          variant="outline"
          size="icon"
          className="rounded-xl"
          onClick={() => onMonthChange(new Date(month.getFullYear(), month.getMonth() - 1, 1))}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <div className="text-lg font-bold">
          {monthNames[month.getMonth()]} {month.getFullYear()}
        </div>
        <Button
          variant="outline"
          size="icon"
          className="rounded-xl"
          onClick={() => onMonthChange(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
      </div>
      <div className="mb-2 grid grid-cols-7 gap-2 text-center text-xs font-semibold text-muted-foreground">
        {dayNames.map((n) => (
          <div key={n} className="py-2">{n}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-2">
        {days.map((d, i) => {
          if (!d) return <div key={i} />;
          const isPast = d < today;
          const isUnavail = unavailable.has(d.getDate()) || isPast;
          const isSelected =
            selected &&
            d.getFullYear() === selected.getFullYear() &&
            d.getMonth() === selected.getMonth() &&
            d.getDate() === selected.getDate();
          const isToday = d.getTime() === today.getTime();
          return (
            <button
              key={i}
              disabled={isUnavail}
              onClick={() => onSelect(d)}
              className={cn(
                "aspect-square rounded-xl text-sm font-semibold transition-all",
                isSelected
                  ? "bg-primary text-primary-foreground shadow-soft scale-105"
                  : isUnavail
                  ? "cursor-not-allowed bg-muted/50 text-muted-foreground/40 line-through"
                  : "bg-primary-soft/50 text-foreground hover:bg-primary hover:text-primary-foreground",
                isToday && !isSelected && "ring-2 ring-primary/40",
              )}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>
      <div className="mt-6 flex flex-wrap gap-4 border-t border-border pt-4 text-xs">
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-md bg-primary-soft" />
          <span className="text-muted-foreground">متاح</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-md bg-primary" />
          <span className="text-muted-foreground">مختار</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-md bg-muted" />
          <span className="text-muted-foreground">غير متاح</span>
        </div>
      </div>
    </div>
  );
}
