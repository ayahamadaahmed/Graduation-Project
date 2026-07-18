import { MapPin, Star, Users, Building2 } from "lucide-react";
import { providers, type Provider } from "@/lib/booking-data";
import { cn } from "@/lib/utils";

export function StepProvider({
  selected,
  onSelect,
}: {
  selected?: string;
  onSelect: (p: Provider) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {providers.map((p) => {
        const active = selected === p.id;
        return (
          <button
            key={p.id}
            onClick={() => onSelect(p)}
            className={cn(
              "flex flex-col overflow-hidden rounded-xl border-2 bg-card text-right shadow-card transition-all hover:shadow-soft hover:-translate-y-0.5",
              active ? "border-primary ring-2 ring-primary/20" : "border-border hover:border-primary/40",
            )}
          >
            <div className={cn("relative flex h-36 items-center justify-center bg-gradient-to-br", p.imageBg)}>
              <Building2 className="h-16 w-16 text-white/90" />
              <div className="absolute top-3 right-3 flex items-center gap-1 rounded-full bg-white/95 px-2.5 py-1 text-xs font-bold text-foreground">
                <Star className="h-3.5 w-3.5 fill-yellow-500 text-yellow-500" />
                {p.rating}
              </div>
            </div>
            <div className="flex flex-1 flex-col gap-3 p-5">
              <h3 className="text-lg font-bold text-foreground">{p.name}</h3>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <MapPin className="h-4 w-4 text-primary" />
                {p.address}
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Users className="h-4 w-4 text-primary" />
                {p.doctorsCount} طبيب
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
