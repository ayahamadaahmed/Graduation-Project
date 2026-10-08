# 🩺 MediScan AI – Multi-Modal Medical Imaging Diagnostic Assistant

MediScan AI is an end-to-end **Deep Learning** application that assists healthcare professionals in screening three of the most common and clinically significant medical imaging tasks from a single web interface:

- 🧠 Brain Tumor Classification (MRI)
- 🫁 Pneumonia Detection (Chest X-Ray)
- 🫀 COVID-19 Detection (Chest CT)
- 🤖 AI-powered Medical Assistant using **Llama 3.3 (70B)** via the Groq API

The system combines multiple computer vision models with a context-aware Large Language Model (LLM) to provide diagnostic predictions, confidence scores, severity assessment, and AI-generated medical explanations.

---

# 🚀 Live Demo

**Hugging Face Space**

https://huggingface.co/spaces/PhilopateerSharl/radiology_assistant

---

# 📌 Overview

MediScan AI integrates three independently trained convolutional neural networks into a unified production-ready web application built with **Gradio** and deployed on **Hugging Face Spaces**.

Each model is based on an **EfficientNet** backbone pretrained on ImageNet and trained using a two-stage transfer learning strategy:

- Initial training with a frozen backbone
- Low learning-rate fine-tuning of selected layers

Users can upload or capture a medical image, enter basic patient information, and instantly receive:

- AI diagnosis
- Confidence score
- Color-coded severity level
- Recommended next steps
- AI-generated medical explanation

A built-in conversational assistant powered by **Groq's Llama 3.3 (70B)** automatically understands the latest diagnosis and answers follow-up medical questions within the supported imaging domains.

---

# ✨ Key Features

- Multi-modal medical image analysis
- Three independently trained deep learning models
- EfficientNetB0, EfficientNetB3 and EfficientNetB4 architectures
- Two-stage transfer learning and fine-tuning
- Confidence-aware predictions
- Severity color coding
- Interactive probability donut chart
- Context-aware AI chatbot
- Session-based patient history
- Upload, webcam capture, or clipboard image input
- Responsive Light/Dark mode interface
- Educational and research-focused medical disclaimer

---

# 🧠 Machine Learning Models

| Model                  | Backbone       | Task                              | Input Size |
| ---------------------- | -------------- | --------------------------------- | ---------- |
| Brain Tumor Classifier | EfficientNetB0 | 4-Class MRI Classification        | 224×224    |
| Pneumonia Classifier   | EfficientNetB3 | Binary Chest X-Ray Classification | 384×384    |
| COVID-19 CT Classifier | EfficientNetB4 | Binary Chest CT Classification    | 380×380    |

---

# 📊 Model Performance

| Model                            |   Accuracy |  ROC-AUC |      F1-Score |
| -------------------------------- | ---------: | -------: | ------------: |
| Brain Tumor (EfficientNetB0)     |  **95.6%** | **0.99** |      **0.95** |
| COVID-19 CT (EfficientNetB4)     |  **91.3%** | **0.97** |      **0.91** |
| Pneumonia X-Ray (EfficientNetB3) | **89–92%** | **0.95** | **0.89–0.93** |

Special emphasis was placed on maximizing **Recall**, minimizing false negatives, and improving clinical screening reliability.

---

# 🔄 System Pipeline

```text
Medical Image
      │
      ▼
Image Preprocessing
      │
      ▼
Deep Learning Model
      │
      ▼
Prediction & Confidence Score
      │
      ▼
Severity Assessment
      │
      ├── Probability Visualization
      └── AI Medical Assistant
```

---

# ⚙️ Data Preprocessing

- RGB conversion
- Image resizing
- EfficientNet preprocessing
- Pixel normalization
- Confidence calibration
- Probability normalization

Input sizes:

- Brain MRI → **224 × 224**
- Chest X-Ray → **384 × 384**
- Chest CT → **380 × 380**

---

# 📂 Datasets

- **Brain Tumor MRI Dataset (Kaggle)** — 7,200 balanced MRI images across four classes.
- **SARS-CoV-2 CT-Scan Dataset (Kaggle)** — 2,481 CT images for COVID-19 classification.
- **Chest X-Ray Images (Pneumonia) Dataset (Paul Mooney - Kaggle)** — 6,464 chest X-ray images.

---

# 💻 Technologies Used

### Programming

- Python

### Deep Learning

- TensorFlow
- Keras
- EfficientNet
- NumPy
- Scikit-learn

### Data Analysis

- Pandas
- Matplotlib
- Seaborn

### User Interface

- Gradio
- HTML5
- CSS3
- SVG Visualization

### AI Assistant

- Groq API
- Llama 3.3 (70B)

### Deployment

- Hugging Face Spaces

---

# 📂 Project Structure

```text
final_project/
│
├── app.py
├── requirements.txt
├── README.md
│
├── models/
│   ├── brain_model.keras
│   ├── Pneumonia_EfficientNetB3_Inference.keras
│   └── covid_ct_model.keras
│
└── notebooks/
    ├── Brain_MRI_Classification.ipynb
    ├── Chest_Xray_Pneumonia_Classification_EfficientNetB3.ipynb
    └── Chest_CT_COVID_Classification.ipynb
```

---

# ▶️ Installation

Clone the repository

```bash
git clone https://github.com/mariamayman540/final_project.git
```

Install dependencies

```bash
pip install -r requirements.txt
```

Run the application

```bash
python app.py
```

---

# 🔑 Environment Variables

Configure your Groq API key before running the application.

```bash
export GROQ_API_KEY="YOUR_API_KEY"
```

---

# 🎯 Skills Demonstrated

- Transfer Learning using EfficientNet architectures
- Fine-tuning strategies for medical image classification
- Handling class imbalance with computed class weights
- Model evaluation using Accuracy, Precision, Recall, F1-Score and ROC-AUC
- Error analysis and iterative model improvement
- Deep Learning deployment with Hugging Face Spaces
- Full-stack AI application development using Gradio
- LLM integration with Groq API
- Production debugging and confidence calibration
- Medical Computer Vision and AI-assisted diagnosis

---

# 👥 Contributors

- **Mariam Ayman**
- **Philopateer Sharl**
- **Kerolos Farag**
- **Kermina Shenoda**
- **Sahrab Ehab**

---

# 📄 License

This project was developed for **educational and research purposes only**.

It is **not intended to replace professional medical diagnosis or clinical decision-making**.
