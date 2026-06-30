from pypdf import PdfReader


def load_pdf(pdf_path):

    reader = PdfReader(pdf_path)

    text = ""

    for page in reader.pages:
        page_text = page.extract_text()

        if page_text:
            text += page_text + "\n"

    return text


def get_pdf_page_count(pdf_path):
    """Phase 2 addition: used by the /documents API to report page counts."""

    reader = PdfReader(pdf_path)

    return len(reader.pages)