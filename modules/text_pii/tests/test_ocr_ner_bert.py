from transformers import pipeline

from ocr import TextOCR


ner = pipeline(
    "ner",
    model="dslim/bert-base-NER",
    aggregation_strategy="simple"
)

IMAGE_PATH = "data/text_pii/controlled_pii/images/case_007_mixed.jpg"

ocr = TextOCR()
ocr_results = ocr.extract_text(IMAGE_PATH)


print("\nOCR → BERT NER TEST")
print("=" * 60)


for item in ocr_results:

    text = item["text"]

    print("\nOCR TEXT:", text)
    print("OCR CONFIDENCE:", item["confidence"])
    print("OCR BBOX:", item["bbox"])

    results = ner(text)

    if not results:
        print("NER: No entities detected.")
        continue

    for entity in results:
        print(
            "NER ENTITY:", entity["word"],
            "| LABEL:", entity["entity_group"],
            "| SCORE:", round(entity["score"], 4),
            "| START:", entity["start"],
            "| END:", entity["end"]
        )