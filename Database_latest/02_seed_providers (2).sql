/* =====================================================================
   MedMind -   |  Script 02: Provider catalog
   Adds 6 fully configured providers (2 hospitals, 2 clinics, 2 labs) to the
   4 existing ones = 10 providers. For each: branches, specialties, services,
   doctors, doctor<->branch / doctor<->service links, weekly working hours,
   and 14 days of availability slots.

   * Idempotent: every row is keyed on a natural key (tenant_key, branch code,
     license number, ...), ids are deterministic. Running twice adds nothing.
   * DRY RUN BY DEFAULT: @commit = 0 rolls everything back and only shows the
     summary. Set @commit = 1 to keep the data.
   * Existing providers and rows are not modified.

   Day-of-week follows the app (Python weekday): Mon=0 ... Sat=5, Sun=6.
   ===================================================================== */
IF DB_ID() <= 4 OR OBJECT_ID(N'dbo.providers', N'U') IS NULL
BEGIN
    RAISERROR(N'Select the restored MedMind database first.', 16, 1);
    SET NOEXEC ON;
END
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @commit bit = 0;        -- <<< 0 = dry run (rollback), 1 = keep the data
DECLARE @slot_days int = 14;    -- availability horizon starting today

DROP TABLE IF EXISTS #prov, #branch, #spec, #svc, #doc, #docbr, #hours;

BEGIN TRY
BEGIN TRANSACTION;

/* ---------- staging tables ---------- */
-- COLLATE DATABASE_DEFAULT keeps temp-table text columns compatible with this database.
CREATE TABLE #prov   (tenant_key varchar(100) COLLATE DATABASE_DEFAULT, name nvarchar(200) COLLATE DATABASE_DEFAULT,
                      slug varchar(150) COLLATE DATABASE_DEFAULT, org_type varchar(30) COLLATE DATABASE_DEFAULT,
                      phone varchar(30) COLLATE DATABASE_DEFAULT, email varchar(254) COLLATE DATABASE_DEFAULT,
                      address nvarchar(500) COLLATE DATABASE_DEFAULT, id uniqueidentifier NULL);
CREATE TABLE #branch (tenant_key varchar(100) COLLATE DATABASE_DEFAULT, code varchar(50) COLLATE DATABASE_DEFAULT,
                      mrn_code char(3) COLLATE DATABASE_DEFAULT, name_ar nvarchar(200) COLLATE DATABASE_DEFAULT,
                      name_en nvarchar(200) COLLATE DATABASE_DEFAULT, address_ar nvarchar(500) COLLATE DATABASE_DEFAULT,
                      address_en nvarchar(500) COLLATE DATABASE_DEFAULT, governorate nvarchar(100) COLLATE DATABASE_DEFAULT,
                      phone varchar(30) COLLATE DATABASE_DEFAULT, provider_id uniqueidentifier NULL, id uniqueidentifier NULL);
CREATE TABLE #spec   (tenant_key varchar(100) COLLATE DATABASE_DEFAULT, code varchar(100) COLLATE DATABASE_DEFAULT,
                      name_ar nvarchar(150) COLLATE DATABASE_DEFAULT, name_en nvarchar(150) COLLATE DATABASE_DEFAULT,
                      provider_id uniqueidentifier NULL, id uniqueidentifier NULL);
CREATE TABLE #svc    (tenant_key varchar(100) COLLATE DATABASE_DEFAULT, code varchar(50) COLLATE DATABASE_DEFAULT,
                      name_ar nvarchar(150) COLLATE DATABASE_DEFAULT, name_en nvarchar(150) COLLATE DATABASE_DEFAULT,
                      description_en nvarchar(500) COLLATE DATABASE_DEFAULT, duration_minutes int, price numeric(10,2),
                      service_type varchar(30) COLLATE DATABASE_DEFAULT, prep_ar nvarchar(500) COLLATE DATABASE_DEFAULT,
                      prep_en nvarchar(500) COLLATE DATABASE_DEFAULT, spec_code varchar(100) COLLATE DATABASE_DEFAULT,
                      provider_id uniqueidentifier NULL, id uniqueidentifier NULL, specialty_id uniqueidentifier NULL);
CREATE TABLE #doc    (doc_key varchar(20) COLLATE DATABASE_DEFAULT, tenant_key varchar(100) COLLATE DATABASE_DEFAULT,
                      spec_code varchar(100) COLLATE DATABASE_DEFAULT, name_ar nvarchar(200) COLLATE DATABASE_DEFAULT,
                      name_en nvarchar(200) COLLATE DATABASE_DEFAULT, license_number varchar(100) COLLATE DATABASE_DEFAULT,
                      bio_ar nvarchar(500) COLLATE DATABASE_DEFAULT, bio_en nvarchar(500) COLLATE DATABASE_DEFAULT,
                      fee numeric(10,2) NULL, tele_fee numeric(10,2) NULL, experience_years int,
                      gender varchar(10) COLLATE DATABASE_DEFAULT, rating numeric(3,2), review_count int,
                      provider_id uniqueidentifier NULL, specialty_id uniqueidentifier NULL, id uniqueidentifier NULL);
CREATE TABLE #docbr  (doc_key varchar(20) COLLATE DATABASE_DEFAULT, branch_code varchar(50) COLLATE DATABASE_DEFAULT,
                      is_primary bit);
CREATE TABLE #hours  (doc_key varchar(20) COLLATE DATABASE_DEFAULT, branch_code varchar(50) COLLATE DATABASE_DEFAULT,
                      days varchar(30) COLLATE DATABASE_DEFAULT, start_time time(0), end_time time(0), slot_minutes int);

INSERT INTO #prov (tenant_key, name, slug, org_type, phone, email, address) VALUES
    (N'hospital-002', N'Nile Care Hospital', N'nile-care-hospital', N'hospital', N'+201000000010', N'info@nilecare-demo.com', N'Giza, Egypt'),
    (N'hospital-003', N'Alexandria Medical Center', N'alexandria-medical-center', N'hospital', N'+201000000011', N'info@alexmed-demo.com', N'Alexandria, Egypt'),
    (N'clinic-002', N'Al Noor Internal Medicine & Diabetes Clinic', N'al-noor-internal-medicine-diabetes-clinic', N'clinic', N'+201000000012', N'info@alnoor-demo.com', N'Maadi, Cairo, Egypt'),
    (N'clinic-003', N'Heart & Vascular Clinic', N'heart-vascular-clinic', N'clinic', N'+201000000013', N'info@heartvascular-demo.com', N'Heliopolis, Cairo, Egypt'),
    (N'lab-002', N'Delta Diagnostic Laboratories', N'delta-diagnostic-laboratories', N'diagnostic_lab', N'+201000000014', N'info@deltalabs-demo.com', N'Tanta, Egypt'),
    (N'lab-003', N'Nile Radiology Center', N'nile-radiology-center', N'diagnostic_lab', N'+201000000015', N'info@nileradiology-demo.com', N'Dokki, Giza, Egypt');
INSERT INTO #branch (tenant_key, code, mrn_code, name_ar, name_en, address_ar, address_en, governorate, phone) VALUES
    (N'hospital-002', N'GIZA', N'NCG', N'نايل كير - الجيزة', N'Nile Care - Giza', N'شارع الهرم، الجيزة', N'Pyramids Road, Giza', N'Giza', N'+201000000110'),
    (N'hospital-002', N'OCT', N'NCO', N'نايل كير - 6 أكتوبر', N'Nile Care - 6th of October', N'الحي المتميز، 6 أكتوبر', N'Entertainment District, 6th of October', N'Giza', N'+201000000111'),
    (N'hospital-003', N'SMO', N'AMS', N'المركز الطبي - سموحة', N'Alexandria Medical - Smouha', N'سموحة، الإسكندرية', N'Smouha, Alexandria', N'Alexandria', N'+201000000120'),
    (N'hospital-003', N'MAN', N'AMM', N'المركز الطبي - المنشية', N'Alexandria Medical - Mansheya', N'المنشية، الإسكندرية', N'Mansheya, Alexandria', N'Alexandria', N'+201000000121'),
    (N'clinic-002', N'MAA', N'ANM', N'عيادة النور - المعادي', N'Al Noor - Maadi', N'المعادي، القاهرة', N'Maadi, Cairo', N'Cairo', N'+201000000130'),
    (N'clinic-002', N'NSR', N'ANN', N'عيادة النور - مدينة نصر', N'Al Noor - Nasr City', N'مدينة نصر، القاهرة', N'Nasr City, Cairo', N'Cairo', N'+201000000131'),
    (N'clinic-003', N'HEL', N'HVH', N'عيادة القلب - مصر الجديدة', N'Heart Clinic - Heliopolis', N'مصر الجديدة، القاهرة', N'Heliopolis, Cairo', N'Cairo', N'+201000000140'),
    (N'lab-002', N'TNT', N'DLT', N'معامل دلتا - طنطا', N'Delta Labs - Tanta', N'طنطا، الغربية', N'Tanta, Gharbia', N'Gharbia', N'+201000000150'),
    (N'lab-002', N'NSR', N'DLN', N'معامل دلتا - مدينة نصر', N'Delta Labs - Nasr City', N'مدينة نصر، القاهرة', N'Nasr City, Cairo', N'Cairo', N'+201000000151'),
    (N'lab-003', N'DOK', N'NRD', N'مركز النيل للأشعة - الدقي', N'Nile Radiology - Dokki', N'الدقي، الجيزة', N'Dokki, Giza', N'Giza', N'+201000000160'),
    (N'lab-003', N'MAA', N'NRM', N'مركز النيل للأشعة - المعادي', N'Nile Radiology - Maadi', N'المعادي، القاهرة', N'Maadi, Cairo', N'Cairo', N'+201000000161');
INSERT INTO #spec (tenant_key, code, name_ar, name_en) VALUES
    (N'hospital-002', N'INTERNAL_MEDICINE', N'الباطنة العامة', N'Internal Medicine'),
    (N'hospital-002', N'CARDIOLOGY', N'أمراض القلب والأوعية الدموية', N'Cardiology'),
    (N'hospital-002', N'ORTHOPEDICS', N'العظام والمفاصل', N'Orthopedics'),
    (N'hospital-002', N'NEUROLOGY', N'المخ والأعصاب', N'Neurology'),
    (N'hospital-003', N'GENERAL_SURGERY', N'الجراحة العامة', N'General Surgery'),
    (N'hospital-003', N'PEDIATRICS', N'طب الأطفال', N'Pediatrics'),
    (N'hospital-003', N'OBSTETRICS_GYNECOLOGY', N'النساء والتوليد', N'Obstetrics & Gynecology'),
    (N'hospital-003', N'ENT', N'الأنف والأذن والحنجرة', N'Ear, Nose & Throat'),
    (N'clinic-002', N'INTERNAL_MEDICINE', N'الباطنة العامة', N'Internal Medicine'),
    (N'clinic-002', N'ENDOCRINOLOGY', N'الغدد الصماء والسكر', N'Endocrinology & Diabetes'),
    (N'clinic-003', N'CARDIOLOGY', N'أمراض القلب والأوعية الدموية', N'Cardiology'),
    (N'clinic-003', N'INTERNAL_MEDICINE', N'الباطنة العامة', N'Internal Medicine'),
    (N'lab-002', N'CLINICAL_PATHOLOGY', N'الباثولوجيا الإكلينيكية', N'Clinical Pathology'),
    (N'lab-003', N'RADIOLOGY', N'الأشعة التشخيصية', N'Diagnostic Radiology');
INSERT INTO #svc (tenant_key, code, name_ar, name_en, description_en, duration_minutes, price, service_type, prep_ar, prep_en, spec_code) VALUES
    (N'hospital-002', N'INTERNAL_CONSULT', N'كشف باطنة', N'Internal Medicine Consultation', N'General internal medicine examination', 30, 600, N'consultation', NULL, NULL, N'INTERNAL_MEDICINE'),
    (N'hospital-002', N'CARDIO_CONSULT', N'كشف قلب', N'Cardiology Consultation', N'Heart and circulation examination', 30, 800, N'consultation', NULL, NULL, N'CARDIOLOGY'),
    (N'hospital-002', N'ECG_TEST', N'رسم قلب', N'Electrocardiogram (ECG)', N'Resting 12-lead ECG', 20, 250, N'diagnostic', NULL, NULL, N'CARDIOLOGY'),
    (N'hospital-002', N'ORTHO_CONSULT', N'كشف عظام', N'Orthopedic Consultation', N'Bone and joint examination', 30, 700, N'consultation', NULL, NULL, N'ORTHOPEDICS'),
    (N'hospital-002', N'NEURO_CONSULT', N'كشف مخ وأعصاب', N'Neurology Consultation', N'Brain and nervous system examination', 30, 750, N'consultation', NULL, NULL, N'NEUROLOGY'),
    (N'hospital-003', N'SURGERY_ASSESS', N'تقييم جراحة عامة', N'General Surgery Assessment', N'Pre-operative surgical assessment', 45, 900, N'surgery', N'إحضار التقارير والتحاليل السابقة', N'Bring previous reports and lab results', N'GENERAL_SURGERY'),
    (N'hospital-003', N'PED_CONSULT', N'كشف أطفال', N'Pediatric Consultation', N'Child health examination', 30, 500, N'consultation', NULL, NULL, N'PEDIATRICS'),
    (N'hospital-003', N'GYN_CONSULT', N'كشف نساء وتوليد', N'Obstetrics & Gynecology Consultation', N'Women''s health examination', 30, 650, N'consultation', NULL, NULL, N'OBSTETRICS_GYNECOLOGY'),
    (N'hospital-003', N'ENT_CONSULT', N'كشف أنف وأذن وحنجرة', N'ENT Consultation', N'Ear, nose and throat examination', 30, 550, N'consultation', NULL, NULL, N'ENT'),
    (N'clinic-002', N'INTERNAL_CONSULT', N'كشف باطنة', N'Internal Medicine Consultation', N'General internal medicine examination', 30, 450, N'consultation', NULL, NULL, N'INTERNAL_MEDICINE'),
    (N'clinic-002', N'DIABETES_FOLLOWUP', N'متابعة السكر', N'Diabetes Follow-up', N'Follow-up visit for diabetes control', 20, 350, N'follow_up', NULL, NULL, N'ENDOCRINOLOGY'),
    (N'clinic-002', N'ENDO_CONSULT', N'كشف غدد صماء', N'Endocrinology Consultation', N'Hormone and metabolic examination', 30, 500, N'consultation', NULL, NULL, N'ENDOCRINOLOGY'),
    (N'clinic-002', N'THYROID_ASSESS', N'تقييم الغدة الدرقية', N'Thyroid Assessment', N'Thyroid examination and review of results', 30, 600, N'diagnostic', NULL, NULL, N'ENDOCRINOLOGY'),
    (N'clinic-003', N'CARDIO_CONSULT', N'كشف قلب', N'Cardiology Consultation', N'Heart and circulation examination', 30, 700, N'consultation', NULL, NULL, N'CARDIOLOGY'),
    (N'clinic-003', N'ECG_TEST', N'رسم قلب', N'Electrocardiogram (ECG)', N'Resting 12-lead ECG', 20, 200, N'diagnostic', NULL, NULL, N'CARDIOLOGY'),
    (N'clinic-003', N'ECHO_TEST', N'إيكو على القلب', N'Echocardiography', N'Ultrasound examination of the heart', 30, 700, N'diagnostic', NULL, NULL, N'CARDIOLOGY'),
    (N'clinic-003', N'CARDIO_FOLLOWUP', N'متابعة قلب', N'Cardiology Follow-up', N'Follow-up visit for heart conditions', 20, 400, N'follow_up', NULL, NULL, N'CARDIOLOGY'),
    (N'clinic-003', N'INTERNAL_CONSULT', N'كشف باطنة', N'Internal Medicine Consultation', N'General internal medicine examination', 30, 400, N'consultation', NULL, NULL, N'INTERNAL_MEDICINE'),
    (N'lab-002', N'CBC', N'صورة دم كاملة', N'Complete Blood Count (CBC)', N'Full blood count with differential', 15, 150, N'diagnostic', NULL, NULL, N'CLINICAL_PATHOLOGY'),
    (N'lab-002', N'RENAL_PANEL', N'وظائف الكلى', N'Renal Function Panel', N'Urea, creatinine and electrolytes', 15, 300, N'diagnostic', NULL, NULL, N'CLINICAL_PATHOLOGY'),
    (N'lab-002', N'LIPID_PROFILE', N'تحليل دهون الدم', N'Lipid Profile', N'Cholesterol and triglycerides', 15, 350, N'diagnostic', N'الصيام من 10 إلى 12 ساعة قبل التحليل', N'Fast for 10 to 12 hours before the test', N'CLINICAL_PATHOLOGY'),
    (N'lab-002', N'LIVER_PANEL', N'وظائف الكبد', N'Liver Function Panel', N'Liver enzymes and bilirubin', 15, 320, N'diagnostic', NULL, NULL, N'CLINICAL_PATHOLOGY'),
    (N'lab-002', N'HBA1C', N'السكر التراكمي', N'HbA1c', N'Three-month average blood glucose', 15, 280, N'diagnostic', NULL, NULL, N'CLINICAL_PATHOLOGY'),
    (N'lab-003', N'CHEST_XRAY', N'أشعة سينية على الصدر', N'Chest X-Ray', N'Standard chest radiograph', 15, 200, N'diagnostic', NULL, NULL, N'RADIOLOGY'),
    (N'lab-003', N'CT_KIDNEY', N'أشعة مقطعية على الكلى', N'Kidney CT Scan', N'CT scan of the kidneys', 30, 1500, N'diagnostic', N'الصيام 4 ساعات وإحضار نتيجة الكرياتينين', N'Fast for 4 hours and bring the latest creatinine result', N'RADIOLOGY'),
    (N'lab-003', N'MRI_BRAIN', N'رنين مغناطيسي على المخ', N'Brain MRI', N'Magnetic resonance imaging of the brain', 45, 1800, N'diagnostic', N'إزالة أي قطع معدنية قبل الفحص', N'Remove all metal objects before the scan', N'RADIOLOGY'),
    (N'lab-003', N'ULTRASOUND_ABD', N'موجات صوتية على البطن', N'Abdominal Ultrasound', N'Ultrasound of the abdomen', 20, 400, N'diagnostic', N'الصيام 6 ساعات وامتلاء المثانة', N'Fast for 6 hours and arrive with a full bladder', N'RADIOLOGY');
INSERT INTO #doc (doc_key, tenant_key, spec_code, name_ar, name_en, license_number, bio_ar, bio_en, fee, tele_fee, experience_years, gender, rating, review_count) VALUES
    (N'h2_int', N'hospital-002', N'INTERNAL_MEDICINE', N'د. هشام فؤاد', N'Dr. Hesham Fouad', N'EG-NCH-INT-001', N'استشاري الباطنة العامة بخبرة 18 سنة', N'Internal Medicine specialist with 18 years of experience.', 600, NULL, 18, N'male', 4.7, 162),
    (N'h2_car', N'hospital-002', N'CARDIOLOGY', N'د. منى عبد الرحمن', N'Dr. Mona Abdelrahman', N'EG-NCH-CAR-001', N'استشارية أمراض القلب والأوعية الدموية بخبرة 15 سنة', N'Cardiology specialist with 15 years of experience.', 800, 600, 15, N'female', 4.8, 205),
    (N'h2_ort', N'hospital-002', N'ORTHOPEDICS', N'د. كريم صبري', N'Dr. Karim Sabry', N'EG-NCH-ORT-001', N'استشاري العظام والمفاصل بخبرة 12 سنة', N'Orthopedics specialist with 12 years of experience.', 700, NULL, 12, N'male', 4.6, 118),
    (N'h2_neu', N'hospital-002', N'NEUROLOGY', N'د. نادية شوقي', N'Dr. Nadia Shawky', N'EG-NCH-NEU-001', N'استشارية المخ والأعصاب بخبرة 14 سنة', N'Neurology specialist with 14 years of experience.', 750, 550, 14, N'female', 4.8, 141),
    (N'h3_sur', N'hospital-003', N'GENERAL_SURGERY', N'د. عمرو الشافعي', N'Dr. Amr El-Shafei', N'EG-AMC-SUR-001', N'استشاري الجراحة العامة بخبرة 20 سنة', N'General Surgery specialist with 20 years of experience.', 900, NULL, 20, N'male', 4.9, 230),
    (N'h3_ped', N'hospital-003', N'PEDIATRICS', N'د. سلمى جمال', N'Dr. Salma Gamal', N'EG-AMC-PED-001', N'استشارية طب الأطفال بخبرة 11 سنة', N'Pediatrics specialist with 11 years of experience.', 500, NULL, 11, N'female', 4.9, 310),
    (N'h3_gyn', N'hospital-003', N'OBSTETRICS_GYNECOLOGY', N'د. دينا رضوان', N'Dr. Dina Radwan', N'EG-AMC-GYN-001', N'استشارية النساء والتوليد بخبرة 16 سنة', N'Obstetrics & Gynecology specialist with 16 years of experience.', 650, NULL, 16, N'female', 4.7, 187),
    (N'h3_ent', N'hospital-003', N'ENT', N'د. باسم عز الدين', N'Dr. Bassem Ezzeldin', N'EG-AMC-ENT-001', N'استشاري الأنف والأذن والحنجرة بخبرة 13 سنة', N'Ear, Nose & Throat specialist with 13 years of experience.', 550, NULL, 13, N'male', 4.5, 96),
    (N'c2_int', N'clinic-002', N'INTERNAL_MEDICINE', N'د. طارق مصطفى', N'Dr. Tarek Mostafa', N'EG-ANC-INT-001', N'استشاري الباطنة العامة بخبرة 17 سنة', N'Internal Medicine specialist with 17 years of experience.', 450, NULL, 17, N'male', 4.6, 144),
    (N'c2_en1', N'clinic-002', N'ENDOCRINOLOGY', N'د. إيمان سعيد', N'Dr. Eman Said', N'EG-ANC-END-001', N'استشارية الغدد الصماء والسكر بخبرة 14 سنة', N'Endocrinology & Diabetes specialist with 14 years of experience.', 500, 350, 14, N'female', 4.8, 176),
    (N'c2_en2', N'clinic-002', N'ENDOCRINOLOGY', N'د. أحمد لطفي', N'Dr. Ahmed Lotfy', N'EG-ANC-END-002', N'استشاري الغدد الصماء والسكر بخبرة 9 سنة', N'Endocrinology & Diabetes specialist with 9 years of experience.', 400, NULL, 9, N'male', 4.4, 83),
    (N'c3_ca1', N'clinic-003', N'CARDIOLOGY', N'د. وليد حسن', N'Dr. Walid Hassan', N'EG-HVC-CAR-001', N'استشاري أمراض القلب والأوعية الدموية بخبرة 19 سنة', N'Cardiology specialist with 19 years of experience.', 700, 500, 19, N'male', 4.9, 254),
    (N'c3_ca2', N'clinic-003', N'CARDIOLOGY', N'د. لبنى يوسف', N'Dr. Lobna Youssef', N'EG-HVC-CAR-002', N'استشارية أمراض القلب والأوعية الدموية بخبرة 12 سنة', N'Cardiology specialist with 12 years of experience.', 650, NULL, 12, N'female', 4.7, 121),
    (N'c3_int', N'clinic-003', N'INTERNAL_MEDICINE', N'د. شريف منير', N'Dr. Sherif Mounir', N'EG-HVC-INT-001', N'استشاري الباطنة العامة بخبرة 10 سنة', N'Internal Medicine specialist with 10 years of experience.', 400, NULL, 10, N'male', 4.5, 77),
    (N'l2_pa1', N'lab-002', N'CLINICAL_PATHOLOGY', N'د. غادة إبراهيم', N'Dr. Ghada Ibrahim', N'EG-DDL-PTH-001', N'استشارية الباثولوجيا الإكلينيكية بخبرة 15 سنة', N'Clinical Pathology specialist with 15 years of experience.', NULL, NULL, 15, N'female', 4.8, 64),
    (N'l2_pa2', N'lab-002', N'CLINICAL_PATHOLOGY', N'د. ماجد عبد الله', N'Dr. Maged Abdullah', N'EG-DDL-PTH-002', N'استشاري الباثولوجيا الإكلينيكية بخبرة 11 سنة', N'Clinical Pathology specialist with 11 years of experience.', NULL, NULL, 11, N'male', 4.6, 52),
    (N'l3_ra1', N'lab-003', N'RADIOLOGY', N'د. حازم فاروق', N'Dr. Hazem Farouk', N'EG-NRC-RAD-001', N'استشاري الأشعة التشخيصية بخبرة 17 سنة', N'Diagnostic Radiology specialist with 17 years of experience.', NULL, NULL, 17, N'male', 4.8, 88),
    (N'l3_ra2', N'lab-003', N'RADIOLOGY', N'د. سها عادل', N'Dr. Soha Adel', N'EG-NRC-RAD-002', N'استشارية الأشعة التشخيصية بخبرة 13 سنة', N'Diagnostic Radiology specialist with 13 years of experience.', NULL, NULL, 13, N'female', 4.7, 71);
INSERT INTO #docbr (doc_key, branch_code, is_primary) VALUES
    (N'h2_int', N'GIZA', 1),
    (N'h2_int', N'OCT', 0),
    (N'h2_car', N'GIZA', 1),
    (N'h2_ort', N'OCT', 1),
    (N'h2_ort', N'GIZA', 0),
    (N'h2_neu', N'GIZA', 1),
    (N'h3_sur', N'SMO', 1),
    (N'h3_ped', N'SMO', 1),
    (N'h3_ped', N'MAN', 0),
    (N'h3_gyn', N'MAN', 1),
    (N'h3_ent', N'SMO', 1),
    (N'c2_int', N'MAA', 1),
    (N'c2_en1', N'MAA', 1),
    (N'c2_en1', N'NSR', 0),
    (N'c2_en2', N'NSR', 1),
    (N'c3_ca1', N'HEL', 1),
    (N'c3_ca2', N'HEL', 1),
    (N'c3_int', N'HEL', 1),
    (N'l2_pa1', N'TNT', 1),
    (N'l2_pa2', N'NSR', 1),
    (N'l3_ra1', N'DOK', 1),
    (N'l3_ra2', N'MAA', 1);
INSERT INTO #hours (doc_key, branch_code, days, start_time, end_time, slot_minutes) VALUES
    (N'h2_int', N'GIZA', N'5,6,0', N'09:00', N'13:00', 30),
    (N'h2_int', N'OCT', N'2', N'14:00', N'18:00', 30),
    (N'h2_car', N'GIZA', N'6,1,3', N'10:00', N'14:00', 30),
    (N'h2_ort', N'OCT', N'5,0,2', N'09:00', N'13:00', 30),
    (N'h2_ort', N'GIZA', N'3', N'15:00', N'18:00', 30),
    (N'h2_neu', N'GIZA', N'5,2', N'11:00', N'15:00', 30),
    (N'h3_sur', N'SMO', N'6,1,3', N'09:00', N'13:00', 30),
    (N'h3_ped', N'SMO', N'5,0,2', N'10:00', N'14:00', 30),
    (N'h3_ped', N'MAN', N'3', N'15:00', N'19:00', 30),
    (N'h3_gyn', N'MAN', N'6,1', N'12:00', N'16:00', 30),
    (N'h3_ent', N'SMO', N'0,2', N'14:00', N'18:00', 30),
    (N'c2_int', N'MAA', N'5,6,1', N'16:00', N'20:00', 30),
    (N'c2_en1', N'MAA', N'0,2', N'16:00', N'20:00', 30),
    (N'c2_en1', N'NSR', N'3', N'10:00', N'14:00', 30),
    (N'c2_en2', N'NSR', N'5,6,1', N'10:00', N'14:00', 30),
    (N'c3_ca1', N'HEL', N'5,0,2', N'17:00', N'21:00', 30),
    (N'c3_ca2', N'HEL', N'6,1,3', N'17:00', N'21:00', 30),
    (N'c3_int', N'HEL', N'2,3', N'10:00', N'14:00', 30),
    (N'l2_pa1', N'TNT', N'5,6,0,1,2,3', N'08:00', N'12:00', 15),
    (N'l2_pa2', N'NSR', N'5,6,0,1,2,3', N'09:00', N'13:00', 15),
    (N'l3_ra1', N'DOK', N'5,6,0,1,2,3', N'09:00', N'13:00', 30),
    (N'l3_ra2', N'MAA', N'5,0,1,3', N'12:00', N'16:00', 30);

/* ---------- providers ---------- */
UPDATE #prov SET id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|provider|', tenant_key)), 1, 16) AS uniqueidentifier);

INSERT INTO dbo.providers (id, tenant_key, name, slug, org_type, verification_status, default_language, timezone, currency_code,
                           phone, email, address, is_active, created_at, updated_at)
SELECT s.id, s.tenant_key, s.name, s.slug, s.org_type, 'verified', 'ar', 'Africa/Cairo', 'EGP',
       s.phone, s.email, s.address, 1, GETUTCDATE(), GETUTCDATE()
FROM #prov s
WHERE NOT EXISTS (SELECT 1 FROM dbo.providers p WHERE p.tenant_key = s.tenant_key OR p.slug = s.slug);

-- always use the ids that really exist in the database
UPDATE s SET id = p.id FROM #prov s JOIN dbo.providers p ON p.tenant_key = s.tenant_key;

/* ---------- branches ---------- */
UPDATE b SET provider_id = p.id FROM #branch b JOIN #prov p ON p.tenant_key = b.tenant_key;
UPDATE #branch SET id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|branch|', tenant_key, N'|', code)), 1, 16) AS uniqueidentifier);

INSERT INTO dbo.branches (id, provider_id, code, name_ar, name_en, address_ar, address_en, governorate, latitude, longitude,
                          phone, whatsapp, timezone, is_active, created_at, updated_at, mrn_code)
SELECT s.id, s.provider_id, s.code, s.name_ar, s.name_en, s.address_ar, s.address_en, s.governorate, NULL, NULL,
       s.phone, s.phone, 'Africa/Cairo', 1, GETUTCDATE(), GETUTCDATE(), s.mrn_code
FROM #branch s
WHERE NOT EXISTS (SELECT 1 FROM dbo.branches x WHERE x.provider_id = s.provider_id AND x.code = s.code)
  AND NOT EXISTS (SELECT 1 FROM dbo.branches x WHERE x.provider_id = s.provider_id AND x.mrn_code = s.mrn_code);

UPDATE s SET id = x.id FROM #branch s JOIN dbo.branches x ON x.provider_id = s.provider_id AND x.code = s.code;

/* ---------- specialties ---------- */
UPDATE s SET provider_id = p.id FROM #spec s JOIN #prov p ON p.tenant_key = s.tenant_key;
UPDATE #spec SET id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|specialty|', tenant_key, N'|', code)), 1, 16) AS uniqueidentifier);

INSERT INTO dbo.specialties (id, provider_id, code, name_ar, name_en, description_ar, description_en, is_active, created_at, updated_at)
SELECT s.id, s.provider_id, s.code, s.name_ar, s.name_en, NULL, s.name_en, 1, GETUTCDATE(), GETUTCDATE()
FROM #spec s
WHERE NOT EXISTS (SELECT 1 FROM dbo.specialties x WHERE x.provider_id = s.provider_id AND x.code = s.code);

UPDATE s SET id = x.id FROM #spec s JOIN dbo.specialties x ON x.provider_id = s.provider_id AND x.code = s.code;

/* ---------- services (+ specialty link) ---------- */
UPDATE s SET provider_id = p.id FROM #svc s JOIN #prov p ON p.tenant_key = s.tenant_key;
UPDATE s SET specialty_id = sp.id FROM #svc s JOIN #spec sp ON sp.tenant_key = s.tenant_key AND sp.code = s.spec_code;
UPDATE #svc SET id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|service|', tenant_key, N'|', code)), 1, 16) AS uniqueidentifier);

INSERT INTO dbo.services (id, provider_id, code, name_ar, name_en, description_ar, description_en, duration_minutes, price,
                          service_type, requires_preparation, preparation_instructions_ar, preparation_instructions_en,
                          is_active, created_at, updated_at, voice_label_ar, voice_label_en, voice_featured_rank)
SELECT s.id, s.provider_id, s.code, s.name_ar, s.name_en, NULL, s.description_en, s.duration_minutes, s.price,
       s.service_type, CASE WHEN s.prep_en IS NULL THEN 0 ELSE 1 END, s.prep_ar, s.prep_en,
       1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET(), NULL, NULL, NULL
FROM #svc s
WHERE NOT EXISTS (SELECT 1 FROM dbo.services x WHERE x.provider_id = s.provider_id AND x.code = s.code);

UPDATE s SET id = x.id FROM #svc s JOIN dbo.services x ON x.provider_id = s.provider_id AND x.code = s.code;

INSERT INTO dbo.service_specialties (id, provider_id, service_id, specialty_id, created_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|service_specialty|', s.id, N'|', s.specialty_id)), 1, 16) AS uniqueidentifier),
       s.provider_id, s.id, s.specialty_id, SYSDATETIMEOFFSET()
FROM #svc s
WHERE NOT EXISTS (SELECT 1 FROM dbo.service_specialties x WHERE x.service_id = s.id AND x.specialty_id = s.specialty_id);

/* ---------- doctors ---------- */
UPDATE d SET provider_id = p.id FROM #doc d JOIN #prov p ON p.tenant_key = d.tenant_key;
UPDATE d SET specialty_id = sp.id FROM #doc d JOIN #spec sp ON sp.tenant_key = d.tenant_key AND sp.code = d.spec_code;
UPDATE #doc SET id = CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|doctor|', tenant_key, N'|', doc_key)), 1, 16) AS uniqueidentifier);

INSERT INTO dbo.doctors (id, provider_id, specialty_id, full_name_ar, full_name_en, license_number, bio_ar, bio_en,
                         consultation_fee, teleconsultation_fee, experience_years, gender, photo_url, rating_avg, review_count,
                         accepting_new_patients, verification_status, is_active, created_at, updated_at)
SELECT s.id, s.provider_id, s.specialty_id, s.name_ar, s.name_en, s.license_number, s.bio_ar, s.bio_en,
       s.fee, s.tele_fee, s.experience_years, s.gender, NULL, s.rating, s.review_count,
       1, 'verified', 1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #doc s
WHERE NOT EXISTS (SELECT 1 FROM dbo.doctors x WHERE x.provider_id = s.provider_id AND x.license_number = s.license_number);

UPDATE s SET id = x.id FROM #doc s JOIN dbo.doctors x ON x.provider_id = s.provider_id AND x.license_number = s.license_number;

/* doctor <-> branch */
INSERT INTO dbo.doctor_branches (id, provider_id, doctor_id, branch_id, is_primary, is_active, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|doctor_branch|', d.id, N'|', b.id)), 1, 16) AS uniqueidentifier),
       d.provider_id, d.id, b.id, l.is_primary, 1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #docbr l
JOIN #doc d    ON d.doc_key = l.doc_key
JOIN #branch b ON b.tenant_key = d.tenant_key AND b.code = l.branch_code
WHERE NOT EXISTS (SELECT 1 FROM dbo.doctor_branches x WHERE x.doctor_id = d.id AND x.branch_id = b.id)
  AND (l.is_primary = 0 OR NOT EXISTS (SELECT 1 FROM dbo.doctor_branches x WHERE x.doctor_id = d.id AND x.is_primary = 1 AND x.is_active = 1));

/* doctor <-> service: a doctor offers every service of his/her specialty */
INSERT INTO dbo.doctor_services (id, provider_id, doctor_id, service_id, fee_override, duration_override_minutes, is_active, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|doctor_service|', d.id, N'|', s.id)), 1, 16) AS uniqueidentifier),
       d.provider_id, d.id, s.id, NULL, NULL, 1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #doc d
JOIN #svc s ON s.tenant_key = d.tenant_key AND s.spec_code = d.spec_code
WHERE NOT EXISTS (SELECT 1 FROM dbo.doctor_services x WHERE x.doctor_id = d.id AND x.service_id = s.id);

/* ---------- weekly working hours ---------- */
INSERT INTO dbo.doctor_working_hours (id, provider_id, doctor_id, branch_id, day_of_week, start_time, end_time,
                                      slot_duration_minutes, is_active, created_at, updated_at)
SELECT CAST(SUBSTRING(HASHBYTES('SHA1', CONCAT(N'seed|working_hours|', d.id, N'|', b.id, N'|', dd.dow, N'|', h.start_time)), 1, 16) AS uniqueidentifier),
       d.provider_id, d.id, b.id, dd.dow, h.start_time, h.end_time, h.slot_minutes, 1, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM #hours h
JOIN #doc d    ON d.doc_key = h.doc_key
JOIN #branch b ON b.tenant_key = d.tenant_key AND b.code = h.branch_code
CROSS APPLY (SELECT CAST(LTRIM(RTRIM(value)) AS int) AS dow FROM STRING_SPLIT(h.days, ',')) dd
WHERE NOT EXISTS (SELECT 1 FROM dbo.doctor_working_hours x
                  WHERE x.doctor_id = d.id AND x.branch_id = b.id AND x.day_of_week = dd.dow AND x.start_time = h.start_time);

/* ---------- availability slots (same rules as the app's slot generator) ---------- */
DECLARE @today date = CAST(SYSUTCDATETIME() AS date);

;WITH n AS (
    SELECT TOP (@slot_days) CAST(ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS int) AS i FROM sys.all_objects
), days AS (
    SELECT DATEADD(day, n.i, @today) AS slot_date FROM n
), k AS (
    SELECT TOP (96) CAST(ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS int) AS j FROM sys.all_objects
)
INSERT INTO dbo.doctor_availability_slots (id, provider_id, doctor_id, branch_id, working_hours_id, slot_date, start_time, end_time,
                                           status, hold_expires_at, hold_reference, is_waitlist_fill, created_at, updated_at)
SELECT NEWID(), w.provider_id, w.doctor_id, w.branch_id, w.id, d.slot_date,
       DATEADD(minute, k.j * w.slot_duration_minutes, w.start_time),
       DATEADD(minute, (k.j + 1) * w.slot_duration_minutes, w.start_time),
       'available', NULL, NULL, 0, SYSDATETIMEOFFSET(), SYSDATETIMEOFFSET()
FROM dbo.doctor_working_hours w
JOIN #doc sd ON sd.id = w.doctor_id
CROSS JOIN days d
CROSS JOIN k
WHERE w.is_active = 1
  AND ((DATEPART(weekday, d.slot_date) + @@DATEFIRST - 2) % 7) = w.day_of_week
  AND DATEDIFF(minute, w.start_time, w.end_time) >= (k.j + 1) * w.slot_duration_minutes
  AND NOT EXISTS (SELECT 1 FROM dbo.doctor_availability_slots x
                  WHERE x.doctor_id = w.doctor_id AND x.slot_date = d.slot_date
                    AND x.start_time = DATEADD(minute, k.j * w.slot_duration_minutes, w.start_time));

/* ---------- summary (visible even on a dry run) ---------- */
PRINT N'--- Provider configuration summary (all providers) ---';
SELECT p.tenant_key, p.org_type,
       (SELECT COUNT(*) FROM dbo.branches b WHERE b.provider_id = p.id AND b.is_active = 1)                                   AS active_branches,
       (SELECT COUNT(*) FROM dbo.specialties s WHERE s.provider_id = p.id AND s.is_active = 1)                                AS active_specialties,
       (SELECT COUNT(*) FROM dbo.services s WHERE s.provider_id = p.id AND s.is_active = 1)                                   AS active_services,
       (SELECT COUNT(*) FROM dbo.doctors d WHERE d.provider_id = p.id AND d.is_active = 1)                                    AS active_doctors,
       (SELECT COUNT(*) FROM dbo.doctor_working_hours w WHERE w.provider_id = p.id AND w.is_active = 1)                       AS working_hour_rows,
       (SELECT COUNT(*) FROM dbo.doctor_availability_slots s WHERE s.provider_id = p.id AND s.status = 'available' AND s.slot_date >= @today) AS future_available_slots
FROM dbo.providers p
ORDER BY p.tenant_key;

IF @commit = 1
BEGIN
    COMMIT TRANSACTION;
    PRINT N'COMMITTED. Providers, catalog, hours and slots were saved.';
END
ELSE
BEGIN
    ROLLBACK TRANSACTION;
    PRINT N'DRY RUN: everything was rolled back. Set @commit = 1 to keep the data.';
END
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
SET NOEXEC OFF;
GO
