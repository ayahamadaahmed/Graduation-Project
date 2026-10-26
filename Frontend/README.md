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

1. Choose a modality and provide the clinic tenant ID.
2. Select a JPG or PNG image and enter a question.
3. The page uploads the image to `POST /api/v1/diagnostics/attachments`.
4. It sends the chat message and returned attachment ID to
   `POST /api/v1/ai/chat`.
5. The Backend validates the clinic, coordinates the diagnostic and chat
   services, and returns the response to the page.

The local SQL database currently has the schema but no clinic data. A matching
provider row must exist for the tenant ID before the integrated upload/chat
endpoints can be exercised successfully.
