import { CheckCircle2, Calendar, Clock, Download, LayoutDashboard, Stethoscope } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Doctor } from "@/lib/booking-data";

export function SuccessCard({
  doctor,
  date,
  time,
  bookingId,
  onDashboard,
  onDownload,
}: {
  doctor?: Doctor;
  date?: Date;
  time?: string;
  bookingId: string;
  onDashboard: () => void;
  onDownload: () => void;
}) {
  return (
    <div className="mx-auto max-w-2xl">
      <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-soft">
        <div className="flex flex-col items-center gap-4 bg-gradient-to-br from-primary to-cyan-600 px-6 py-10 text-primary-foreground">
          <div className="flex h-20 w-20 items-center justify-center rounded-full bg-white/20 backdrop-blur-sm">
            <CheckCircle2 className="h-12 w-12" />
          </div>
          <h2 className="text-2xl font-bold">تم تأكيد الموعد بنجاح</h2>
          <p className="text-sm text-primary-foreground/90">رقم الحجز: {bookingId}</p>
        </div>
        <div className="space-y-4 p-6">
          <div className="flex items-center gap-3 rounded-xl bg-secondary p-4">
            <div className="flex h-10 w-11 items-center justify-center rounded-xl bg-primary-soft text-primary">
              <Stethoscope className="h-5 w-5" />
            </div>
            <div className="flex-1">
              <div className="text-xs text-muted-foreground">الطبيب</div>
              <div className="font-semibold">{doctor?.name}</div>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex items-center gap-3 rounded-xl bg-secondary p-4">
              <div className="flex h-10 w-11 items-center justify-center rounded-xl bg-primary-soft text-primary">
                <Calendar className="h-5 w-5" />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">التاريخ</div>
                <div className="font-semibold">{date?.toLocaleDateString("ar-SA")}</div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-xl bg-secondary p-4">
              <div className="flex h-10 w-11 items-center justify-center rounded-xl bg-primary-soft text-primary">
                <Clock className="h-5 w-5" />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">الوقت</div>
                <div className="font-semibold">{time}</div>
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-3 pt-2 sm:flex-row">
            <Button onClick={onDownload} variant="outline" className="flex-1 h-10 rounded-xl">
              <Download className="ml-2 h-4 w-4" />
              تحميل PDF
            </Button>
            <Button onClick={onDashboard} className="flex-1 h-10 rounded-xl bg-primary hover:bg-primary/90">
              <LayoutDashboard className="ml-2 h-4 w-4" />
              الذهاب للوحة التحكم
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
