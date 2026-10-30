# Local X-Raydar weights

The three local checkpoints (`is299`, `is512`, `is1024`) are loaded by the
Diagnostic Agent and ensembled at inference time. They are intentionally
excluded from Git because each is about 187 MB. Keep the included upstream
license at `third_party/xraydar/LICENSE` with any redistribution.

Weights are available from the publisher's Hugging Face repository:

- https://huggingface.co/dnamodel/xraydar-cv/resolve/main/cv/is299/model_best.pth.tar
- https://huggingface.co/dnamodel/xraydar-cv/resolve/main/cv/is512/model_best.pth.tar
- https://huggingface.co/dnamodel/xraydar-cv/resolve/main/cv/is1024/model_best.pth.tar

This software includes Warwick X-Raydar code © 2023, The University of Warwick.
The upstream license permits only academic research and non-clinical,
non-commercial evaluation. Commercial or clinical use is prohibited unless the
University grants separate permission. See `third_party/xraydar/LICENSE`.

To use X-Raydar, install the optional dependencies from
`Backend/Diagnostic Agent/requirements-xraydar.txt` in the Diagnostic Agent's
own Python environment. The app defaults to local X-Raydar. To switch back to
the existing MediScan model, set `DIAGNOSTIC_CHEST_XRAY_MODEL=mediscan` and
restart the Diagnostic Agent.
`DIAGNOSTIC_XRAYDAR_MODEL_DIR` can point to a
different folder containing the three `is{size}/model_best.pth.tar` files.

X-Raydar is research software. The upstream license restricts use; read the
license before any use or redistribution. Its outputs are independent findings,
not calibrated probabilities or a diagnosis. It has no direct pulmonary embolism
or pulmonary infarction output label. Do not use it to rule in or rule out these
conditions, and do not use it for clinical decisions.
