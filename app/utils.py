import fitz  # PyMuPDF


def load_pdf_from_bytes(data: bytes) -> fitz.Document:
    """Open a PDF from raw bytes using PyMuPDF."""
    return fitz.open(stream=data, filetype="pdf")
