import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

export interface PatientInfo {
  name: string;
  phone: string;
  age: string;
  gender: "male" | "female";
  symptoms: string;
  hasInsurance: boolean;
}

export function StepPatient({
  value,
  onChange,
}: {
  value: PatientInfo;
  onChange: (v: PatientInfo) => void;
}) {
  const set = <K extends keyof PatientInfo>(k: K, v: PatientInfo[K]) =>
    onChange({ ...value, [k]: v });

  return (
    <div className="rounded-xl border border-border bg-card p-6 shadow-card">
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="name">الاسم الكامل</Label>
          <Input
            id="name"
            value={value.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="أدخل اسمك الكامل"
            className="h-10 rounded-xl"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="phone">رقم الجوال</Label>
          <Input
            id="phone"
            value={value.phone}
            onChange={(e) => set("phone", e.target.value)}
            placeholder="05xxxxxxxx"
            className="h-10 rounded-xl"
            dir="ltr"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="age">العمر</Label>
          <Input
            id="age"
            type="number"
            value={value.age}
            onChange={(e) => set("age", e.target.value)}
            placeholder="مثال: 32"
            className="h-10 rounded-xl"
          />
        </div>
        <div className="space-y-2">
          <Label>الجنس</Label>
          <RadioGroup
            value={value.gender}
            onValueChange={(v) => set("gender", v as "male" | "female")}
            className="flex h-10 items-center gap-6"
          >
            <div className="flex items-center gap-2">
              <RadioGroupItem value="male" id="male" />
              <Label htmlFor="male" className="cursor-pointer">ذكر</Label>
            </div>
            <div className="flex items-center gap-2">
              <RadioGroupItem value="female" id="female" />
              <Label htmlFor="female" className="cursor-pointer">أنثى</Label>
            </div>
          </RadioGroup>
        </div>
        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="symptoms">وصف الأعراض</Label>
          <Textarea
            id="symptoms"
            value={value.symptoms}
            onChange={(e) => set("symptoms", e.target.value)}
            placeholder="اذكر أعراضك أو سبب الزيارة..."
            rows={4}
            className="rounded-xl resize-none"
          />
        </div>
        <div className="md:col-span-2 flex items-center gap-3 rounded-xl bg-primary-soft/50 p-4">
          <Checkbox
            id="insurance"
            checked={value.hasInsurance}
            onCheckedChange={(c) => set("hasInsurance", c === true)}
          />
          <Label htmlFor="insurance" className="cursor-pointer text-sm">
            لدي تأمين طبي وأرغب في استخدامه لهذا الموعد
          </Label>
        </div>
      </div>
    </div>
  );
}
