import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { stepTitles } from "@/lib/booking-data";

export function BookingStepper({ current }: { current: number }) {
  return (
    <div className="rounded-xl border border-border bg-card p-3 shadow-card md:p-4">
      <div className="flex items-center justify-between overflow-x-auto">

        {stepTitles.map((title, idx) => {
          const step = idx + 1;
          const done = step < current;
          const active = step === current;
          return (
            <div key={title} className="flex flex-1 items-center">
              <div className="flex flex-col items-center gap-2 min-w-[60px]">
                <div
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-bold transition-all",
                    done && "border-primary bg-primary text-primary-foreground",
                    active && "border-primary bg-primary-soft text-primary shadow-soft scale-110",
                    !done && !active && "border-border bg-muted text-muted-foreground",
                  )}
                >
                  {done ? <Check className="h-4 w-4" /> : step}
                </div>

                <span
                  className={cn(
                    "hidden text-xs font-medium md:block text-center",
                    active ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  {title}
                </span>
              </div>
              {idx < stepTitles.length - 1 && (
                <div
                  className={cn(
                    "mx-2 h-0.5 flex-1 rounded-full transition-colors",
                    done ? "bg-primary" : "bg-border",
                  )}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
