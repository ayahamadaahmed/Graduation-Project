from __future__ import annotations

from dataclasses import dataclass


MAX_DIAGNOSTIC_PDF_PAGES = 12


@dataclass(frozen=True, slots=True)
class DiagnosticDocumentPage:
    filename: str
    content_type: str
    data: bytes


def prepare_diagnostic_pages(
    *,
    data: bytes,
    filename: str,
    content_type: str,
) -> list[DiagnosticDocumentPage]:
    """Return image pages for the image-based Diagnostic Agent pipeline."""
    if content_type != "application/pdf":
        return [
            DiagnosticDocumentPage(
                filename=filename,
                content_type=content_type,
                data=data,
            )
        ]

    if not data.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PDF support requires PyMuPDF in the Backend environment."
        ) from exc

    try:
        document = fitz.open(stream=data, filetype="pdf")
        try:
            if document.page_count < 1:
                raise ValueError("The PDF contains no pages.")
            if document.page_count > MAX_DIAGNOSTIC_PDF_PAGES:
                raise ValueError(
                    f"PDFs can contain at most {MAX_DIAGNOSTIC_PDF_PAGES} pages."
                )

            pages = []
            for index, page in enumerate(document):
                scale = min(
                    160 / 72,
                    2200 / max(page.rect.width, page.rect.height),
                )
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    alpha=False,
                )
                if pixmap.width * pixmap.height > 5_000_000:
                    raise ValueError("A PDF page is too large to process safely.")
                pages.append(
                    DiagnosticDocumentPage(
                        filename=f"{filename} (page {index + 1}).png",
                        content_type="image/png",
                        data=pixmap.tobytes("png"),
                    )
                )
            return pages
        finally:
            document.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The PDF could not be read.") from exc
