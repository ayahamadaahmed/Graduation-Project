import { Calendar, Clock, Stethoscope, Building2, Video } from "lucide-react";
import type { Doctor, Provider, Specialty } from "@/lib/booking-data";

interface Props {
  specialty?: Specialty;
  provider?: Provider;
  doctor?: Doctor;
  date?: Date;
  time?: string;
}

export function StepSummary({ specialty, provider, doctor, date, time }: Props) {
  const rows = [
    { icon: Stethoscope, label: "التخصص", value: specialty?.name },
    { icon: Building2, label: "المستشفى", value: provider?.name },
    { icon: Stethoscope, label: "الطبيب", value: doctor?.name },
    { icon: Calendar, label: "التاريخ", value: date?.toLocaleDateString("ar-SA") },
    { icon: Clock, label: "الوقت", value: time },
    { icon: Video, label: "نوع الاستشارة", value: "زيارة عيادة" },
  ];

  return (
    <div className="rounded-xl border border-border bg-card p-6 shadow-card">
      <h3 className="mb-5 text-lg font-bold">تفاصيل الحجز</h3>
      <div className="divide-y divide-border">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between gap-4 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-soft text-primary">
                <r.icon className="h-5 w-5" />
              </div>
              <span className="text-sm text-muted-foreground">{r.label}</span>
            </div>
            <span className="text-sm font-semibold text-foreground text-left">
              {r.value ?? "—"}
            </span>
          </div>
        ))}
      </div>
      {doctor && (
        <div className="mt-5 flex items-center justify-between rounded-xl bg-primary p-4 text-primary-foreground">
          <span className="text-sm font-medium">إجمالي رسوم الكشف</span>
          <span className="text-xl font-bold">{doctor.fee} ر.س</span>
        </div>
      )}
    </div>
  );
}
