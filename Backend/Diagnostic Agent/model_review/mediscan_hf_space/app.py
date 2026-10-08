# ╔══════════════════════════════════════════════════════════════════╗
# ║   MediScan AI — Version 4.0  (Hugging Face Spaces build)        ║
# ║                                                                  ║
# ║  • 4 diseases: Brain MRI, Chest X-Ray, CT (COVID-19), Kidney CT  ║
# ║  • Grad-CAM heatmap on every diagnosis — shows what the AI saw   ║
# ║  • Guards against non-medical uploads (e.g. a photo of food)     ║
# ║  • Clearable session history                                     ║
# ║  • Chatbot: Groq (free) — auto-aware of the latest scan result  ║
# ║  • Disease sub-selection after scan type                         ║
# ║  • User-controlled Light/Dark mode, tucked into ⚙️ Settings      ║
# ║  • Patient Name / Age / Sex, upload OR camera capture            ║
# ║  • Confidence Breakdown bars + a donut-chart visualization       ║
# ║  • Mobile-responsive layout                                      ║
# ╚══════════════════════════════════════════════════════════════════╝


# ════════════════════════════════════════════════════════════════════
#  Hugging Face Spaces build
#  Dependencies are installed automatically from requirements.txt
#  (gradio, groq, numpy, tensorflow-cpu, pillow) — nothing to !pip install here.
# ════════════════════════════════════════════════════════════════════

import os
import io
import base64
import gradio as gr
from groq import Groq
import numpy as np
import cv2
import tensorflow as tf
from PIL import Image
from datetime import datetime

# EfficientNet preprocessing (used for all 4 models)
from tensorflow.keras.applications.efficientnet import preprocess_input as eff_preprocess

print("⏳ Loading models — takes 30–60 seconds...")

# ── Model files must be uploaded to the SAME folder as this app.py ──────────
mri_model    = tf.keras.models.load_model('best_brain_tumor_model.keras')
xray_model   = tf.keras.models.load_model('x-ray.keras')
ct_model     = tf.keras.models.load_model('Covid_19.keras')
kidney_model = tf.keras.models.load_model('kidney_efficientnetb0_final.keras')
# ─────────────────────────────────────────────────────────────────────────────

print("✅ All 4 models loaded!")
print(f"   MRI    input: {mri_model.input_shape}    output: {mri_model.output_shape}")
print(f"   X-Ray  input: {xray_model.input_shape}   output: {xray_model.output_shape}")
print(f"   CT     input: {ct_model.input_shape}     output: {ct_model.output_shape}")
print(f"   Kidney input: {kidney_model.input_shape} output: {kidney_model.output_shape}")

# ── Groq API key for chatbot ──────────────────────────────────────────────────
# On Hugging Face: go to your Space → Settings → "Variables and secrets"
# → New secret → Name: GROQ_API_KEY, Value: your key from console.groq.com (free)
GROQ_KEY     = os.environ.get('GROQ_API_KEY', '')
CHAT_ENABLED = bool(GROQ_KEY)
if CHAT_ENABLED:
    print("✅ Groq chatbot key found!")
else:
    print("⚠️  Groq key not found — chatbot will show setup instructions.")

# ── Supabase (accounts + persistent history) ──────────────────────────────────
# On Hugging Face: Settings → "Variables and secrets" → add:
#   SUPABASE_URL  = https://xxxxx.supabase.co        (Project Settings → API)
#   SUPABASE_KEY  = your "anon public" key            (Project Settings → API)
# ⚠️  Also go to Authentication → Providers → Email and turn OFF "Confirm email",
#     otherwise sign-ups won't be able to log in until they click an email link.
from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
DB_ENABLED   = bool(SUPABASE_URL and SUPABASE_KEY)

sb = None
if DB_ENABLED:
    try:
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Supabase connected — accounts & persistent history enabled!")
    except Exception as e:
        DB_ENABLED = False
        print(f"⚠️  Supabase connection failed ({e}) — accounts will show setup instructions.")
else:
    print("⚠️  Supabase not configured — accounts will show setup instructions.")

# Optional — only needed for the "🗑️ Delete My Account" feature. This is the
# NEW-style "Secret key" (sb_secret_...) from Supabase's API Keys page (NOT
# the Publishable key, which can't delete auth users on its own). This is
# safe to use here specifically because it's used server-side in this
# Python code, never sent to a browser.
SUPABASE_SECRET_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')
sb_admin = None
if DB_ENABLED and SUPABASE_SECRET_KEY:
    try:
        sb_admin = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
        print("✅ Account deletion enabled.")
    except Exception as e:
        print(f"⚠️  Admin client failed ({e}) — account deletion will be disabled.")
else:
    print("ℹ️  SUPABASE_SECRET_KEY not set — 'Delete My Account' will show a setup message.")


# ── Account & data helpers ──────────────────────────────────────────────────
# Every function returns (result, error_message) or a plain list — never
# raises — so the UI layer can always show a friendly message instead of
# crashing on a network hiccup or a misconfigured Space.

def db_sign_up(email, password, full_name, role):
    """Creates an auth user + a matching profile row. Returns (session, error)."""
    if not DB_ENABLED:
        return None, "Accounts aren't set up on this Space yet (missing SUPABASE_URL/SUPABASE_KEY)."
    email, full_name = (email or '').strip(), (full_name or '').strip()
    if not email or not password or not full_name:
        return None, "Please fill in your name, email, and password."
    try:
        res = sb.auth.sign_up({"email": email, "password": password})
        if not res.user:
            return None, "Sign up failed. The email may already be registered."
        uid = res.user.id
        sb.table('profiles').upsert({
            'id': uid, 'full_name': full_name, 'role': role
        }).execute()
        return {'user_id': uid, 'email': email, 'role': role, 'name': full_name}, None
    except Exception as e:
        return None, f"Sign up error: {e}"


def db_sign_in(email, password):
    """Returns (session, error)."""
    if not DB_ENABLED:
        return None, "Accounts aren't set up on this Space yet (missing SUPABASE_URL/SUPABASE_KEY)."
    try:
        res = sb.auth.sign_in_with_password({"email": (email or '').strip(), "password": password})
        if not res.user:
            return None, "Incorrect email or password."
        uid = res.user.id
        prof = sb.table('profiles').select('*').eq('id', uid).execute()
        rows = prof.data or []
        if not rows:
            # Self-healing: profile row missing (e.g. an interrupted signup) — create it now
            sb.table('profiles').insert({'id': uid, 'full_name': email, 'role': 'patient'}).execute()
            role, name = 'patient', email
        else:
            role = rows[0].get('role', 'patient')
            name = rows[0].get('full_name', email)
        return {'user_id': uid, 'email': email, 'role': role, 'name': name}, None
    except Exception as e:
        return None, f"Sign in error: {e}"


def db_add_patient(doctor_id, full_name, age, sex, email, notes):
    try:
        sb.table('patients').insert({
            'doctor_id': doctor_id, 'full_name': (full_name or '').strip(),
            'age': int(age) if age else None, 'sex': sex,
            'email': (email or '').strip() or None, 'notes': notes or '',
        }).execute()
        return True, None
    except Exception as e:
        return False, str(e)


def db_list_patients(doctor_id):
    try:
        res = sb.table('patients').select('*').eq('doctor_id', doctor_id).order('created_at', desc=True).execute()
        return res.data or []
    except Exception:
        return []


def db_update_patient_notes(patient_id, notes):
    try:
        sb.table('patients').update({'notes': notes}).eq('id', patient_id).execute()
        return True
    except Exception:
        return False


def db_save_scan(created_by, patient_id, scan_type, diagnosis, confidence, severity):
    try:
        sb.table('scans').insert({
            'created_by': created_by, 'patient_id': patient_id,
            'scan_type': scan_type, 'diagnosis': diagnosis,
            'confidence': float(confidence), 'severity': severity,
        }).execute()
        return True
    except Exception:
        return False


def db_get_scans_for_patient(patient_id):
    try:
        res = sb.table('scans').select('*').eq('patient_id', patient_id).order('created_at', desc=True).execute()
        return res.data or []
    except Exception:
        return []


def db_get_scans_by_creator(user_id):
    """A doctor/researcher's own logged scans, regardless of patient."""
    try:
        res = sb.table('scans').select('*').eq('created_by', user_id).order('created_at', desc=True).execute()
        return res.data or []
    except Exception:
        return []


def db_get_scans_for_patient_email(email):
    """Used by a PATIENT account to see their own history, linked via the
    email their doctor entered when creating their patient profile."""
    try:
        pts = sb.table('patients').select('id').eq('email', (email or '').strip()).execute()
        ids = [p['id'] for p in (pts.data or [])]
        if not ids:
            return []
        res = sb.table('scans').select('*').in_('patient_id', ids).order('created_at', desc=True).execute()
        return res.data or []
    except Exception:
        return []


def db_get_scans_for_patient_role(user_id, email):
    """A Patient's own history = scans they ran themselves, PLUS any scans a
    doctor logged under a patient profile that matches their email. Done as
    two simple queries + a Python merge rather than a single OR-filter query,
    since Postgrest's OR-filter string syntax is easy to get subtly wrong."""
    own = []
    try:
        res = sb.table('scans').select('*').eq('created_by', user_id).order('created_at', desc=True).execute()
        own = res.data or []
    except Exception:
        pass
    linked = db_get_scans_for_patient_email(email)
    seen, merged = set(), []
    for row in own + linked:
        rid = row.get('id')
        if rid not in seen:
            seen.add(rid)
            merged.append(row)
    merged.sort(key=lambda r: r.get('created_at') or '', reverse=True)
    return merged


def db_delete_account(user_id):
    """Permanently deletes the auth user. The schema's ON DELETE CASCADE /
    SET NULL foreign keys take care of cleaning up their profile, their
    patients (if a doctor), and their scans automatically — no need to
    manually delete from each table first."""
    if not sb_admin:
        return False, "Account deletion isn't set up on this Space yet (missing SUPABASE_SECRET_KEY)."
    try:
        sb_admin.auth.admin.delete_user(user_id)
        return True, None
    except Exception as e:
        return False, str(e)


# ════════════════════════════════════════════════════════════════════
#  CELL 3 — Configuration, Prediction Functions, Chatbot
# ════════════════════════════════════════════════════════════════════

# ── Class labels for MRI (4-class softmax, alphabetical folder order) ────────
MRI_CLASSES = ['Glioma', 'Meningioma', 'No Tumor', 'Pituitary Tumor']
# glioma=0, meningioma=1, notumor=2, pituitary=3

# ── Class labels for Kidney CT (4-class softmax) — from kidney_class_indices.json
KIDNEY_CLASSES = ['Cyst', 'Normal', 'Stone', 'Tumor']
# Cyst=0, Normal=1, Stone=2, Tumor=3

# ── X-Ray: binary sigmoid. Alphabetical: NORMAL=0, PNEUMONIA=1 ───────────────
# output > 0.5 → Pneumonia (label 1), output ≤ 0.5 → Normal (label 0)

# ── CT: binary sigmoid. Alphabetical order of YOUR training folders ───────────
# ⚠️  IMPORTANT: test with a real COVID CT image first.
#     If it says "Normal" when it should say "COVID-19", change this to True:
CT_FLIP = False

# ── Medical insights database ────────────────────────────────────────────────
INSIGHTS = {
    'Glioma': {
        'color': '#b71c1c', 'bg': '#ffebee', 'severity': '🔴 High', 'icon': '⚠️',
        'about': 'Glioma is a brain tumor that starts in glial cells. It can be slow-growing or aggressive depending on grade.',
        'action': 'Seek immediate consultation with a neuro-oncologist. Further imaging and biopsy are needed to determine the grade and treatment plan.',
    },
    'Meningioma': {
        'color': '#e65100', 'bg': '#fff3e0', 'severity': '🟡 Medium', 'icon': '⚠️',
        'about': 'Meningioma is a tumor of the brain\'s protective membrane. Most are benign (non-cancerous) and slow-growing.',
        'action': 'Consult a neurosurgeon. Many meningiomas are managed with regular MRI monitoring without immediate surgery.',
    },
    'No Tumor': {
        'color': '#1b5e20', 'bg': '#e8f5e9', 'severity': '🟢 None', 'icon': '✅',
        'about': 'No brain tumor was detected in the MRI scan. Results appear within normal limits.',
        'action': 'Results appear normal. If neurological symptoms persist, consult a neurologist for a clinical evaluation.',
    },
    'Pituitary Tumor': {
        'color': '#e65100', 'bg': '#fff3e0', 'severity': '🟡 Medium', 'icon': '⚠️',
        'about': 'A pituitary adenoma was detected. The vast majority are benign and non-cancerous.',
        'action': 'Consult an endocrinologist for hormone evaluation. An eye exam may be needed to check for visual field changes.',
    },
    'Pneumonia': {
        'color': '#b71c1c', 'bg': '#ffebee', 'severity': '🔴 High', 'icon': '🚨',
        'about': 'Signs consistent with pneumonia were detected. Pneumonia is a lung infection that inflames the air sacs.',
        'action': 'Seek medical attention promptly. A doctor will decide between antibiotics (bacterial) or antivirals (viral). Rest and stay hydrated.',
    },
    'Normal': {
        'color': '#1b5e20', 'bg': '#e8f5e9', 'severity': '🟢 None', 'icon': '✅',
        'about': 'No significant abnormalities detected. Results appear within normal range.',
        'action': 'Results appear normal. If symptoms persist, consult a doctor for a full clinical evaluation.',
    },
    'COVID-19': {
        'color': '#b71c1c', 'bg': '#ffebee', 'severity': '🔴 High', 'icon': '🚨',
        'about': 'CT findings consistent with COVID-19 related lung changes (ground-glass opacities, bilateral infiltrates).',
        'action': 'Self-isolate immediately. Confirm with a PCR/antigen test. Contact your doctor. Monitor oxygen — seek emergency care if SpO₂ < 94%.',
    },
    'Cyst': {
        'color': '#e65100', 'bg': '#fff3e0', 'severity': '🟡 Medium', 'icon': '⚠️',
        'about': 'A renal cyst was detected — a fluid-filled sac in the kidney. Most simple cysts are benign and cause no symptoms.',
        'action': 'Consult a urologist or nephrologist. Simple cysts are usually just monitored periodically with follow-up imaging; complex cysts may need closer evaluation.',
    },
    'Stone': {
        'color': '#e65100', 'bg': '#fff3e0', 'severity': '🟡 Medium', 'icon': '⚠️',
        'about': 'A kidney stone (renal calculus) was detected — a hard mineral deposit that can cause pain or block urine flow.',
        'action': 'Consult a urologist. Treatment ranges from fluids and pain management for small stones to procedures like lithotripsy for larger ones.',
    },
    'Tumor': {
        'color': '#b71c1c', 'bg': '#ffebee', 'severity': '🔴 High', 'icon': '🚨',
        'about': 'A renal mass/tumor was detected. Further imaging is needed to determine whether it is benign or malignant.',
        'action': 'Seek prompt consultation with a urologist or oncologist. A contrast CT and possibly a biopsy will be needed to determine the nature and treatment plan.',
    },
}

# ── Disease options per scan type (shown after scan type is chosen).
#    CT now offers 2 pathways — this is what actually decides which model
#    runs, via each option's unique 'id'. ────────────────────────────────────
DISEASE_OPTIONS = {
    'MRI': [
        {
            'id': 'brain_tumor',
            'label': '🧠 Brain Tumor — checks for Glioma, Meningioma, Pituitary Tumor, or No Tumor',
            'title': '🧠 Brain Tumor Detection',
            'description': 'This model analyzes brain MRI scans and classifies them into 4 categories: <b>Glioma</b>, <b>Meningioma</b>, <b>Pituitary Tumor</b>, or <b>No Tumor</b>. Early detection of brain tumors significantly improves treatment outcomes.',
        },
    ],
    'X-Ray': [
        {
            'id': 'pneumonia',
            'label': '🫁 Pneumonia — checks for signs of lung infection in the chest X-Ray',
            'title': '🫁 Pneumonia Detection',
            'description': 'This model analyzes chest X-Ray images to detect signs of <b>Pneumonia</b>. Pneumonia is a lung infection that can be bacterial or viral. Prompt diagnosis is critical for effective treatment.',
        },
    ],
    'CT': [
        {
            'id': 'covid',
            'label': '🦠 COVID-19 — checks for COVID-19 related lung changes in the CT scan',
            'title': '🦠 COVID-19 Detection',
            'description': 'This model analyzes chest CT scans for signs of <b>COVID-19</b> related lung changes such as ground-glass opacities. CT scans are a valuable tool for assessing COVID-19 severity.',
        },
        {
            'id': 'kidney',
            'label': '🫘 Kidney Disease — checks for Cyst, Stone, Tumor, or Normal in the CT scan',
            'title': '🫘 Kidney Disease Detection',
            'description': 'This model analyzes kidney CT scans and classifies them into 4 categories: <b>Cyst</b>, <b>Stone</b>, <b>Tumor</b>, or <b>Normal</b>. Early detection of kidney abnormalities significantly improves treatment outcomes.',
        },
    ],
}

# Reverse lookup: disease dropdown label → internal id (used by analyze_scan
# to pick the right model — this is now driven by the DISEASE choice, not
# the scan type, since CT alone maps to 2 different models).
LABEL_TO_DISEASE_ID = {
    opt['label']: opt['id']
    for opts in DISEASE_OPTIONS.values()
    for opt in opts
}

# ── Expanded clinical reference content (Researcher + Doctor role only) ──────
# Written in general, educational terms — not a substitute for a radiology
# textbook or clinical guideline, but useful context beyond the patient-facing
# summary in INSIGHTS above.
CLINICAL_REFERENCE = {
    'brain_tumor': {
        'title': '🧠 Brain Tumors — Diagnostic Notes',
        'imaging': 'On MRI, gliomas typically appear as irregular, infiltrative masses with '
                    'variable enhancement depending on grade — high-grade gliomas often show '
                    'ring enhancement and surrounding edema. Meningiomas are usually well-circumscribed, '
                    'extra-axial masses with strong homogeneous enhancement and sometimes a '
                    '"dural tail" sign. Pituitary tumors are centered in the sella turcica and may '
                    'show suprasellar extension compressing the optic chiasm.',
        'differentials': 'Key differentials include metastasis, abscess, and demyelinating lesions '
                          'for glioma-like masses; for meningioma, differentials include schwannoma '
                          'and dural metastasis.',
        'diagnostic_workflow': 'Definitive diagnosis generally requires histopathology (biopsy or '
                                'resection) plus molecular markers (e.g. IDH mutation status, MGMT '
                                'methylation for gliomas) per current WHO CNS tumor classification.',
        'links': [
            ('RadiologyInfo.org — Brain Tumors (RSNA/ACR)', 'https://www.radiologyinfo.org/en/info/braintumor'),
            ('ASNR — Neuroradiology Patient Info: Brain Tumor', 'https://www.asnr.org/patientinfo/conditions/brain_tumor.shtml'),
        ],
    },
    'pneumonia': {
        'title': '🫁 Pneumonia — Diagnostic Notes',
        'imaging': 'Chest X-Ray findings suggestive of pneumonia include focal consolidation, '
                    'air-space opacity, and air bronchograms. Lobar consolidation is more typical '
                    'of bacterial pneumonia, while diffuse, bilateral interstitial patterns are '
                    'more typical of atypical/viral pneumonia.',
        'differentials': 'Differentials for a consolidative opacity include atelectasis, pulmonary '
                          'edema, pulmonary infarct, and malignancy — clinical correlation (fever, '
                          'cough, labs) is essential.',
        'diagnostic_workflow': 'Clinical diagnosis is usually supported by imaging plus labs '
                                '(CBC, CRP/procalcitonin) and, where available, sputum culture or '
                                'antigen testing to help distinguish bacterial vs. viral causes.',
        'links': [
            ('RadiologyInfo.org — Pneumonia (RSNA/ACR)', 'https://www.radiologyinfo.org/en/info/pneumonia'),
        ],
    },
    'covid': {
        'title': '🦠 COVID-19 — Diagnostic Notes',
        'imaging': 'Chest CT findings associated with COVID-19 pneumonia include bilateral, '
                    'peripheral, and basal-predominant ground-glass opacities, sometimes with a '
                    'rounded morphology or a "crazy-paving" pattern in more severe disease.',
        'differentials': 'Ground-glass opacities are non-specific and can also be seen in other '
                          'viral pneumonias, organizing pneumonia, and pulmonary edema — CT alone '
                          'cannot confirm COVID-19.',
        'diagnostic_workflow': 'PCR or antigen testing remains the reference standard for '
                                'diagnosis; CT is primarily used to assess extent/severity or when '
                                'testing is inconclusive, not as a standalone diagnostic tool.',
        'links': [
            ('WHO — COVID-19 Fact Sheet', 'https://www.who.int/news-room/fact-sheets/detail/coronavirus-disease-(covid-19)'),
            ('RadiologyInfo.org — COVID-19 Imaging Safety', 'https://www.radiologyinfo.org/en/info/safety-coronavirus'),
        ],
    },
    'kidney': {
        'title': '🫘 Kidney Disease — Diagnostic Notes',
        'imaging': 'On CT, simple renal cysts appear as well-defined, fluid-attenuation, '
                    'non-enhancing lesions (Bosniak I). Renal stones appear as hyperdense foci, '
                    'best characterized on non-contrast CT. Renal tumors (e.g. renal cell '
                    'carcinoma) typically appear as solid, enhancing masses that may distort the '
                    'renal contour.',
        'differentials': 'Complex cysts (Bosniak II–IV) need close follow-up as malignancy risk '
                          'rises with category. Angiomyolipoma is an important benign differential '
                          'for a solid renal mass due to its fat content.',
        'diagnostic_workflow': 'Multiphase contrast CT (or MRI) is typically used to characterize '
                                'an indeterminate renal mass; biopsy may be considered for masses '
                                'where imaging is inconclusive.',
        'links': [
            ('RadiologyInfo.org — Kidney Stones', 'https://www.radiologyinfo.org/en/info/stones-renal'),
            ('RadiologyInfo.org — Kidney (Renal) Cysts', 'https://www.radiologyinfo.org/en/info/renal-cyst'),
            ('Johns Hopkins Medicine — Kidney Cancer Diagnosis', 'https://www.hopkinsmedicine.org/health/conditions-and-diseases/kidney-cancer/kidney-cancer-diagnosis'),
        ],
    },
}

def make_clinical_reference_html(disease_id):
    ref = CLINICAL_REFERENCE.get(disease_id)
    if not ref:
        return ""
    links_html = "".join(
        f'<a href="{url}" target="_blank" rel="noopener noreferrer" style="display:inline-block;'
        f'margin:0.3rem 0.4rem 0 0;padding:0.4rem 0.8rem;border-radius:20px;background:var(--step-bg);'
        f'color:#1565c0;text-decoration:none;font-size:0.82rem;border:1px solid var(--border-col)">'
        f'🔗 {label}</a>'
        for label, url in ref.get('links', [])
    )
    return f"""
    <div class="ms-result-card" style="background:var(--bg-card);border:1px solid var(--border-col);
        border-radius:12px;padding:1.2rem 1.4rem;margin-bottom:1rem;font-family:Segoe UI,Arial,sans-serif;">
        <h3 style="margin:0 0 0.7rem;color:var(--text-main)">{ref['title']}</h3>
        <p style="margin:0 0 0.5rem;color:var(--text-main);font-size:0.9rem">
            <b>🩻 Imaging findings:</b> {ref['imaging']}
        </p>
        <p style="margin:0 0 0.5rem;color:var(--text-main);font-size:0.9rem">
            <b>🔍 Key differentials:</b> {ref['differentials']}
        </p>
        <p style="margin:0 0 0.8rem;color:var(--text-main);font-size:0.9rem">
            <b>🧭 Diagnostic workflow:</b> {ref['diagnostic_workflow']}
        </p>
        <div>{links_html}</div>
    </div>"""

# ── Shared state (module-level — works for a single-user session) ────────────
current_scan = {'diagnosis': None, 'scan_type': None, 'confidence': None, 'patient': None, 'sex': None}
scan_history  = []


# ── Helper: convert PIL image to model-ready array ───────────────────────────
def prep_image(pil_img, target_size):
    """Resize, convert to RGB, expand dims. Returns raw 0–255 float32 array."""
    arr = np.array(pil_img.convert('RGB').resize(target_size), dtype=np.float32)
    return np.expand_dims(arr, axis=0)          # shape: (1, H, W, 3)


# ── Prediction functions (one per model) ──────────────────────────────────────
def _as_probabilities(raw):
    """
    Safety net: some exported .keras models return raw logits (any
    magnitude) instead of a proper softmax distribution, which is what
    caused confidences like '1090%' or '17802%'. If the values already
    look like a valid probability distribution (non-negative, sums to
    ~1) we use them as-is; otherwise we apply softmax ourselves.
    """
    raw = np.asarray(raw, dtype=np.float64)
    if raw.min() >= -1e-6 and abs(raw.sum() - 1.0) < 0.02:
        return np.clip(raw, 0.0, 1.0)
    shifted = raw - np.max(raw)
    exp = np.exp(shifted)
    return exp / exp.sum()


def _as_probability(raw):
    """Same idea as _as_probabilities but for a single sigmoid output."""
    raw = float(raw)
    if 0.0 <= raw <= 1.0:
        return raw
    return 1.0 / (1.0 + np.exp(-raw))


# ── Guard against non-medical uploads (e.g. a photo of a pizza) ───────────────
def looks_like_medical_scan(pil_img):
    """
    Heuristic: MRI/X-Ray/CT/Kidney-CT scans are essentially grayscale even
    when saved as an RGB file (R≈G≈B per pixel), and low in color
    saturation. Ordinary photos (food, selfies, screenshots...) are far
    more saturated. This isn't a perfect detector, but it reliably catches
    the "clearly not a medical scan" case.
    """
    arr = np.array(pil_img.convert('RGB'), dtype=np.int16)
    channel_spread = arr.max(axis=2) - arr.min(axis=2)   # 0 for true grayscale
    return float(channel_spread.mean()) < 18.0


# ── Grad-CAM — generic, works for any EfficientNet-backbone classifier ───────
def _find_backbone(model):
    """Locates the nested EfficientNet backbone layer inside a full model."""
    for i, layer in enumerate(model.layers):
        if 'efficientnet' in layer.name.lower():
            return layer, i
    return None, None


def compute_gradcam_heatmap(model, img_tensor, target_fn):
    """
    Generic Grad-CAM: finds the model's EfficientNet backbone, grabs its
    final feature map (this is what 'top_activation' already is for a
    backbone built with include_top=False, pooling=None — no need to dig
    for it by name), then REPLAYS whatever layers come before AND after
    the backbone (e.g. a built-in preprocessing/augmentation layer before
    it, GAP → BatchNorm → Dropout → Dense → ... after it) in their
    original order. Because it replays layers generically instead of
    hardcoding names, it works across MRI / X-Ray / CT / Kidney models
    even though each has its own head (and possibly its own pre-backbone
    block) instance. Replaying the pre-backbone layers with training=False
    is correctness hygiene (guards against any non-determinism in an
    augmentation block) — confirmed via inspecting the real model files
    that it is NOT, on its own, what causes the occasional imprecise
    localization on diffuse-pattern diseases (Pneumonia/COVID-19); the CT
    model has no pre-backbone block at all and still shows the same
    characteristic, which is consistent with published findings that
    Grad-CAM itself is inherently less precise on diffuse findings than on
    a single compact lesion (see: Salahuddin et al., "A review of
    explainable and interpretable AI with applications in COVID-19
    imaging," Medical Physics 2021 — Grad-CAM was shown to sometimes
    highlight clinically irrelevant regions for COVID-19 CT classifiers).

    Gradients are ReLU'd before channel-pooling ("positive-gradient"
    pooling): a location that would have DECREASED the predicted score no
    longer gets averaged in and allowed to cancel out real positive
    evidence elsewhere in the same channel. This captures most of the
    localization benefit Grad-CAM++ aims for — especially on diffuse,
    multi-region evidence — without needing Grad-CAM++'s second/third-order
    derivatives, which published critique (Lerma et al., "Grad-CAM++ is
    Equivalent to Grad-CAM With Positive Gradients") shows are often
    mathematically close to redundant in practice, at the cost of real
    numerical fragility (exponentials and third-order derivatives on a
    deep network are a good way to hit NaN/instability). Given the
    priority here is "don't break what's already working," this is the
    safer, well-grounded choice.

    `target_fn(preds) -> scalar tensor` lets the caller pick exactly what
    quantity to explain (e.g. the winning softmax class, or "evidence for
    the Normal class" for a binary model whose predicted class is Normal).
    Returns a normalized 0–1 heatmap array, or None if anything about the
    model's structure doesn't match what's expected (fails safe).
    """
    try:
        backbone, idx = _find_backbone(model)
        if backbone is None:
            return None
        pre_layers  = model.layers[1:idx]      # skip the InputLayer itself; replay anything
                                                  # between it and the backbone (e.g. built-in
                                                  # preprocessing) so the backbone sees exactly
                                                  # what it would during a real predict() call
        head_layers = model.layers[idx + 1:]

        grad_model = tf.keras.models.Model(inputs=backbone.input, outputs=backbone.output)

        with tf.GradientTape() as tape:
            x = img_tensor
            for layer in pre_layers:
                x = layer(x, training=False)
            conv_output = grad_model(x, training=False)
            x2 = conv_output
            for layer in head_layers:
                x2 = layer(x2, training=False)   # inference mode: matches .predict() exactly
                                                  # (BatchNorm uses stored stats, Dropout is a no-op)
            target = target_fn(x2)

        grads = tape.gradient(target, conv_output)
        if grads is None:
            return None

        # Positive-gradient pooling (see docstring above).
        positive_grads = tf.maximum(grads, 0.0)
        pooled_grads = tf.reduce_mean(positive_grads, axis=(0, 1, 2))
        conv_output_0 = conv_output[0]
        heatmap = conv_output_0 @ pooled_grads[..., tf.newaxis]
        heatmap = tf.squeeze(heatmap)
        heatmap = tf.maximum(heatmap, 0) / (tf.math.reduce_max(heatmap) + 1e-10)
        return heatmap.numpy()
    except Exception:
        # Grad-CAM is a bonus visualization — never let it break a diagnosis.
        return None


def compute_gradcam_plusplus_heatmap(model, img_tensor, target_fn):
    """
    Grad-CAM++ (Chattopadhyay et al., 2018) — weights each spatial location
    using 2nd/3rd-order derivatives instead of one global average, which
    generally gives tighter localization on diffuse/multi-region evidence
    (exactly the Pneumonia/COVID case). Algorithm adapted from the verified,
    working reference implementation at
    github.com/samson6460/tf_keras_gradcamplusplus (Apache-2.0 licensed;
    cites the original paper), restructured to use this app's generic
    pre/post-layer-replay technique instead of the reference's simpler
    `model.get_layer(name).output` (which doesn't work here — our backbone
    is a NESTED sub-model, the same Keras 3 quirk documented in
    compute_gradcam_heatmap above).

    Third-order derivatives on a deep network are numerically delicate —
    a near-zero denominator can blow up into a huge or NaN value. Every
    division below is guarded, the raw map is checked for non-finite
    values, and outliers are percentile-clipped BEFORE normalizing so one
    bad pixel can't crush the rest of the map to invisible. If anything
    still looks unsafe (non-finite, degenerate all-zero, etc.), this
    returns None — the caller then automatically falls back to the plain
    Grad-CAM above rather than showing a broken or misleading image.
    """
    try:
        backbone, idx = _find_backbone(model)
        if backbone is None:
            return None
        pre_layers  = model.layers[1:idx]
        head_layers = model.layers[idx + 1:]

        grad_model = tf.keras.models.Model(inputs=backbone.input, outputs=backbone.output)

        def _forward():
            x = img_tensor
            for layer in pre_layers:
                x = layer(x, training=False)
            conv_out = grad_model(x, training=False)
            x2 = conv_out
            for layer in head_layers:
                x2 = layer(x2, training=False)
            return conv_out, target_fn(x2)

        with tf.GradientTape() as tape1:
            with tf.GradientTape() as tape2:
                with tf.GradientTape() as tape3:
                    conv_output, target = _forward()
                first_grad = tape3.gradient(target, conv_output)
            second_grad = tape2.gradient(first_grad, conv_output)
        third_grad = tape1.gradient(second_grad, conv_output)

        if first_grad is None or second_grad is None or third_grad is None:
            return None

        conv_output_0 = conv_output[0]
        first_grad_0  = first_grad[0]
        second_grad_0 = second_grad[0]
        third_grad_0  = third_grad[0]

        # α_ij^k = D2 / (2·D2 + Σ_ab[A_ab^k · D3])  — per the published formula
        global_sum = tf.reduce_sum(conv_output_0, axis=(0, 1))   # Σ_ab A_ab^k, shape (C,)

        alpha_denom = second_grad_0 * 2.0 + third_grad_0 * global_sum
        safe_denom  = tf.where(tf.abs(alpha_denom) > 1e-8, alpha_denom, tf.ones_like(alpha_denom) * 1e-8)
        alphas = second_grad_0 / safe_denom

        # Normalize alphas to sum to 1 per channel (part of the published algorithm)
        alpha_sum  = tf.reduce_sum(alphas, axis=(0, 1))
        safe_sum   = tf.where(tf.abs(alpha_sum) > 1e-8, alpha_sum, tf.ones_like(alpha_sum) * 1e-8)
        alphas = alphas / safe_sum

        # w_k^c = Σ_ij α_ij^k · ReLU(∂y/∂A_ij^k)
        positive_grads   = tf.maximum(first_grad_0, 0.0)
        channel_weights  = tf.reduce_sum(positive_grads * alphas, axis=(0, 1))   # (C,)

        # L^c = ReLU(Σ_k w_k^c · A^k)
        cam = tf.reduce_sum(channel_weights * conv_output_0, axis=-1)
        cam = tf.maximum(cam, 0)
        cam_np = cam.numpy()

        # ── Safety net: never let a numerically unstable pixel produce a
        # broken or misleading heatmap. ──────────────────────────────────
        if not np.isfinite(cam_np).any():
            return None
        cam_np = np.where(np.isfinite(cam_np), cam_np, 0.0)
        if cam_np.max() <= 0:
            return None
        p995 = np.percentile(cam_np, 99.5)
        if p995 > 0:
            cam_np = np.clip(cam_np, 0, p995)
        max_val = cam_np.max()
        if max_val < 1e-10:
            return None
        return cam_np / max_val
    except Exception:
        return None


def _hot_region_overlaps_background(heatmap, pil_img, target_size, hot_value=0.6, dark_threshold=20, min_hot_pixels=10):
    """
    Sanity check: does the hottest part of this heatmap actually sit on
    real tissue, or is it sitting on the black background outside the
    patient's body / outside the scan field? A genuine finding should be
    on visible anatomy. `heatmap` is assumed already normalized to 0..1
    (true for both Grad-CAM functions above) — using an absolute
    threshold on that known scale, rather than a percentile rank, matters
    here: Grad-CAM's normal output is a small, concentrated hot blob
    against a mostly-cold background, and a percentile rank breaks badly
    on exactly that shape (tested and confirmed before shipping this).
    Returns True if the heatmap looks like a background artifact and
    should be rejected.
    """
    try:
        gray = np.array(pil_img.convert('L').resize(target_size), dtype=np.float32)
        heatmap_resized = cv2.resize(heatmap, target_size)
        hot_mask = heatmap_resized >= hot_value
        if hot_mask.sum() < min_hot_pixels:
            return False   # too little "hot" area to judge confidently either way
        return float(gray[hot_mask].mean()) < dark_threshold
    except Exception:
        return False   # if the check itself fails, don't block a heatmap over it


def _hot_region_near_border(heatmap, target_size, hot_value=0.6, border_frac=0.10, min_hot_pixels=10):
    """
    A second, different safeguard: checks whether the hot region's
    WEIGHTED CENTER sits within the outer border margin of the image
    (10% of width/height from any edge, by default). This catches
    equipment sitting at the frame edge — ECG leads, gown snaps, ID
    markers — that the darkness check above can't catch, because a
    metal/plastic marker is usually BRIGHT on an X-ray/CT, not dark, so
    it wouldn't trip a "sitting on background" check at all.
    Returns True if the hot region is centered near the border and
    should be rejected.
    """
    try:
        heatmap_resized = cv2.resize(heatmap, target_size)
        H, W = heatmap_resized.shape
        hot_mask = heatmap_resized >= hot_value
        if hot_mask.sum() < min_hot_pixels:
            return False
        ys, xs = np.nonzero(hot_mask)
        weights = heatmap_resized[hot_mask]
        cy = np.average(ys, weights=weights)
        cx = np.average(xs, weights=weights)
        my, mx = border_frac * H, border_frac * W
        return bool(cy < my or cy > H - my or cx < mx or cx > W - mx)
    except Exception:
        return False


def compute_best_gradcam(model, img_tensor, target_fn, pil_img, cam_size):
    """
    Primary technique is the plain positive-gradient Grad-CAM — NOT
    Grad-CAM++. This was a deliberate reversal after real-world testing:
    Grad-CAM++'s extra 2nd/3rd-order-derivative divisions make it MORE
    exposed (not less) to a well-documented failure mode where near-zero
    activations (e.g. the black background outside a patient's body)
    produce near-zero denominators, and therefore huge or spurious
    weights — see Sattarzadeh et al., "Visual Explanations from Deep
    Networks via Riemann-Stieltjes Integrated Gradient-based
    Localization," which found Grad-CAM-family methods "particularly
    sensitive" to exactly this.

    Whatever heatmap comes out is then checked against TWO different
    safeguards — sitting on black background, OR sitting on/near the
    image border (which catches equipment like ECG leads sitting at the
    frame edge, a well-documented shortcut-learning risk specifically in
    chest X-ray pneumonia classifiers). If EITHER check fails, this
    returns (None, None) — no heatmap is shown at all for that image,
    rather than a misleading one.
    """
    heatmap = compute_gradcam_heatmap(model, img_tensor, target_fn)
    if (heatmap is not None
            and not _hot_region_overlaps_background(heatmap, pil_img, cam_size)
            and not _hot_region_near_border(heatmap, cam_size)):
        return heatmap, "Grad-CAM"
    return None, None


def _sharpen_heatmap(heatmap, percentile=60):
    """
    Suppresses low-activation regions instead of stretching the colormap
    across the full 0–1 range relative to just the single hottest pixel.
    Without this, a disease with diffuse, spread-out evidence (e.g.
    pneumonia/COVID lung changes, vs. a single compact lesion like a
    tumor or stone) ends up with weakly-activated regions still showing
    as visible yellow/orange under JET, making the overlay look noisier
    and less confident than the actual strongest evidence warrants.
    """
    threshold = np.percentile(heatmap, percentile)
    denom = heatmap.max() - threshold
    if denom < 1e-6:
        return heatmap
    return np.clip((heatmap - threshold) / denom, 0, 1)


def make_gradcam_overlay(pil_img, heatmap, target_size):
    """Resizes the heatmap, colors it, and blends it over a contrast-enhanced scan."""
    img_resized = pil_img.convert('RGB').resize(target_size)
    img_arr = np.array(img_resized, dtype=np.uint8)

    heatmap_resized = cv2.resize(heatmap, target_size)
    heatmap_resized = _sharpen_heatmap(heatmap_resized)
    heatmap_uint8   = np.uint8(255 * np.clip(heatmap_resized, 0, 1))
    heatmap_color   = cv2.applyColorMap(heatmap_uint8, cv2.COLORMAP_JET)
    heatmap_color   = cv2.cvtColor(heatmap_color, cv2.COLOR_BGR2RGB)

    # CLAHE contrast boost on the base image so anatomy stays visible under the overlay
    lab = cv2.cvtColor(img_arr, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    img_enhanced = cv2.cvtColor(cv2.merge((clahe.apply(l), a, b)), cv2.COLOR_LAB2RGB)

    # Fade the heatmap where it's weak so only genuinely strong regions are
    # visually loud — alpha itself follows the (sharpened) heatmap strength.
    alpha = (0.5 * heatmap_resized)[..., None]
    overlay = (img_enhanced.astype(np.float32) * (1 - alpha)
               + heatmap_color.astype(np.float32) * alpha).astype(np.uint8)
    return Image.fromarray(overlay)



def make_gradcam_card(overlay_img, method="Grad-CAM"):
    buf = io.BytesIO()
    overlay_img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    badge = (
        '<span style="font-size:0.7rem;font-weight:600;color:#1565c0;'
        'background:var(--step-bg);border-radius:10px;padding:0.15rem 0.55rem;margin-left:0.4rem">'
        f'{method}</span>'
    )
    return f"""
    <div class="ms-chart-card">
        <p style="text-align:center;font-weight:600;margin:0 0 0.6rem;color:var(--text-main)">
            🔥 Where the AI Focused {badge}
        </p>
        <img src="data:image/png;base64,{b64}" style="max-width:100%;border-radius:10px;display:block;margin:0 auto" />
        <p style="text-align:center;font-size:0.78rem;color:var(--text-main);opacity:0.7;margin:0.6rem 0 0">
            Warmer colors (red/yellow) mark the regions that most influenced this diagnosis.
        </p>
    </div>"""


def predict_mri(pil_img):
    """MRI: EfficientNetB0, 224×224, 4-class softmax → argmax."""
    arr   = prep_image(pil_img, (224, 224))
    arr   = eff_preprocess(arr)                  # EfficientNetB0 preprocessing
    preds = _as_probabilities(mri_model.predict(arr, verbose=0)[0])  # shape: (4,)
    idx   = int(np.argmax(preds))
    cls   = MRI_CLASSES[idx]
    conf  = float(preds[idx]) * 100
    probs = {MRI_CLASSES[i]: float(preds[i]) * 100 for i in range(4)}
    target_fn = lambda p: p[:, idx]               # Grad-CAM explains the winning class
    return cls, conf, probs, target_fn, arr

def predict_xray(pil_img):
    """
    X-Ray: EfficientNetB3, 384×384, BINARY sigmoid output (1 neuron).
    The model has built-in preprocessing — pass raw 0–255 pixels.
    Alphabetical training folders: NORMAL=0, PNEUMONIA=1
    → output > 0.5 means Pneumonia
    """
    arr  = prep_image(pil_img, (384, 384))       # correct size for EfficientNetB3
    pred = _as_probability(xray_model.predict(arr, verbose=0)[0][0])  # single sigmoid value

    pneumonia_prob = pred * 100
    normal_prob    = (1 - pred) * 100

    if pred > 0.5:
        cls, conf = 'Pneumonia', pneumonia_prob
        target_fn = lambda p: p[:, 0]             # explain "more Pneumonia evidence"
    else:
        cls, conf = 'Normal', normal_prob
        target_fn = lambda p: 1.0 - p[:, 0]        # explain "more Normal evidence"

    probs = {'Pneumonia': pneumonia_prob, 'Normal': normal_prob}
    return cls, conf, probs, target_fn, arr

def predict_ct(pil_img):
    """
    CT: EfficientNetB4, 380×380, BINARY sigmoid output (1 neuron).
    The model has built-in preprocessing — pass raw 0–255 pixels.

    ⚠️  Class order depends on YOUR training folder names (alphabetical).
        If COVID folder name < Normal folder name alphabetically:
            COVID=0, Normal=1  → output > 0.5 means Normal → CT_FLIP = False (default)
        If Normal comes first alphabetically:
            Normal=0, COVID=1  → output > 0.5 means COVID  → CT_FLIP = True

    Test with a KNOWN COVID CT image. If result is wrong, flip CT_FLIP above.
    """
    arr  = prep_image(pil_img, (380, 380))       # correct size for EfficientNetB4
    pred = _as_probability(ct_model.predict(arr, verbose=0)[0][0])

    if CT_FLIP:
        covid_prob  = pred * 100           # COVID labeled as 1 in training
        normal_prob = (1 - pred) * 100
        covid_target_fn  = lambda p: p[:, 0]
        normal_target_fn = lambda p: 1.0 - p[:, 0]
    else:
        covid_prob  = (1 - pred) * 100     # COVID labeled as 0 in training (alphabetically first)
        normal_prob = pred * 100
        covid_target_fn  = lambda p: 1.0 - p[:, 0]
        normal_target_fn = lambda p: p[:, 0]

    if covid_prob > 50:
        cls, conf, target_fn = 'COVID-19', covid_prob, covid_target_fn
    else:
        cls, conf, target_fn = 'Normal', normal_prob, normal_target_fn

    probs = {'COVID-19': covid_prob, 'Normal': normal_prob}
    return cls, conf, probs, target_fn, arr


def predict_kidney(pil_img):
    """Kidney CT: EfficientNetB0, 224×224, 4-class softmax → argmax."""
    arr   = prep_image(pil_img, (224, 224))
    arr   = eff_preprocess(arr)                  # EfficientNetB0 preprocessing
    preds = _as_probabilities(kidney_model.predict(arr, verbose=0)[0])  # shape: (4,)
    idx   = int(np.argmax(preds))
    cls   = KIDNEY_CLASSES[idx]
    conf  = float(preds[idx]) * 100
    probs = {KIDNEY_CLASSES[i]: float(preds[i]) * 100 for i in range(4)}
    target_fn = lambda p: p[:, idx]
    return cls, conf, probs, target_fn, arr


# ── Confidence donut chart (SVG, no extra dependencies) ────────────────────────
def make_confidence_chart(probs, top_class):
    """
    Small donut chart visualizing the probability breakdown, placed next to
    the Confidence Breakdown bars. The winning diagnosis is colored by its
    severity (matching the result card); other classes are muted gray so
    the top result stands out at a glance.
    """
    items = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(v for _, v in items) or 1.0

    r, cx, cy, stroke = 70, 90, 90, 26
    circumference = 2 * 3.141592653589793 * r

    top_color     = INSIGHTS.get(top_class, {}).get('color', '#1565c0')
    muted_palette = ['#90a4ae', '#b0bec5', '#cfd8dc', '#78909c']

    arcs, offset = [], 0.0
    for i, (label, pct) in enumerate(items):
        frac   = pct / total
        length = frac * circumference
        color  = top_color if label == top_class else muted_palette[(i - 1) % len(muted_palette)]
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}"></circle>'
        )
        offset += length

    legend_rows = "".join(
        f'<div style="display:flex;align-items:center;gap:0.4rem;margin:0.18rem 0;font-size:0.82rem;color:var(--text-main)">'
        f'<span style="width:10px;height:10px;border-radius:50%;flex-shrink:0;'
        f'background:{top_color if label == top_class else muted_palette[(i - 1) % len(muted_palette)]}"></span>'
        f'<span style="flex:1">{label}</span><b>{pct:.1f}%</b></div>'
        for i, (label, pct) in enumerate(items)
    )

    top_pct = probs.get(top_class, 0)

    return f"""
    <div class="ms-chart-card">
        <div style="display:flex;align-items:center;gap:1.1rem;flex-wrap:wrap;justify-content:center">
            <svg viewBox="0 0 180 180" width="140" height="140" style="transform:rotate(-90deg);flex-shrink:0">
                {''.join(arcs)}
            </svg>
            <div style="min-width:140px;flex:1">{legend_rows}</div>
        </div>
        <p style="text-align:center;margin:0.5rem 0 0;font-size:0.85rem;color:var(--text-main)">
            Top result: <b style="color:{top_color}">{top_class}</b> — {top_pct:.1f}%
        </p>
    </div>"""


# ── Main analysis function (called by Analyze button) ─────────────────────────
def render_patient_result(info):
    """Simplified, jargon-free result for the Patient role — severity-level
    guidance only, no class names, confidence numbers, or Grad-CAM."""
    sev = info.get('severity', '')
    if 'High' in sev:
        headline, color, bg = "🔴 Please see a doctor promptly", '#b71c1c', '#ffebee'
        note = "This result suggests something that needs a doctor's attention soon. Please book an appointment."
    elif 'Medium' in sev:
        headline, color, bg = "🟡 Worth checking with your doctor", '#e65100', '#fff3e0'
        note = "This result is worth discussing with your doctor at your next opportunity — it doesn't look urgent."
    else:
        headline, color, bg = "🟢 Looks fine — no urgent action needed", '#1b5e20', '#e8f5e9'
        note = "Nothing concerning was found. If you still have symptoms, it's always okay to check in with your doctor."
    return f"""
    <div class="ms-result-card" style="border-left:5px solid {color};background:{bg};border-radius:12px;
        padding:1.6rem;font-family:Segoe UI,Arial,sans-serif;text-align:center">
        <h2 style="margin:0 0 0.6rem;color:{color}">{headline}</h2>
        <p style="margin:0;color:#333;font-size:0.95rem">{note}</p>
        <p style="margin-top:1rem;color:#888;font-size:0.8rem;font-style:italic">
            ⚠️ This is a simplified, AI-assisted summary — not a diagnosis. Your doctor can see your full results.
        </p>
    </div>"""


def analyze_scan(patient_name, patient_age, patient_sex, scan_choice, disease_choice, image,
                  session, assigned_patient_id):
    global current_scan, scan_history

    role = session.get('role') if session else 'guest'

    # Input validation
    if not patient_name or not patient_name.strip():
        return _warn("⚠️ Please enter the patient's name."), {}, "", "", _history_rows()
    if image is None:
        return _warn("⚠️ Please upload a scan image."), {}, "", "", _history_rows()

    try:
        pil_img = Image.fromarray(image)

        # Guard against non-medical uploads (e.g. a photo of a pizza)
        if not looks_like_medical_scan(pil_img):
            return _warn(
                "⚠️ This doesn't look like a medical scan. Please upload a proper "
                "<b>MRI, X-Ray, or CT</b> image — MediScan AI can only analyze "
                "grayscale-style medical imaging, not regular photos."
            ), {}, "", "", _history_rows()

        # Which model runs is decided by the DISEASE choice, not the scan
        # type alone — CT now covers 2 different pathways (COVID-19 / Kidney).
        disease_id = LABEL_TO_DISEASE_ID.get(disease_choice)

        if disease_id == 'brain_tumor':
            cls, conf, probs, target_fn, arr = predict_mri(pil_img)
            model_for_cam, cam_size = mri_model, (224, 224)
        elif disease_id == 'pneumonia':
            cls, conf, probs, target_fn, arr = predict_xray(pil_img)
            model_for_cam, cam_size = xray_model, (384, 384)
        elif disease_id == 'covid':
            cls, conf, probs, target_fn, arr = predict_ct(pil_img)
            model_for_cam, cam_size = ct_model, (380, 380)
        elif disease_id == 'kidney':
            cls, conf, probs, target_fn, arr = predict_kidney(pil_img)
            model_for_cam, cam_size = kidney_model, (224, 224)
        else:
            return _warn("⚠️ Please choose which disease to check for."), {}, "", "", _history_rows()

        info = INSIGHTS.get(cls, {})

        # Update shared state (chatbot uses this for context)
        current_scan.update({
            'diagnosis': cls, 'scan_type': scan_choice,
            'confidence': conf, 'patient': patient_name.strip(),
            'sex': patient_sex,
        })

        # Persist to Supabase for any logged-in role (skipped for Guest —
        # "nothing is saved" is the whole point of Guest mode).
        if session and DB_ENABLED and role != 'guest':
            db_save_scan(
                created_by=session['user_id'],
                patient_id=(assigned_patient_id or None),
                scan_type=scan_choice, diagnosis=cls,
                confidence=conf, severity=info.get('severity', ''),
            )

        # Also keep the local in-session list (used for Guest mode's table)
        scan_history.append({
            'time': datetime.now().strftime('%H:%M'),
            'name': patient_name.strip(), 'age': int(patient_age),
            'sex': patient_sex or '—',
            'scan': scan_choice, 'diagnosis': cls,
            'confidence': f'{conf:.1f}%'
        })

        # ── Patient role: simplified, jargon-free result only ────────────────
        if role == 'patient':
            return render_patient_result(info), {}, "", "", _history_rows()

        # ── Doctor / Researcher / Guest: full clinical detail ────────────────
        low_conf = ''
        if conf < 70:
            low_conf = (
                '<div style="background:#fff9c4;border:1px solid #f9a825;border-radius:8px;'
                'padding:0.7rem;margin-top:0.8rem;font-size:0.88rem;color:#5a4000">'
                '⚠️ <b>Low confidence ({:.1f}%).</b> The AI is uncertain. '
                'Please consult a doctor regardless of this result.</div>'
            ).format(conf)

        # Result HTML card
        result_html = f"""
        <div class="ms-result-card" style="
            border-left: 5px solid {info['color']};
            background: {info['bg']};
            border-radius: 12px;
            padding: 1.5rem;
            margin-top: 0.5rem;
            font-family: Segoe UI, Arial, sans-serif;
        ">
            <h2 style="margin:0; color:{info['color']}; font-size:1.8rem">
                {info['icon']} {cls}
            </h2>
            <p style="margin:0.5rem 0; color:#444; font-size:0.95rem">
                <b>Patient:</b> {patient_name.strip()} &nbsp;·&nbsp;
                <b>Age:</b> {int(patient_age)} &nbsp;·&nbsp;
                <b>Sex:</b> {patient_sex or '—'} &nbsp;·&nbsp;
                <b>Scan:</b> {scan_choice}
            </p>
            <p style="margin:0.2rem 0; font-size:0.95rem; color:#444">
                <b>AI Confidence:</b> {conf:.1f}% &nbsp;·&nbsp;
                <b>Severity:</b> {info['severity']}
            </p>
            <hr style="border:none;border-top:1px solid {info['color']}30;margin:0.9rem 0">
            <p style="margin:0.4rem 0; font-size:0.93rem; color:#333">
                <b>ℹ️ About this condition:</b><br>
                {info['about']}
            </p>
            <p style="margin:0.6rem 0 0; font-size:0.93rem; color:#333">
                <b>💡 Recommended action:</b><br>
                {info['action']}
            </p>
            {low_conf}
            <p style="margin-top:1rem; color:#888; font-size:0.8rem; font-style:italic">
                ⚠️ AI-assisted result for educational purposes only.
                Always consult a qualified medical professional for diagnosis and treatment.
            </p>
        </div>"""

        # gr.Label expects fractions (0–1) and multiplies by 100 itself to show
        # a percentage. Passing already-multiplied percentages here is exactly
        # what caused the "9895%" bug — so we convert back to fractions.
        probs_for_label = {k: v / 100.0 for k, v in probs.items()}
        chart_html = make_confidence_chart(probs, cls)

        # Plain (positive-gradient) Grad-CAM, with a background-overlap safety
        # check on top (see compute_best_gradcam) — either way, this never
        # breaks the diagnosis itself; worst case, no heatmap card is shown.
        gradcam_html = ""
        heatmap, gradcam_method = compute_best_gradcam(model_for_cam, arr, target_fn, pil_img, cam_size)
        if heatmap is not None:
            overlay_img = make_gradcam_overlay(pil_img, heatmap, cam_size)
            gradcam_html = make_gradcam_card(overlay_img, method=gradcam_method)

        return result_html, probs_for_label, chart_html, gradcam_html, _history_rows()

    except Exception as e:
        error_html = f"""
        <div class="ms-result-card" style="background:#ffebee;border-left:5px solid #c62828;border-radius:10px;padding:1.5rem">
            <h3 style="color:#c62828;margin:0">❌ Analysis Error</h3>
            <p style="margin:0.7rem 0; color:#333"><b>Error:</b> {str(e)}</p>
            <p style="color:#555">Common fixes:
            <ul>
                <li>Make sure all 4 model files loaded correctly (check the Space's logs)</li>
                <li>Try uploading a different image (JPG format works best)</li>
                <li>Make sure the image is not corrupted</li>
            </ul></p>
        </div>"""
        return error_html, {}, "", "", _history_rows()


# ── Disease info card (shown when user selects scan type or disease) ─────────
def _disease_info_card_html(opt):
    if not opt:
        return ""
    return f"""
    <div class="ms-result-card" style="
        background: #e8f0fe;
        border: 1px solid #1a73e8;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        font-family: Segoe UI, Arial, sans-serif;
    ">
        <h4 style="margin:0 0 0.4rem; color:#1a73e8">{opt.get('title','')}</h4>
        <p style="margin:0; color:#333; font-size:0.9rem">{opt.get('description','')}</p>
    </div>"""


def update_disease_section(scan_choice):
    """Updates the disease dropdown + info card when SCAN TYPE changes."""
    opts    = DISEASE_OPTIONS.get(scan_choice, [])
    choices = [o['label'] for o in opts]
    new_val = choices[0] if choices else None
    info_html = _disease_info_card_html(opts[0] if opts else None)
    return (
        gr.update(choices=choices, value=new_val),
        info_html
    )


def update_disease_info(scan_choice, disease_label):
    """Updates ONLY the info card when the DISEASE dropdown itself changes
    (matters for CT, which now offers 2 real choices — COVID-19 vs Kidney)."""
    opts = DISEASE_OPTIONS.get(scan_choice, [])
    match = next((o for o in opts if o['label'] == disease_label), None)
    return _disease_info_card_html(match)

def _warn(msg):
    return f'<div class="ms-result-card" style="background:#fff3cd;border:1px solid #f9a825;border-radius:8px;padding:1rem;font-family:Segoe UI,Arial,sans-serif;color:#5a4000">{msg}</div>'

def _history_rows():
    return [[r['time'], r['name'], r['age'], r.get('sex', '—'), r['scan'], r['diagnosis'], r['confidence']]
            for r in scan_history]

def clear_history():
    """Wipes the in-session scan history — wired to the 🗑️ Clear History button."""
    global scan_history
    scan_history.clear()
    return []


# ── Account system: UI-facing handlers ─────────────────────────────────────────
def _patient_choices(doctor_id):
    """(dropdown choices, raw patient list) for a doctor's patients — the
    dropdown value returned on selection is the patient's UUID directly."""
    patients = db_list_patients(doctor_id)
    choices = [("— No patient selected (just testing) —", "")]
    choices += [
        (f"{p.get('full_name','?')} (age {p.get('age') or '—'}, {p.get('sex') or '—'})", p['id'])
        for p in patients
    ]
    return choices, patients


def add_patient_handler(session, name, age, sex, email, notes):
    if not session or session.get('role') != 'doctor':
        return "⚠️ Only Doctor accounts can add patients.", gr.update(), gr.update()
    if not name or not name.strip():
        return "⚠️ Please enter the patient's name.", gr.update(), gr.update()
    ok, err = db_add_patient(session['user_id'], name, age, sex, email, notes)
    msg = f"✅ Added **{name.strip()}**." if ok else f"❌ Couldn't add patient: {err}"
    choices, _ = _patient_choices(session['user_id'])
    return msg, gr.update(choices=choices, value=""), gr.update(choices=choices, value="")


def refresh_patient_dropdown(session):
    if not session or session.get('role') != 'doctor':
        return gr.update(choices=[("— No patient selected (just testing) —", "")], value="")
    choices, _ = _patient_choices(session['user_id'])
    return gr.update(choices=choices)


def autofill_patient_fields(session, patient_id):
    """When a Doctor picks a patient in the Diagnose tab's assignment
    dropdown, fill Name/Age/Sex from that patient's saved profile instead
    of making them re-type info they already entered in 👤 My Patients.
    Leaving "No patient selected" picked keeps the fields as-is for a
    quick ad-hoc test."""
    if not session or session.get('role') != 'doctor' or not patient_id:
        return gr.update(), gr.update(), gr.update()
    patients = db_list_patients(session['user_id'])
    p = next((p for p in patients if p['id'] == patient_id), None)
    if not p:
        return gr.update(), gr.update(), gr.update()
    return (
        gr.update(value=p.get('full_name') or ''),
        gr.update(value=p.get('age') or 30),
        gr.update(value=p.get('sex') or 'Prefer not to say'),
    )


def show_patient_detail(session, patient_id):
    if not session or session.get('role') != 'doctor' or not patient_id:
        return "", "", []
    patients = db_list_patients(session['user_id'])
    p = next((p for p in patients if p['id'] == patient_id), None)
    if not p:
        return "", "", []
    detail_html = (
        '<div class="ms-result-card" style="background:var(--bg-card);border:1px solid var(--border-col);'
        'border-radius:10px;padding:1rem 1.2rem;color:var(--text-main)">'
        f'<b style="font-size:1.05rem">{p.get("full_name","?")}</b><br>'
        f'<span style="font-size:0.88rem;opacity:0.85">Age {p.get("age") or "—"} · {p.get("sex") or "—"}'
        f' · {p.get("email") or "No email on file"}</span></div>'
    )
    scans = db_get_scans_for_patient(patient_id)
    rows = [
        [(s.get('created_at') or '')[:16].replace('T', ' '), s.get('scan_type', ''),
         s.get('diagnosis', ''), f"{float(s.get('confidence', 0) or 0):.1f}%", s.get('severity', '')]
        for s in scans
    ]
    return detail_html, p.get('notes') or '', rows


def save_patient_notes_handler(patient_id, notes):
    if not patient_id:
        return "⚠️ Select a patient first."
    ok = db_update_patient_notes(patient_id, notes)
    return "✅ Notes saved." if ok else "❌ Couldn't save notes — try again."


def make_history_stats_html(rows, is_patient_view):
    """Small aggregate stats card shown above the DB-backed history table.
    Skipped for the Patient role — they get the simplified severity-only
    view elsewhere, so raw stats like 'diagnosis breakdown' don't belong
    here for them."""
    if not rows or is_patient_view:
        return ""
    total = len(rows)
    diagnoses = [r[2] for r in rows if r[2]]
    most_common = max(set(diagnoses), key=diagnoses.count) if diagnoses else '—'
    confidences = [float(str(r[3]).rstrip('%')) for r in rows if r[3]]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0
    high_count = sum(1 for r in rows if 'High' in str(r[4]))
    return f"""
    <div class="ms-chart-card" style="margin-bottom:1rem">
        <div style="display:flex;gap:1.8rem;flex-wrap:wrap;justify-content:center;text-align:center">
            <div><div style="font-size:1.6rem;font-weight:700;color:var(--text-main)">{total}</div>
                <div style="font-size:0.78rem;opacity:0.7;color:var(--text-main)">Total Scans</div></div>
            <div><div style="font-size:1.6rem;font-weight:700;color:var(--text-main)">{avg_conf:.1f}%</div>
                <div style="font-size:0.78rem;opacity:0.7;color:var(--text-main)">Avg. Confidence</div></div>
            <div><div style="font-size:1.3rem;font-weight:700;color:var(--text-main);margin-top:0.15rem">{most_common}</div>
                <div style="font-size:0.78rem;opacity:0.7;color:var(--text-main)">Most Common Result</div></div>
            <div><div style="font-size:1.6rem;font-weight:700;color:#c62828">{high_count}</div>
                <div style="font-size:0.78rem;opacity:0.7;color:var(--text-main)">High Severity</div></div>
        </div>
    </div>"""


def refresh_history_smart(session):
    """Role-aware history refresh for the 📋 History tab's DB-backed table.
    Returns (rows, stats_html)."""
    if not session or not DB_ENABLED or session.get('role') == 'guest':
        return [], ""
    role = session.get('role')
    if role == 'patient':
        scans = db_get_scans_for_patient_role(session['user_id'], session.get('email'))
    else:  # doctor or researcher — everything they've personally logged
        scans = db_get_scans_by_creator(session['user_id'])
    rows = [
        [(s.get('created_at') or '')[:16].replace('T', ' '), s.get('scan_type', ''),
         s.get('diagnosis', ''), f"{float(s.get('confidence', 0) or 0):.1f}%", s.get('severity', '')]
        for s in scans
    ]
    stats_html = make_history_stats_html(rows, is_patient_view=(role == 'patient'))
    return rows, stats_html


# ── Chatbot function (Groq — completely free) ─────────────────────────────────
CHAT_SYSTEM = """You are MediScan AI's medical assistant. You ONLY discuss these 4 topics:
1. Brain Tumors: Glioma, Meningioma, Pituitary Tumor
2. Pneumonia
3. COVID-19
4. Kidney Disease: Cyst, Stone, Tumor

STRICT RULE: If asked about anything else, say:
"I'm specialized only in Brain Tumors, Pneumonia, COVID-19, and Kidney Disease. I'm not able to help with other topics."

Be empathetic, use simple language, avoid excessive medical jargon.
Always remind users to consult a real doctor for actual diagnosis and treatment.
You can discuss: symptoms, causes, what the diagnosis means, general treatment options, prevention, what to expect.
You can also explain what a Grad-CAM heatmap is if asked: it's a visualization highlighting which
part of the scan the AI focused on most when making its prediction — it does not replace a radiologist's reading.
Do NOT prescribe specific medications or dosages."""

def medical_chat(message, history):
    if not CHAT_ENABLED or not GROQ_KEY:
        return "⚠️ Chatbot is disabled. Add your GROQ_API_KEY in your Space's Settings → Variables and secrets."

    client = Groq(api_key=GROQ_KEY)

    system = CHAT_SYSTEM
    if current_scan.get('diagnosis'):
        system += (
            f"\n\nThe user's latest MediScan AI result: "
            f"Scan={current_scan['scan_type']}, "
            f"Diagnosis={current_scan['diagnosis']}, "
            f"Confidence={current_scan['confidence']:.1f}%, "
            f"Patient={current_scan['patient']}. "
            f"Reference this naturally when relevant."
        )

    msgs = [{"role": "system", "content": system}]
    # Gradio 6 passes history as a list of {"role": ..., "content": ...} dicts
    for turn in history:
        role    = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": message})

    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=msgs,
            max_tokens=700
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"❌ Groq error: {str(e)}\n\nCheck that your GROQ_API_KEY is valid at console.groq.com"


# ════════════════════════════════════════════════════════════════════
#  CELL 4 — Build the Website (4 Tabs)
# ════════════════════════════════════════════════════════════════════

APP_CSS = """
/* ─── Theme variables — light (default) ──────────────────────── */
:root {
    --bg-main: #f0f4f8;
    --bg-card: #ffffff;
    --text-main: #1a1a2e;
    --border-col: #dce3f0;
    --card-shadow: rgba(0,0,0,0.06);
    --card-shadow-hover: rgba(0,0,0,0.12);
    --step-bg: #eef2ff;
    --disc-bg: #fff9c4;
    --disc-text: #5a4000;
    --disc-border: #f9a825;
}

/* ─── Theme variables — dark (toggled via the switch in Settings) ── */
html.dark, body.dark {
    --bg-main: #12141c;
    --bg-card: #1c1f2b;
    --text-main: #e9ecf5;
    --border-col: #333850;
    --card-shadow: rgba(0,0,0,0.35);
    --card-shadow-hover: rgba(0,0,0,0.55);
    --step-bg: #1a2035;
    --disc-bg: #2b2410;
    --disc-text: #ffe082;
    --disc-border: #8d6e00;
}

* { box-sizing: border-box; }

html, body {
    background-color: var(--bg-main) !important;
    color: var(--text-main) !important;
    transition: background-color 0.2s ease, color 0.2s ease;
    overflow-x: hidden;
    max-width: 100vw;
}

/* ─── Center the app / mobile-safe width ───────────────────────── */
.gradio-container {
    max-width: 920px !important;
    width: 100% !important;
    margin-left:  auto !important;
    margin-right: auto !important;
    background: var(--bg-main) !important;
    font-family: 'Segoe UI', Arial, sans-serif !important;
    overflow-x: hidden;
    padding-left: 10px;
    padding-right: 10px;
}

/* ─── Generic Gradio form labels adapt to theme (does NOT touch our  ─
     own colored HTML cards below, which set their own inline colors) */
label, .label-wrap {
    color: var(--text-main);
}

/* Images/scan previews never overflow their container */
img, svg { max-width: 100%; height: auto; }

/* ─── Theme toggle control (now lives inside the Settings accordion) ── */
#ms-theme-toggle { max-width: 280px; margin: 0 auto; }

/* ─── Tab styling ─────────────────────────────────────────────── */
.tabs > .tab-nav > button {
    font-size: 1rem;
    padding: 0.6rem 1.2rem;
    font-weight: 600;
}

/* ─── App header, with a slow-moving gradient for a modern feel ─── */
.ms-header {
    background: linear-gradient(120deg, #0d2b4e, #1565c0, #00838f, #1565c0, #0d2b4e);
    background-size: 300% 300%;
    animation: msGradientShift 12s ease infinite;
    border-radius: 14px;
    padding: 1.8rem 1.5rem;
    text-align: center;
    color: white !important;
    margin-bottom: 1rem;
    box-shadow: 0 4px 24px rgba(21,101,192,0.3);
}
.ms-header h1, .ms-header p { color: white !important; }
.ms-header h1 { margin: 0; font-size: 2rem; font-weight: 700; }
.ms-header p  { margin: 0.4rem 0 0; opacity: 0.9; font-size: 0.97rem; }

@keyframes msGradientShift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

/* ─── Disease cards on Home tab ───────────────────────────────── */
.d-card {
    background: var(--bg-card);
    border-radius: 14px;
    padding: 1.4rem;
    text-align: center;
    border: 1px solid var(--border-col);
    box-shadow: 0 2px 10px var(--card-shadow);
    transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.2s ease;
}
.d-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px var(--card-shadow-hover); }

/* ─── Steps ───────────────────────────────────────────────────── */
.step {
    background: var(--step-bg);
    border-left: 4px solid #1565c0;
    border-radius: 0 10px 10px 0;
    padding: 0.8rem 1.1rem;
    margin-bottom: 0.55rem;
    font-size: 0.93rem;
    color: var(--text-main) !important;
}

/* ─── Disclaimer ──────────────────────────────────────────────── */
.disc {
    background: var(--disc-bg);
    border: 1px solid var(--disc-border);
    border-radius: 10px;
    padding: 0.9rem 1.2rem;
    font-size: 0.87rem;
    text-align: center;
    color: var(--disc-text) !important;
}

/* ─── Result / diagnosis cards: self-contained colors by design    ─
     (always readable regardless of app theme), with a gentle
     fade-and-rise entrance so a new result feels alive. ───────── */
.ms-result-card, .ms-chart-card {
    animation: msFadeUp 0.45s ease-out;
}
@keyframes msFadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ─── Confidence donut chart card ─────────────────────────────── */
.ms-chart-card {
    background: var(--bg-card);
    border: 1px solid var(--border-col);
    border-radius: 12px;
    padding: 1rem;
    box-shadow: 0 2px 10px var(--card-shadow);
}

/* ─── Subtle interactive feedback on buttons ───────────────────── */
button { transition: transform 0.12s ease, filter 0.12s ease; }
button:hover { filter: brightness(1.05); }
button.primary:hover, button.lg.primary:hover { transform: translateY(-1px); }

/* ─── Mobile responsive ───────────────────────────────────────── */
@media (max-width: 640px) {
    .gradio-container { padding-left: 6px; padding-right: 6px; }
    .ms-header { padding: 1.2rem 1rem; }
    .ms-header h1 { font-size: 1.35rem; }
    .ms-header p  { font-size: 0.8rem; }
    .d-card { padding: 1rem; min-width: 100% !important; }
    .step { font-size: 0.85rem; padding: 0.65rem 0.9rem; }
    .tabs > .tab-nav > button { font-size: 0.85rem; padding: 0.45rem 0.7rem; }
    .ms-chart-card > div { flex-direction: column; }
}
"""

# Injected into <head> — makes sure mobile browsers render at device width
# instead of a zoomed-out desktop layout (this is what was causing the
# "cropped on phone" issue).
APP_HEAD = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'

# Toggles Gradio's own `.dark` class on <html>/<body> based on the radio
# choice — this drives both our custom CSS variables above AND Gradio's
# built-in dark styling for buttons/inputs/etc, so nothing gets out of sync.
TOGGLE_THEME_JS = """
(choice) => {
    const dark = choice.includes('Dark');
    document.documentElement.classList.toggle('dark', dark);
    document.body.classList.toggle('dark', dark);
}
"""

HOME_HTML = """
<div class="ms-header">
    <h1>🏥 MediScan AI</h1>
    <p>AI-Powered Medical Imaging Diagnostic System</p>
    <p style="font-size:0.8rem; margin-top:0.5rem; opacity:0.75">
        MRI &nbsp;·&nbsp; X-Ray &nbsp;·&nbsp; CT (COVID-19 or Kidney)
    </p>
</div>

<h3 style="text-align:center; color:#1565c0; margin:1.4rem 0 0.8rem">
    What can MediScan AI detect?
</h3>
<div style="display:flex; gap:0.9rem; flex-wrap:wrap; justify-content:center; margin-bottom:1.5rem">
    <div class="d-card" style="flex:1; min-width:180px; max-width:255px">
        <div style="font-size:2.8rem; margin-bottom:0.4rem">🧠</div>
        <h4 style="color:#1565c0; margin:0 0 0.35rem">Brain Tumors</h4>
        <p style="color:var(--text-main); opacity:0.75; font-size:0.83rem; margin:0">
            Analyzes Brain MRI scans<br>
            <b>Glioma · Meningioma<br>Pituitary Tumor · No Tumor</b>
        </p>
    </div>
    <div class="d-card" style="flex:1; min-width:180px; max-width:255px">
        <div style="font-size:2.8rem; margin-bottom:0.4rem">🫁</div>
        <h4 style="color:#1565c0; margin:0 0 0.35rem">Pneumonia</h4>
        <p style="color:var(--text-main); opacity:0.75; font-size:0.83rem; margin:0">
            Analyzes Chest X-Ray images<br>
            <b>Pneumonia · Normal</b>
        </p>
    </div>
    <div class="d-card" style="flex:1; min-width:180px; max-width:255px">
        <div style="font-size:2.8rem; margin-bottom:0.4rem">🦠</div>
        <h4 style="color:#1565c0; margin:0 0 0.35rem">COVID-19</h4>
        <p style="color:var(--text-main); opacity:0.75; font-size:0.83rem; margin:0">
            Analyzes CT Scan images<br>
            <b>COVID-19 · Normal</b>
        </p>
    </div>
    <div class="d-card" style="flex:1; min-width:180px; max-width:255px">
        <div style="font-size:2.8rem; margin-bottom:0.4rem">🫘</div>
        <h4 style="color:#1565c0; margin:0 0 0.35rem">Kidney Disease</h4>
        <p style="color:var(--text-main); opacity:0.75; font-size:0.83rem; margin:0">
            Analyzes Kidney CT scans<br>
            <b>Cyst · Stone<br>Tumor · Normal</b>
        </p>
    </div>
</div>

<h3 style="text-align:center; color:#1565c0; margin:0 0 0.8rem">How to use MediScan AI</h3>
<div style="max-width:520px; margin:0 auto 1.4rem">
    <div class="step"><b>Step 1</b> — Go to <b>🔬 Diagnose</b> and enter patient name, age, and sex</div>
    <div class="step"><b>Step 2</b> — Choose scan type (MRI / X-Ray / CT) — CT lets you pick COVID-19 or Kidney</div>
    <div class="step"><b>Step 3</b> — Choose which disease to check (auto-filled for you)</div>
    <div class="step"><b>Step 4</b> — Upload, photograph, or paste the scan image and click <b>🔍 Analyze Scan</b></div>
    <div class="step"><b>Step 5</b> — Read the AI diagnosis, confidence chart, and Grad-CAM heatmap</div>
    <div class="step"><b>Step 6</b> — Go to <b>💬 AI Chat</b> to ask questions about the result</div>
    <div class="step"><b>Step 7</b> — View or clear all past scans in the <b>📋 History</b> tab</div>
</div>

<div class="disc">
    ⚠️ <b>Medical Disclaimer:</b> MediScan AI is for <b>educational and research purposes only</b>.
    It is <b>not</b> a substitute for professional medical diagnosis or treatment.
    Always consult a qualified healthcare professional.
</div>
"""

with gr.Blocks(title="MediScan AI 🏥", head=APP_HEAD) as demo:

    session_state = gr.State(value=None)   # {'user_id','email','role','name'} or None

    with gr.Accordion("⚙️ Settings", open=False):
        theme_toggle = gr.Radio(
            choices=["🌞 Light Mode", "🌙 Dark Mode"],
            value="🌞 Light Mode",
            label="Appearance",
            elem_id="ms-theme-toggle",
        )
        gr.Markdown("---")
        gr.Markdown(
            "### 🗑️ Delete My Account\n"
            "*This permanently deletes your account, your patients (if you're a Doctor), "
            "and all your scan history. This cannot be undone.*"
        )
        delete_confirm_check = gr.Checkbox(label="I understand this is permanent")
        delete_account_btn = gr.Button("🗑️ Delete My Account", variant="stop", size="sm")
        delete_account_msg = gr.Markdown("")
    theme_toggle.change(fn=None, inputs=[theme_toggle], outputs=None, js=TOGGLE_THEME_JS)
    demo.load(fn=None, inputs=[theme_toggle], outputs=None, js=TOGGLE_THEME_JS)

    # ════════════ ACCOUNT GATE (Sign In / Sign Up / Guest) ═════════════════════
    with gr.Group(visible=True) as auth_group:
        gr.HTML(
            '<div class="ms-header"><h1>🔐 Welcome to MediScan AI</h1>'
            '<p>Sign in or create an account to continue</p></div>'
        )
        if not DB_ENABLED:
            gr.HTML("""
            <div style="background:#e3f2fd;border:1px solid #1565c0;border-radius:12px;
                padding:1.5rem 2rem;font-family:Segoe UI,Arial,sans-serif;">
                <h3 style="color:#1565c0;margin:0 0 0.8rem">🗄️ Set Up Accounts (Free)</h3>
                <ol style="color:#333;padding-left:1.2rem;line-height:2">
                    <li>Go to <b>supabase.com</b> → create a free project</li>
                    <li>Project Settings → API → copy the <b>Project URL</b> and <b>anon public key</b></li>
                    <li>In the SQL Editor, run the schema from the setup notes to create
                        the <code>profiles</code>, <code>patients</code>, and <code>scans</code> tables</li>
                    <li>Authentication → Providers → Email → turn <b>OFF</b> "Confirm email"</li>
                    <li>On your Hugging Face Space: Settings → Variables and secrets → add
                        <code>SUPABASE_URL</code> and <code>SUPABASE_KEY</code></li>
                    <li>The Space restarts automatically and accounts will be live</li>
                </ol>
            </div>""")
        gr.Markdown("*Or explore the diagnostic tool right away —*")
        guest_btn = gr.Button("👋 Continue as Guest (no account, nothing is saved)", size="sm")

        with gr.Tabs():
            with gr.Tab("Sign In"):
                si_email = gr.Textbox(label="Email")
                si_pass  = gr.Textbox(label="Password", type="password")
                si_btn   = gr.Button("Sign In", variant="primary")
                si_msg   = gr.Markdown("")
            with gr.Tab("Sign Up"):
                su_name  = gr.Textbox(label="Full Name")
                su_email = gr.Textbox(label="Email")
                su_pass  = gr.Textbox(label="Password (6+ characters)", type="password")
                su_role  = gr.Radio(
                    choices=["Patient", "Doctor", "Medical Researcher"],
                    value="Patient", label="I am signing up as a...",
                )
                su_btn   = gr.Button("Create Account", variant="primary")
                su_msg   = gr.Markdown("")

    # ════════════ MAIN APP (hidden until signed in or Guest) ═══════════════════
    with gr.Row(visible=False) as welcome_row:
        welcome_bar = gr.HTML()
        logout_btn  = gr.Button("🚪 Logout", size="sm", scale=0)

    # ════════════ TAB 1: Home ════════════════════════════════════════════════
    with gr.Tabs(visible=False) as main_tabs:
        with gr.Tab("🏠 Home"):
            gr.HTML(HOME_HTML)


        # ════════════ TAB 2: Diagnose ════════════════════════════════════════
        with gr.Tab("🔬 Diagnose"):
            gr.HTML(
                '<div class="ms-header">'
                '<h1>🔬 Scan Analysis</h1>'
                '<p>Fill in patient info · choose scan type · upload image · click Analyze</p>'
                '</div>'
            )

            # ── Patient info ─────────────────────────────────────────────────
            with gr.Row():
                name_in = gr.Textbox(
                    label="👤 Patient Full Name",
                    placeholder="e.g. Ahmed Ali",
                    scale=2
                )
                age_in = gr.Number(
                    label="🎂 Age",
                    value=30, minimum=1, maximum=120,
                    scale=1
                )
                sex_in = gr.Radio(
                    choices=["Male", "Female", "Prefer not to say"],
                    label="🚻 Sex",
                    value="Prefer not to say",
                    scale=2
                )

            # ── Assign to one of the doctor's saved patient profiles (optional) ──
            # Hidden for Researcher/Patient/Guest — only Doctors manage patient
            # profiles, per the account system below. Picking a patient here
            # auto-fills the Name/Age/Sex fields above from their saved
            # profile, so you're not re-typing the same info you already
            # entered in 👤 My Patients. Leave it on "No patient selected" for
            # a quick ad-hoc test where you still want to type these by hand.
            patient_assign_drop = gr.Dropdown(
                label="👤 Assign This Scan To (from your 👤 My Patients list)",
                choices=[("— No patient selected (just testing) —", "")],
                value="",
                visible=False,
            )
            patient_assign_drop.change(
                fn=autofill_patient_fields,
                inputs=[session_state, patient_assign_drop],
                outputs=[name_in, age_in, sex_in]
            )

            # ── Scan type (plain modality only — disease is chosen in Step 2) ──
            scan_radio = gr.Radio(
                choices=['MRI', 'X-Ray', 'CT'],
                label="🔬 Step 1 — Choose Scan Type",
                value='MRI',
            )

            # ── Disease selector (auto-filled based on scan type, but selectable) ──
            # CT offers 2 real choices here — COVID-19 (lungs) or Kidney Disease.
            disease_drop = gr.Dropdown(
                choices=[o['label'] for o in DISEASE_OPTIONS['MRI']],
                value=DISEASE_OPTIONS['MRI'][0]['label'],
                label="🩺 Step 2 — Choose the Disease to Check For",
                interactive=True,
                info="Pre-selected based on the scan type you chose above — you can confirm or change it."
            )

            # Disease info card
            disease_info_html = gr.HTML(
                value=_disease_info_card_html(DISEASE_OPTIONS['MRI'][0])
            )

            # Update dropdown + info card when scan type radio changes
            scan_radio.change(
                fn=update_disease_section,
                inputs=[scan_radio],
                outputs=[disease_drop, disease_info_html]
            )
            # Update ONLY the info card when the disease itself changes
            # (matters for CT — switching between COVID-19 and Kidney)
            disease_drop.change(
                fn=update_disease_info,
                inputs=[scan_radio, disease_drop],
                outputs=[disease_info_html]
            )

            # ── Image upload (upload a file, take a photo, or paste from clipboard) ──
            image_in = gr.Image(
                label="📤 Step 3 — Upload, Photograph, or Paste the Scan Image",
                sources=["upload", "webcam", "clipboard"],
                type="numpy",
                height=280,
            )

            # ── Analyze button ───────────────────────────────────────────────
            analyze_btn = gr.Button("🔍 Analyze Scan", variant="primary", size="lg")

            gr.Markdown("---")
            gr.Markdown("### 📊 Diagnosis Result")

            result_html_out  = gr.HTML()
            with gr.Row():
                confidence_out = gr.Label(
                    label="📈 Confidence Breakdown",
                    num_top_classes=4,
                    scale=1,
                )
                chart_out = gr.HTML(scale=1)

            gradcam_out  = gr.HTML()
            _hidden_hist = gr.DataFrame(visible=False)

            analyze_btn.click(
                fn=analyze_scan,
                inputs=[name_in, age_in, sex_in, scan_radio, disease_drop, image_in,
                        session_state, patient_assign_drop],
                outputs=[result_html_out, confidence_out, chart_out, gradcam_out, _hidden_hist]
            )


        # ════════════ TAB 3: AI Chat ══════════════════════════════════════════
        with gr.Tab("💬 AI Chat"):
            gr.HTML(
                '<div class="ms-header">'
                '<h1>💬 AI Medical Assistant</h1>'
                '<p>Ask me about Brain Tumors · Pneumonia · COVID-19 · Kidney Disease</p>'
                '</div>'
            )

            if CHAT_ENABLED:
                gr.Markdown(
                    "I **automatically know your latest scan result** (if you used the Diagnose tab). "
                    "I only answer questions about the 4 diseases MediScan AI covers."
                )
                gr.ChatInterface(
                    fn=medical_chat,
                    chatbot=gr.Chatbot(
                        height=420,
                        placeholder=(
                            "👋 Hi! I'm MediScan's AI assistant.\n\n"
                            "Ask me about Brain Tumors, Pneumonia, COVID-19, or Kidney Disease.\n\n"
                            "Examples:\n"
                            "• *What is Glioma?*\n"
                            "• *What are the symptoms of Pneumonia?*\n"
                            "• *What does a kidney cyst mean?*"
                        ),
                        show_label=False,
                    ),
                    textbox=gr.Textbox(
                        placeholder="Type your question and press Enter...",
                        container=False, scale=7
                    ),
                    examples=[
                        "What is Glioma and how serious is it?",
                        "What are the symptoms of Pneumonia?",
                        "What should I do after a COVID-19 CT diagnosis?",
                        "What is the difference between Meningioma and Glioma?",
                        "Can pituitary tumors be fully cured?",
                        "How is bacterial pneumonia treated?",
                        "What's the difference between a kidney cyst and a kidney stone?",
                        "How serious is a kidney tumor?",
                        "What is a Grad-CAM heatmap and can I trust it?",
                    ],
                    title=None,
                    submit_btn="Send ➤",
                )
            else:
                gr.HTML("""
                <div style="background:#e3f2fd;border:1px solid #1565c0;border-radius:12px;
                    padding:1.5rem 2rem;font-family:Segoe UI,Arial,sans-serif;">
                    <h3 style="color:#1565c0;margin:0 0 0.8rem">💬 Set Up the Chatbot (Free)</h3>
                    <ol style="color:#333;padding-left:1.2rem;line-height:2">
                        <li>Go to <b>console.groq.com</b> → sign up for free</li>
                        <li>Click <b>API Keys</b> in the left menu → <b>Create API Key</b></li>
                        <li>Copy the key that appears</li>
                        <li>On your Hugging Face Space, go to <b>Settings</b> → <b>Variables and secrets</b></li>
                        <li>Click <b>New secret</b><br>
                            Name: <code>GROQ_API_KEY</code><br>
                            Value: paste your key here</li>
                        <li>The Space will restart automatically and pick it up</li>
                    </ol>
                    <p style="color:#1565c0;font-weight:600;margin:0.5rem 0 0">
                        Groq is 100% free — no credit card required.
                    </p>
                </div>""")


        # ════════════ TAB 4: History ══════════════════════════════════════════
        with gr.Tab("📋 History"):
            gr.HTML(
                '<div class="ms-header">'
                '<h1>📋 Scan History</h1>'
                '<p>Guest mode: this session only · Signed in: saved to your account</p>'
                '</div>'
            )

            # Guest-mode table (in-memory, session-only) — visible for Guest only
            with gr.Row() as guest_hist_row:
                refresh_btn = gr.Button("🔄 Refresh History", variant="secondary", size="sm")
                clear_hist_btn = gr.Button("🗑️ Clear History", variant="stop", size="sm")

            history_table = gr.DataFrame(
                value=[],
                headers=["Time", "Patient", "Age", "Sex", "Scan Type", "Diagnosis", "Confidence"],
                datatype=["str", "str", "number", "str", "str", "str", "str"],
                label="", interactive=False, wrap=True, visible=True,
            )
            guest_hist_note = gr.Markdown(
                "*Click **Refresh History** after each scan to update this table.*  \n"
                "*Guest history resets when the Space restarts or sleeps, and isn't saved anywhere.*"
            )

            # DB-backed table (persistent) — visible for logged-in accounts
            db_refresh_btn = gr.Button("🔄 Refresh My History", variant="secondary", size="sm", visible=False)
            db_stats_html = gr.HTML(visible=False)
            db_history_table = gr.DataFrame(
                value=[],
                headers=["Time", "Scan Type", "Diagnosis", "Confidence", "Severity"],
                datatype=["str", "str", "str", "str", "str"],
                label="", interactive=False, wrap=True, visible=False,
            )
            db_hist_note = gr.Markdown(
                "*This history is tied to your account and persists across sessions. "
                "Doctors: per-patient history with notes lives in 👤 My Patients.*",
                visible=False,
            )

            refresh_btn.click(fn=_history_rows, inputs=[], outputs=[history_table])
            clear_hist_btn.click(fn=clear_history, inputs=[], outputs=[history_table])
            db_refresh_btn.click(fn=refresh_history_smart, inputs=[session_state], outputs=[db_history_table, db_stats_html])

        # ════════════ TAB 5: My Patients (Doctor only) ═════════════════════════
        with gr.Tab("👤 My Patients", visible=False) as patients_tab:
            gr.HTML(
                '<div class="ms-header"><h1>👤 My Patients</h1>'
                '<p>Manage patient profiles, notes, and their scan history</p></div>'
            )
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### ➕ Add a New Patient")
                    np_name  = gr.Textbox(label="Full Name")
                    np_age   = gr.Number(label="Age", value=30, minimum=1, maximum=120)
                    np_sex   = gr.Radio(choices=["Male", "Female", "Prefer not to say"],
                                        value="Prefer not to say", label="Sex")
                    np_email = gr.Textbox(
                        label="Patient's Email (optional)",
                        info="If they create their own Patient account with this same email, they'll see this history."
                    )
                    np_notes = gr.Textbox(label="Notes", lines=3,
                                           placeholder="History, allergies, ongoing concerns...")
                    np_btn = gr.Button("➕ Add Patient", variant="primary")
                    np_msg = gr.Markdown("")

                with gr.Column(scale=1):
                    gr.Markdown("### 📋 Select a Patient")
                    patient_pick_drop = gr.Dropdown(
                        label="Your Patients",
                        choices=[("— No patient selected (just testing) —", "")],
                        value="",
                    )
                    pick_refresh_btn = gr.Button("🔄 Refresh List", size="sm")
                    patient_detail_html = gr.HTML()
                    patient_notes_box = gr.Textbox(label="📝 Notes", lines=4)
                    save_notes_btn = gr.Button("💾 Save Notes", size="sm")
                    notes_msg = gr.Markdown("")

            gr.Markdown("### 📜 This Patient's Scan History")
            patient_history_table = gr.DataFrame(
                value=[],
                headers=["Time", "Scan Type", "Diagnosis", "Confidence", "Severity"],
                datatype=["str", "str", "str", "str", "str"],
                label="", interactive=False, wrap=True,
            )

            np_btn.click(
                fn=add_patient_handler,
                inputs=[session_state, np_name, np_age, np_sex, np_email, np_notes],
                outputs=[np_msg, patient_pick_drop, patient_assign_drop]
            )
            pick_refresh_btn.click(fn=refresh_patient_dropdown, inputs=[session_state], outputs=[patient_pick_drop])
            patient_pick_drop.change(
                fn=show_patient_detail,
                inputs=[session_state, patient_pick_drop],
                outputs=[patient_detail_html, patient_notes_box, patient_history_table]
            )
            save_notes_btn.click(
                fn=save_patient_notes_handler,
                inputs=[patient_pick_drop, patient_notes_box],
                outputs=[notes_msg]
            )

        # ════════════ TAB 6: Clinical Reference (Doctor + Researcher) ═════════
        with gr.Tab("📚 Clinical Reference", visible=False) as reference_tab:
            gr.HTML(
                '<div class="ms-header"><h1>📚 Clinical Reference</h1>'
                '<p>Expanded diagnostic notes for each condition MediScan AI screens for</p></div>'
            )
            gr.HTML(make_clinical_reference_html('brain_tumor'))
            gr.HTML(make_clinical_reference_html('pneumonia'))
            gr.HTML(make_clinical_reference_html('covid'))
            gr.HTML(make_clinical_reference_html('kidney'))
            gr.Markdown(
                "*This is general educational context, not a clinical guideline — click the "
                "🔗 links above each section for further reading from RSNA/ACR, the WHO, and "
                "other professional sources.*"
            )

    # ════════════ Account wiring: Sign In / Sign Up / Guest / Logout ═══════════
    # One shared helper keeps every entry point (sign in, sign up, guest,
    # logout) in perfect sync — they all just compute a `session` and hand it
    # to the exact same function to redraw the UI.
    MAIN_OUTPUTS = [
        session_state, auth_group, welcome_row, welcome_bar, main_tabs,
        patients_tab, reference_tab, patient_assign_drop,
        guest_hist_row, history_table, guest_hist_note,
        db_refresh_btn, db_stats_html, db_history_table, db_hist_note,
        # Diagnose tab — cleared on every sign-in/sign-up/guest/logout so the
        # NEXT person using this browser tab never sees the previous
        # person's name, image, or diagnosis still sitting there.
        name_in, age_in, sex_in, image_in,
        result_html_out, confidence_out, chart_out, gradcam_out,
    ]

    def _full_ui_refresh(session):
        logged    = session is not None
        role      = session.get('role') if session else None
        is_guest  = (role == 'guest')
        is_doctor = (role == 'doctor')
        is_db_role = logged and not is_guest   # doctor / researcher / patient

        # Wipe the shared "latest scan" context so the chatbot never carries
        # a diagnosis over from whoever was using this session before.
        current_scan.update({
            'diagnosis': None, 'scan_type': None, 'confidence': None,
            'patient': None, 'sex': None,
        })

        welcome_html = ""
        if logged:
            role_label = {'doctor': '👨‍⚕️ Doctor', 'researcher': '🔬 Medical Researcher',
                          'patient': '🙂 Patient', 'guest': '👋 Guest'}.get(role, role)
            name = session.get('name') or session.get('email') or 'there'
            welcome_html = (
                f'<div style="text-align:right;padding:0.3rem 0.6rem;color:var(--text-main);'
                f'font-size:0.85rem;opacity:0.85">Signed in as <b>{name}</b> ({role_label})</div>'
            )

        if is_doctor:
            choices, _ = _patient_choices(session['user_id'])
            patient_drop_update = gr.update(choices=choices, value="", visible=True)
        else:
            patient_drop_update = gr.update(visible=False, value="")

        db_hist_rows, db_stats = refresh_history_smart(session) if is_db_role else ([], "")

        return (
            session,                                              # session_state
            gr.update(visible=not logged),                        # auth_group
            gr.update(visible=logged),                             # welcome_row
            welcome_html,                                          # welcome_bar
            gr.update(visible=logged),                             # main_tabs
            gr.update(visible=is_doctor),                          # patients_tab
            gr.update(visible=role in ('doctor', 'researcher')),   # reference_tab
            patient_drop_update,                                   # patient_assign_drop
            gr.update(visible=is_guest),                           # guest_hist_row
            gr.update(visible=is_guest),                           # history_table
            gr.update(visible=is_guest),                           # guest_hist_note
            gr.update(visible=is_db_role),                         # db_refresh_btn
            gr.update(visible=is_db_role, value=db_stats),         # db_stats_html
            gr.update(visible=is_db_role, value=db_hist_rows),     # db_history_table
            gr.update(visible=is_db_role),                         # db_hist_note
            "",                                                     # name_in
            30,                                                     # age_in
            "Prefer not to say",                                    # sex_in
            None,                                                   # image_in
            "",                                                     # result_html_out
            {},                                                     # confidence_out
            "",                                                     # chart_out
            "",                                                     # gradcam_out
        )

    def handle_sign_in(email, password):
        session, err = db_sign_in(email, password)
        if err:
            return _full_ui_refresh(None) + (f"❌ {err}",)
        return _full_ui_refresh(session) + ("",)

    def handle_sign_up(name, email, password, role_label):
        role = {"Patient": "patient", "Doctor": "doctor",
                 "Medical Researcher": "researcher"}.get(role_label, "patient")
        session, err = db_sign_up(email, password, name, role)
        if err:
            return _full_ui_refresh(None) + (f"❌ {err}",)
        return _full_ui_refresh(session) + ("✅ Account created — welcome!",)

    def handle_guest():
        return _full_ui_refresh({'user_id': None, 'email': None, 'role': 'guest', 'name': 'Guest'})

    def handle_logout():
        return _full_ui_refresh(None)

    def handle_delete_account(session, confirmed):
        if not session or session.get('role') == 'guest':
            return ("⚠️ You're not signed in to an account.",) + _full_ui_refresh(session)
        if not confirmed:
            return ("⚠️ Please check the confirmation box first.",) + _full_ui_refresh(session)
        ok, err = db_delete_account(session['user_id'])
        if not ok:
            return (f"❌ {err}",) + _full_ui_refresh(session)
        return ("✅ Account deleted. You've been signed out.",) + _full_ui_refresh(None)

    si_btn.click(fn=handle_sign_in, inputs=[si_email, si_pass], outputs=MAIN_OUTPUTS + [si_msg])
    su_btn.click(fn=handle_sign_up, inputs=[su_name, su_email, su_pass, su_role], outputs=MAIN_OUTPUTS + [su_msg])
    guest_btn.click(fn=handle_guest, inputs=[], outputs=MAIN_OUTPUTS)
    logout_btn.click(fn=handle_logout, inputs=[], outputs=MAIN_OUTPUTS)
    delete_account_btn.click(
        fn=handle_delete_account,
        inputs=[session_state, delete_confirm_check],
        outputs=[delete_account_msg] + MAIN_OUTPUTS
    )


# ════════════════════════════════════════════════════════════════════
#  CELL 5 — Launch!
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
#  Launch — Hugging Face Spaces hosts this directly, no share tunnel needed
# ════════════════════════════════════════════════════════════════════

print("\n🚀 Launching MediScan AI v4.0...")
demo.launch(
    theme=gr.themes.Soft(primary_hue="blue", secondary_hue="cyan"),
    css=APP_CSS,
)

# ✅ Your permanent public URL will look like:
#    https://huggingface.co/spaces/<your-username>/<your-space-name>
#
# ─────────────────────────────────────────────────────────────────────
# ⚠️  IF CT RESULTS SEEM WRONG (says Normal for a COVID scan):
#     Change CT_FLIP = False → CT_FLIP = True near the top of this file,
#     save it, and the Space will rebuild automatically.
# ─────────────────────────────────────────────────────────────────────
