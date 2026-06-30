from backend.rag.pdf_loader import load_pdf

text = load_pdf("data/documents/sample.pdf")

print(text[:1000])