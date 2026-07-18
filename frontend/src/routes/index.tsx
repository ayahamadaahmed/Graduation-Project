import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { ChevronRight, ChevronLeft, Check } from "lucide-react";

import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { AppSidebar } from "@/components/app-sidebar";
import { AppHeader } from "@/components/app-header";
import { BookingStepper } from "@/components/booking/booking-stepper";
import { StepSpecialty } from "@/components/booking/step-specialty";
import { StepProvider } from "@/components/booking/step-provider";
import { StepDoctor } from "@/components/booking/step-doctor";
import { StepCalendar } from "@/components/booking/step-calendar";
import { StepTime } from "@/components/booking/step-time";
import { StepPatient, type PatientInfo } from "@/components/booking/step-patient";
import { StepSummary } from "@/components/booking/step-summary";
import { SuccessCard } from "@/components/booking/success-card";
import { stepTitles, type Specialty, type Provider, type Doctor } from "@/lib/booking-data";

export const Route = createFileRoute("/")({
  component: BookingPage,
});

function BookingPage() {
  const [step, setStep] = useState(1);
  const [specialty, setSpecialty] = useState<Specialty>();
  const [provider, setProvider] = useState<Provider>();
  const [doctor, setDoctor] = useState<Doctor>();
  const [date, setDate] = useState<Date>();
  const [month, setMonth] = useState(new Date());
  const [time, setTime] = useState<string>();
  const [patient, setPatient] = useState<PatientInfo>({
    name: "",
    phone: "",
    age: "",
    gender: "male",
    symptoms: "",
    hasInsurance: false,
  });
  const [confirmed, setConfirmed] = useState(false);

  const canNext = () => {
    if (step === 1) return !!specialty;
    if (step === 2) return !!provider;
    if (step === 3) return !!doctor;
    if (step === 4) return !!date;
    if (step === 5) return !!time;
    if (step === 6) return patient.name && patient.phone && patient.age;
    return true;
  };

  const next = () => canNext() && setStep((s) => Math.min(7, s + 1));
  const back = () => setStep((s) => Math.max(1, s - 1));
  const bookingId = `SC-${Math.floor(100000 + Math.random() * 900000)}`;

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="bg-background">
        <AppHeader />
        <main className="flex-1 space-y-4 p-4 md:p-5 lg:p-6">
          {confirmed ? (
            <SuccessCard
              doctor={doctor}
              date={date}
              time={time}
              bookingId={bookingId}
              onDownload={() => window.print()}
              onDashboard={() => {
                setConfirmed(false);
                setStep(1);
                setSpecialty(undefined);
                setProvider(undefined);
                setDoctor(undefined);
                setDate(undefined);
                setTime(undefined);
              }}
            />
          ) : (
            <>
              <div>
                <h1 className="text-xl font-bold md:text-2xl">حجز موعد جديد</h1>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  الخطوة {step} من {stepTitles.length} · {stepTitles[step - 1]}
                </p>
              </div>


              <BookingStepper current={step} />

              <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
                <div className="space-y-4">
                  {step === 1 && (
                    <StepSpecialty selected={specialty?.id} onSelect={setSpecialty} />
                  )}
                  {step === 2 && (
                    <StepProvider selected={provider?.id} onSelect={setProvider} />
                  )}
                  {step === 3 && <StepDoctor selected={doctor?.id} onSelect={setDoctor} />}
                  {step === 4 && (
                    <StepCalendar
                      selected={date}
                      onSelect={setDate}
                      month={month}
                      onMonthChange={setMonth}
                    />
                  )}
                  {step === 5 && <StepTime selected={time} onSelect={setTime} />}
                  {step === 6 && <StepPatient value={patient} onChange={setPatient} />}
                  {step === 7 && (
                    <StepSummary
                      specialty={specialty}
                      provider={provider}
                      doctor={doctor}
                      date={date}
                      time={time}
                    />
                  )}

                  <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card p-3 shadow-card">
                    <Button
                      variant="outline"
                      onClick={back}
                      disabled={step === 1}
                      className="h-10 rounded-lg text-[13px]"
                    >
                      <ChevronRight className="ml-1 h-3.5 w-3.5" />
                      السابق
                    </Button>
                    {step < 7 ? (
                      <Button
                        onClick={next}
                        disabled={!canNext()}
                        className="h-10 rounded-lg bg-primary text-[13px] hover:bg-primary/90"
                      >
                        التالي
                        <ChevronLeft className="mr-1 h-3.5 w-3.5" />
                      </Button>
                    ) : (
                      <Button
                        onClick={() => setConfirmed(true)}
                        className="h-10 rounded-lg bg-success text-[13px] text-success-foreground hover:bg-success/90"
                      >
                        <Check className="ml-1 h-3.5 w-3.5" />
                        تأكيد الحجز
                      </Button>
                    )}
                  </div>

                </div>

                <aside className="hidden lg:block">
                  <BookingSidebar
                    specialty={specialty}
                    provider={provider}
                    doctor={doctor}
                    date={date}
                    time={time}
                  />
                </aside>
              </div>
            </>
          )}
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

function BookingSidebar({
  specialty,
  provider,
  doctor,
  date,
  time,
}: {
  specialty?: Specialty;
  provider?: Provider;
  doctor?: Doctor;
  date?: Date;
  time?: string;
}) {
  const items = [
    { label: "التخصص", value: specialty?.name },
    { label: "المستشفى", value: provider?.name },
    { label: "الطبيب", value: doctor?.name },
    { label: "التاريخ", value: date?.toLocaleDateString("ar-SA") },
    { label: "الوقت", value: time },
  ];
  return (
    <div className="sticky top-20 rounded-xl border border-border bg-card p-4 shadow-card">
      <h3 className="mb-3 text-sm font-bold">تفاصيل الموعد</h3>
      <div className="space-y-2.5">
        {items.map((i) => (
          <div key={i.label} className="flex items-start justify-between gap-3 border-b border-border pb-2.5 last:border-0 last:pb-0">
            <span className="text-[11px] text-muted-foreground">{i.label}</span>
            <span className="text-[13px] font-semibold text-foreground text-left">
              {i.value ?? <span className="text-muted-foreground/60">—</span>}
            </span>
          </div>
        ))}
      </div>
      {doctor && (
        <div className="mt-4 rounded-lg bg-primary-soft p-3">
          <div className="text-[11px] text-primary/80">رسوم الكشف المتوقعة</div>
          <div className="mt-0.5 text-xl font-bold text-primary">{doctor.fee} ر.س</div>
        </div>
      )}
    </div>

  );
}
