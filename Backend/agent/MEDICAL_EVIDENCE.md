# Medical evidence retrieval

The medical education path now uses a local-first retrieval policy:

1. Search the tenant's curated medical education Markdown files.
2. Search MedlinePlus when the local collection cannot answer a recognized
   medical topic.
3. Also search recent PubMed-indexed publications when the user explicitly
   asks for recent evidence or guidelines. Guideline requests apply PubMed's
   publication-type filter; an indexed result still needs review and is not
   automatically a current local standard of care.
4. Ask the configured response model to summarize retrieved text and append
   exact source titles, publishers, dates when available, and URLs.

Only a canonical topic from `MedicalEvidenceRetriever.TOPIC_ALIASES` is sent to
these public services. The user's message, symptoms narrative, image, report
values, patient identifiers, and conversation history are not sent to the
search APIs. Topic coverage is intentionally allowlisted; an unrecognized
topic does not trigger an unrestricted external search.

The adapters use the public MedlinePlus Web Service and NCBI E-utilities. They
need outbound HTTPS access but no API key for this low request volume. Results
are cached in memory for 12 hours. Set
`MEDMIND_EXTERNAL_MEDICAL_SEARCH_ENABLED=0` in the Backend environment to turn
external retrieval off. If a source is unavailable, the local knowledge path
continues to work and the system must not claim that it checked current
evidence.

This provides sourced educational retrieval, not symptom diagnosis, clinical
triage, or a continuously maintained clinical guideline service. Official
guidelines relevant to the deployment country still need to be curated,
versioned, and reviewed by qualified clinicians.
