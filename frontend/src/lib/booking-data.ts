import {
  Heart,
  Stethoscope,
  Baby,
  Bone,
  Sparkles,
  Smile,
  type LucideIcon,
} from "lucide-react";

export interface Specialty {
  id: string;
  name: string;
  description: string;
  icon: LucideIcon;
  doctorsCount: number;
}

export const specialties: Specialty[] = [
  { id: "cardio", name: "أمراض القلب", description: "تشخيص وعلاج أمراض القلب والشرايين", icon: Heart, doctorsCount: 24 },
  { id: "internal", name: "الطب الباطني", description: "الرعاية الصحية الشاملة للبالغين", icon: Stethoscope, doctorsCount: 32 },
  { id: "pedia", name: "طب الأطفال", description: "رعاية صحية متكاملة للأطفال", icon: Baby, doctorsCount: 18 },
  { id: "ortho", name: "جراحة العظام", description: "علاج إصابات وأمراض العظام والمفاصل", icon: Bone, doctorsCount: 15 },
  { id: "derma", name: "الأمراض الجلدية", description: "علاج الأمراض الجلدية والتجميل", icon: Sparkles, doctorsCount: 12 },
  { id: "dental", name: "طب الأسنان", description: "علاج وتجميل الأسنان واللثة", icon: Smile, doctorsCount: 20 },
];

export interface Provider {
  id: string;
  name: string;
  rating: number;
  address: string;
  doctorsCount: number;
  imageBg: string;
}

export const providers: Provider[] = [
  { id: "p1", name: "مستشفى الملك فهد التخصصي", rating: 4.8, address: "الرياض - حي العليا", doctorsCount: 120, imageBg: "from-cyan-400 to-blue-500" },
  { id: "p2", name: "مستشفى الحياة الطبي", rating: 4.6, address: "جدة - حي الروضة", doctorsCount: 85, imageBg: "from-teal-400 to-cyan-500" },
  { id: "p3", name: "المركز الطبي الدولي", rating: 4.9, address: "الدمام - الكورنيش", doctorsCount: 96, imageBg: "from-emerald-400 to-teal-500" },
  { id: "p4", name: "مستشفى النور التخصصي", rating: 4.5, address: "مكة - العزيزية", doctorsCount: 74, imageBg: "from-sky-400 to-indigo-500" },
];

export interface Doctor {
  id: string;
  name: string;
  specialty: string;
  rating: number;
  experience: number;
  fee: number;
  availableToday: boolean;
  initials: string;
  color: string;
}

export const doctors: Doctor[] = [
  { id: "d1", name: "د. أحمد المنصور", specialty: "استشاري أمراض القلب", rating: 4.9, experience: 15, fee: 350, availableToday: true, initials: "أم", color: "from-cyan-500 to-teal-500" },
  { id: "d2", name: "د. سارة العتيبي", specialty: "أخصائي أول أمراض القلب", rating: 4.7, experience: 10, fee: 280, availableToday: true, initials: "سع", color: "from-pink-500 to-rose-500" },
  { id: "d3", name: "د. خالد الحربي", specialty: "استشاري قسطرة القلب", rating: 4.8, experience: 18, fee: 400, availableToday: false, initials: "خح", color: "from-indigo-500 to-purple-500" },
  { id: "d4", name: "د. نورة الشمري", specialty: "أخصائي أمراض القلب", rating: 4.6, experience: 8, fee: 250, availableToday: true, initials: "نش", color: "from-emerald-500 to-green-500" },
];

export const timeSlots = ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "14:00", "14:30", "15:00"];

export const stepTitles = [
  "اختر التخصص",
  "اختر مقدم الرعاية",
  "اختر الطبيب",
  "اختر التاريخ",
  "اختر الوقت",
  "بيانات المريض",
  "ملخص الحجز",
];
