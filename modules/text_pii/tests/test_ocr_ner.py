import spacy

from ocr import TextOCR

nlp = spacy.load("en_core_web_sm")

IMAGE_PATH = "data/text_pii/controlled_pii/images/case_007_mixed.jpg"


ocr = TextOCR()

ocr_results = ocr.extract_text(IMAGE_PATH)


print("\nOCR → NER TEST")
print("=" * 60)


for item in ocr_results:
    text = item["text"]

    print("\nOCR TEXT:", text)
    print("OCR CONFIDENCE:", item["confidence"])
    print("OCR BBOX:", item["bbox"])

    doc = nlp(text)

    if not doc.ents:
        print("NER: No entities detected.")
        continue

    for ent in doc.ents:
        print(
            "NER ENTITY:",
            ent.text,
            "| LABEL:",
            ent.label_,
            "| START:",
            ent.start_char,
            "| END:",
            ent.end_char
        )