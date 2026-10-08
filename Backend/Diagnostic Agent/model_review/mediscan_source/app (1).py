# ╔══════════════════════════════════════════════════════════════════╗
# ║   MediScan AI — Version 3.1  (Hugging Face Spaces build)        ║
# ║                                                                  ║
# ║  • X-Ray model: correct input size (384×384)                    ║
# ║  • CT model: correct input size (380×380)                       ║
# ║  • X-Ray + CT: binary sigmoid output handled correctly           ║
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
import gradio as gr
from groq import Groq
import numpy as np
import tensorflow as tf
from PIL import Image
from datetime import datetime

# EfficientNet preprocessing (used for all 3 models)
from tensorflow.keras.applications.efficientnet import preprocess_input as eff_preprocess

print("⏳ Loading models — takes 30–60 seconds...")

# ── Model files must be uploaded to the SAME folder as this app.py ──────────
mri_model  = tf.keras.models.load_model('best_brain_tumor_model.keras')
xray_model = tf.keras.models.load_model('x-ray.keras')
ct_model   = tf.keras.models.load_model('Covid_19.keras')
# ─────────────────────────────────────────────────────────────────────────────

print("✅ All 3 models loaded!")
print(f"   MRI   input: {mri_model.input_shape}   output: {mri_model.output_shape}")
print(f"   X-Ray input: {xray_model.input_shape}  output: {xray_model.output_shape}")
print(f"   CT    input: {ct_model.input_shape}    output: {ct_model.output_shape}")

# ── Groq API key for chatbot ──────────────────────────────────────────────────
# On Hugging Face: go to your Space → Settings → "Variables and secrets"
# → New secret → Name: GROQ_API_KEY, Value: your key from console.groq.com (free)
GROQ_KEY     = os.environ.get('GROQ_API_KEY', '')
CHAT_ENABLED = bool(GROQ_KEY)
if CHAT_ENABLED:
    print("✅ Groq chatbot key found!")
else:
    print("⚠️  Groq key not found — chatbot will show setup instructions.")


# ════════════════════════════════════════════════════════════════════
#  CELL 3 — Configuration, Prediction Functions, Chatbot
# ════════════════════════════════════════════════════════════════════

# ── Class labels for MRI (4-class softmax, alphabetical folder order) ────────
MRI_CLASSES = ['Glioma', 'Meningioma', 'No Tumor', 'Pituitary Tumor']
# glioma=0, meningioma=1, notumor=2, pituitary=3

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
}

# ── Disease selection options (shown after scan type is chosen) ───────────────
SCAN_TO_DISEASES = {
    '🧠 Brain MRI':   ['🧠 Brain Tumor — checks for Glioma, Meningioma, Pituitary Tumor, or No Tumor'],
    '🫁 Chest X-Ray': ['🫁 Pneumonia — checks for signs of lung infection in the chest X-Ray'],
    '🦠 CT Scan':     ['🦠 COVID-19 — checks for COVID-19 related lung changes in the CT scan'],
}

DISEASE_INFO = {
    '🧠 Brain MRI': {
        'title': '🧠 Brain Tumor Detection',
        'description': 'This model analyzes brain MRI scans and classifies them into 4 categories: <b>Glioma</b>, <b>Meningioma</b>, <b>Pituitary Tumor</b>, or <b>No Tumor</b>. Early detection of brain tumors significantly improves treatment outcomes.',
    },
    '🫁 Chest X-Ray': {
        'title': '🫁 Pneumonia Detection',
        'description': 'This model analyzes chest X-Ray images to detect signs of <b>Pneumonia</b>. Pneumonia is a lung infection that can be bacterial or viral. Prompt diagnosis is critical for effective treatment.',
    },
    '🦠 CT Scan': {
        'title': '🦠 COVID-19 Detection',
        'description': 'This model analyzes chest CT scans for signs of <b>COVID-19</b> related lung changes such as ground-glass opacities. CT scans are a valuable tool for assessing COVID-19 severity.',
    },
}

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


def predict_mri(pil_img):
    """MRI: EfficientNetB0, 224×224, 4-class softmax → argmax."""
    arr   = prep_image(pil_img, (224, 224))
    arr   = eff_preprocess(arr)                  # EfficientNetB0 preprocessing
    preds = _as_probabilities(mri_model.predict(arr, verbose=0)[0])  # shape: (4,)
    idx   = int(np.argmax(preds))
    cls   = MRI_CLASSES[idx]
    conf  = float(preds[idx]) * 100
    probs = {MRI_CLASSES[i]: float(preds[i]) * 100 for i in range(4)}
    return cls, conf, probs

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
    else:
        cls, conf = 'Normal', normal_prob

    probs = {'Pneumonia': pneumonia_prob, 'Normal': normal_prob}
    return cls, conf, probs

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
    else:
        covid_prob  = (1 - pred) * 100     # COVID labeled as 0 in training (alphabetically first)
        normal_prob = pred * 100

    if covid_prob > 50:
        cls, conf = 'COVID-19', covid_prob
    else:
        cls, conf = 'Normal', normal_prob

    probs = {'COVID-19': covid_prob, 'Normal': normal_prob}
    return cls, conf, probs


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
def analyze_scan(patient_name, patient_age, patient_sex, scan_choice, disease_choice, image):
    global current_scan, scan_history

    # Input validation
    if not patient_name or not patient_name.strip():
        return _warn("⚠️ Please enter the patient's name."), {}, "", _history_rows()
    if image is None:
        return _warn("⚠️ Please upload a scan image."), {}, "", _history_rows()

    try:
        pil_img = Image.fromarray(image)

        # Run the correct model
        if scan_choice == '🧠 Brain MRI':
            cls, conf, probs = predict_mri(pil_img)
        elif scan_choice == '🫁 Chest X-Ray':
            cls, conf, probs = predict_xray(pil_img)
        else:
            cls, conf, probs = predict_ct(pil_img)

        info = INSIGHTS.get(cls, {})

        # Update shared state (chatbot uses this for context)
        current_scan.update({
            'diagnosis': cls, 'scan_type': scan_choice,
            'confidence': conf, 'patient': patient_name.strip(),
            'sex': patient_sex,
        })

        # Save to session history
        scan_history.append({
            'time': datetime.now().strftime('%H:%M'),
            'name': patient_name.strip(), 'age': int(patient_age),
            'sex': patient_sex or '—',
            'scan': scan_choice, 'diagnosis': cls,
            'confidence': f'{conf:.1f}%'
        })

        # Low confidence warning
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

        return result_html, probs_for_label, chart_html, _history_rows()

    except Exception as e:
        error_html = f"""
        <div class="ms-result-card" style="background:#ffebee;border-left:5px solid #c62828;border-radius:10px;padding:1.5rem">
            <h3 style="color:#c62828;margin:0">❌ Analysis Error</h3>
            <p style="margin:0.7rem 0; color:#333"><b>Error:</b> {str(e)}</p>
            <p style="color:#555">Common fixes:
            <ul>
                <li>Make sure all 3 model files loaded correctly (check the Space's logs)</li>
                <li>Try uploading a different image (JPG format works best)</li>
                <li>Make sure the image is not corrupted</li>
            </ul></p>
        </div>"""
        return error_html, {}, "", _history_rows()


# ── Disease info card (shown when user selects scan type) ─────────────────────
def update_disease_section(scan_choice):
    """Updates the disease dropdown and info card when scan type changes."""
    choices = SCAN_TO_DISEASES.get(scan_choice, [])
    new_val = choices[0] if choices else None
    info    = DISEASE_INFO.get(scan_choice, {})
    info_html = f"""
    <div class="ms-result-card" style="
        background: #e8f0fe;
        border: 1px solid #1a73e8;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        font-family: Segoe UI, Arial, sans-serif;
    ">
        <h4 style="margin:0 0 0.4rem; color:#1a73e8">{info.get('title','')}</h4>
        <p style="margin:0; color:#333; font-size:0.9rem">{info.get('description','')}</p>
    </div>""" if info else ""
    return (
        gr.update(choices=choices, value=new_val),
        info_html
    )

def _warn(msg):
    return f'<div class="ms-result-card" style="background:#fff3cd;border:1px solid #f9a825;border-radius:8px;padding:1rem;font-family:Segoe UI,Arial,sans-serif;color:#5a4000">{msg}</div>'

def _history_rows():
    return [[r['time'], r['name'], r['age'], r.get('sex', '—'), r['scan'], r['diagnosis'], r['confidence']]
            for r in scan_history]


# ── Chatbot function (Groq — completely free) ─────────────────────────────────
CHAT_SYSTEM = """You are MediScan AI's medical assistant. You ONLY discuss these 3 topics:
1. Brain Tumors: Glioma, Meningioma, Pituitary Tumor
2. Pneumonia
3. COVID-19

STRICT RULE: If asked about anything else, say:
"I'm specialized only in Brain Tumors, Pneumonia, and COVID-19. I'm not able to help with other topics."

Be empathetic, use simple language, avoid excessive medical jargon.
Always remind users to consult a real doctor for actual diagnosis and treatment.
You can discuss: symptoms, causes, what the diagnosis means, general treatment options, prevention, what to expect.
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
        Brain MRI &nbsp;·&nbsp; Chest X-Ray &nbsp;·&nbsp; CT Scan
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
</div>

<h3 style="text-align:center; color:#1565c0; margin:0 0 0.8rem">How to use MediScan AI</h3>
<div style="max-width:520px; margin:0 auto 1.4rem">
    <div class="step"><b>Step 1</b> — Go to <b>🔬 Diagnose</b> and enter patient name and age</div>
    <div class="step"><b>Step 2</b> — Choose scan type (MRI / X-Ray / CT)</div>
    <div class="step"><b>Step 3</b> — Choose which disease to check (auto-filled for you)</div>
    <div class="step"><b>Step 4</b> — Upload the scan image and click <b>🔍 Analyze Scan</b></div>
    <div class="step"><b>Step 5</b> — Read the AI diagnosis and recommendations</div>
    <div class="step"><b>Step 6</b> — Go to <b>💬 AI Chat</b> to ask questions about the result</div>
    <div class="step"><b>Step 7</b> — View all past scans in the <b>📋 History</b> tab</div>
</div>

<div class="disc">
    ⚠️ <b>Medical Disclaimer:</b> MediScan AI is for <b>educational and research purposes only</b>.
    It is <b>not</b> a substitute for professional medical diagnosis or treatment.
    Always consult a qualified healthcare professional.
</div>
"""

with gr.Blocks(title="MediScan AI 🏥", head=APP_HEAD) as demo:

    with gr.Accordion("⚙️ Settings", open=False):
        theme_toggle = gr.Radio(
            choices=["🌞 Light Mode", "🌙 Dark Mode"],
            value="🌞 Light Mode",
            label="Appearance",
            elem_id="ms-theme-toggle",
        )
    theme_toggle.change(fn=None, inputs=[theme_toggle], outputs=None, js=TOGGLE_THEME_JS)
    demo.load(fn=None, inputs=[theme_toggle], outputs=None, js=TOGGLE_THEME_JS)

    # ════════════ TAB 1: Home ════════════════════════════════════════════════
    with gr.Tabs():
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

            # ── Scan type ────────────────────────────────────────────────────
            scan_radio = gr.Radio(
                choices=['🧠 Brain MRI', '🫁 Chest X-Ray', '🦠 CT Scan'],
                label="🔬 Step 1 — Choose Scan Type",
                value='🧠 Brain MRI',
            )

            # ── Disease selector (auto-filled based on scan type, but selectable) ──
            disease_drop = gr.Dropdown(
                choices=SCAN_TO_DISEASES['🧠 Brain MRI'],
                value=SCAN_TO_DISEASES['🧠 Brain MRI'][0],
                label="🩺 Step 2 — Choose the Disease to Check For",
                interactive=True,
                info="Pre-selected based on the scan type you chose above — you can confirm or change it."
            )

            # Disease info card
            disease_info_html = gr.HTML(
                value=f"""
                <div class="ms-result-card" style="background:#e8f0fe;border:1px solid #1a73e8;border-radius:10px;
                    padding:1rem 1.2rem;font-family:Segoe UI,Arial,sans-serif;">
                    <h4 style="margin:0 0 0.4rem;color:#1a73e8">🧠 Brain Tumor Detection</h4>
                    <p style="margin:0;color:#333;font-size:0.9rem">
                        This model analyzes brain MRI scans and classifies them into 4 categories:
                        <b>Glioma</b>, <b>Meningioma</b>, <b>Pituitary Tumor</b>, or <b>No Tumor</b>.
                        Early detection of brain tumors significantly improves treatment outcomes.
                    </p>
                </div>"""
            )

            # Update dropdown + info card when scan type radio changes
            scan_radio.change(
                fn=update_disease_section,
                inputs=[scan_radio],
                outputs=[disease_drop, disease_info_html]
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
            _hidden_hist = gr.DataFrame(visible=False)

            analyze_btn.click(
                fn=analyze_scan,
                inputs=[name_in, age_in, sex_in, scan_radio, disease_drop, image_in],
                outputs=[result_html_out, confidence_out, chart_out, _hidden_hist]
            )


        # ════════════ TAB 3: AI Chat ══════════════════════════════════════════
        with gr.Tab("💬 AI Chat"):
            gr.HTML(
                '<div class="ms-header">'
                '<h1>💬 AI Medical Assistant</h1>'
                '<p>Ask me about Brain Tumors · Pneumonia · COVID-19</p>'
                '</div>'
            )

            if CHAT_ENABLED:
                gr.Markdown(
                    "I **automatically know your latest scan result** (if you used the Diagnose tab). "
                    "I only answer questions about the 3 diseases MediScan AI covers."
                )
                gr.ChatInterface(
                    fn=medical_chat,
                    chatbot=gr.Chatbot(
                        height=420,
                        placeholder=(
                            "👋 Hi! I'm MediScan's AI assistant.\n\n"
                            "Ask me about Brain Tumors, Pneumonia, or COVID-19.\n\n"
                            "Examples:\n"
                            "• *What is Glioma?*\n"
                            "• *What are the symptoms of Pneumonia?*\n"
                            "• *What should I do after a COVID-19 CT result?*"
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
                        "Is a COVID-19 CT result always accurate?",
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
                '<p>All scans analyzed in this session</p>'
                '</div>'
            )

            refresh_btn = gr.Button("🔄 Refresh History", variant="secondary", size="sm")

            history_table = gr.DataFrame(
                value=[],
                headers=["Time", "Patient", "Age", "Sex", "Scan Type", "Diagnosis", "Confidence"],
                datatype=["str", "str", "number", "str", "str", "str", "str"],
                label="",
                interactive=False,
                wrap=True,
            )

            gr.Markdown(
                "*Click **Refresh History** after each scan to update this table.*  \n"
                "*History resets when the Space restarts or sleeps.*"
            )

            refresh_btn.click(fn=_history_rows, inputs=[], outputs=[history_table])


# ════════════════════════════════════════════════════════════════════
#  CELL 5 — Launch!
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
#  Launch — Hugging Face Spaces hosts this directly, no share tunnel needed
# ════════════════════════════════════════════════════════════════════

print("\n🚀 Launching MediScan AI v3.0...")
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
