# MedMind Frontend

This folder contains the local diagnostic chat workbench. It is plain HTML,
CSS, and JavaScript, so no Node.js build step is needed yet.

## Run the frontend separately

From the repository root, open a PowerShell window and run:

```powershell
python -m http.server 5173 --directory Frontend
```

Open `http://127.0.0.1:5173`. By default, the page sends API requests to the
Backend at `http://127.0.0.1:8000`. To use another local API address, add the
`api` query parameter, for example `http://127.0.0.1:5173/?api=http://127.0.0.1:8001`.

The Backend allows browser requests from the local frontend origins on port
5173. Its existing `http://127.0.0.1:8000/diagnostic-chat` route remains
available for same-origin use.

## Chat workflow

1. Provide a tenant ID that has diagnostic capabilities enabled. The local
   example lab tenant is `lab-001`; `clinic-001` currently does not have image
   analysis enabled by its capability policy.
2. To analyze a new item, attach a JPG or PNG image and enter a question. The
   user does not choose the image type. Follow-up questions in the same chat
   can be sent without attaching the image again.
3. The page uploads the image to `POST /api/v1/diagnostics/attachments`.
4. It sends the chat message and returned attachment ID to
   `POST /api/v1/ai/chat` with `diagnostic_mode: "auto_image"`.
5. The Backend passes the trusted image to the Diagnostic Agent, which uses the
   configured OpenAI vision model to classify it as a lab report, chest X-ray,
   brain MRI, kidney CT, or unsupported/uncertain image.
6. Supported images are sent through the existing pathology or radiology
   analysis flow. If classification confidence is low, the chat asks the user
   what kind of image it is; it does not guess. The response identifies the
   detected type before explaining the result.

Pathology extraction is not limited to CBC. It also recognizes the currently
implemented glycemic, renal, liver, and lipid panels, plus common additional
tests such as 25-OH vitamin D, ferritin, serum iron, TIBC, transferrin
saturation, vitamin B12, folate, and reticulocyte count. Additional tests are
flagged only against a readable reference range printed on that report; they
are not used alone to diagnose anemia or vitamin deficiency. Other names may
still appear as unmapped or not safely evaluated, so review extracted values
against the original image.

Messages and assistant replies are currently kept in the Backend's in-memory
conversation store. Follow-ups can use that recent text while the Backend
process remains running; restarting it clears this conversation context.

The OpenAI vision key and model configuration must be available to the
Diagnostic Agent through the Backend `.env` file. The key stays server-side and
is never sent to the browser. This automatic classifier uses OpenAI vision; a
Groq chat key by itself does not provide image classification.

Medical education searches the local knowledge files first. If they cannot
answer a recognized topic, or the user asks for recent evidence or guidelines,
the Backend may query MedlinePlus and PubMed using only a canonical medical
topic. It does not send the image, patient identifiers, or the user's full
message to those search services. External references are shown in the reply.

The upload and chat endpoints still enforce tenant permissions and patient or
encounter validation when those IDs are supplied.
