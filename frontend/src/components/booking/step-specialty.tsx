import { specialties, type Specialty } from "@/lib/booking-data";
import { cn } from "@/lib/utils";

export function StepSpecialty({
  selected,
  onSelect,
}: {
  selected?: string;
  onSelect: (s: Specialty) => void;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {specialties.map((s) => {
        const active = selected === s.id;
        const Icon = s.icon;
        return (
          <button
            key={s.id}
            onClick={() => onSelect(s)}
            className={cn(
              "group flex flex-col items-start gap-4 rounded-xl border-2 bg-card p-6 text-right shadow-card transition-all hover:shadow-soft hover:-translate-y-0.5",
              active ? "border-primary ring-2 ring-primary/20" : "border-border hover:border-primary/40",
            )}
          >
            <div
              className={cn(
                "flex h-14 w-14 items-center justify-center rounded-xl transition-colors",
                active
                  ? "bg-primary text-primary-foreground"
                  : "bg-primary-soft text-primary group-hover:bg-primary group-hover:text-primary-foreground",
              )}
            >
              <Icon className="h-7 w-7" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-bold text-foreground">{s.name}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{s.description}</p>
            </div>
            <div className="text-xs font-medium text-primary">{s.doctorsCount} طبيب متاح</div>
          </button>
        );
      })}
    </div>
  );
}
