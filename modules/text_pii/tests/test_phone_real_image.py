from ocr import TextOCR
from pii_detector import detect_phone
IMAGE_PATH = "data/text_pii/controlled_pii/images/case_007_mixed.jpg"
ocr = TextOCR()
ocr_results = ocr.extract_text(IMAGE_PATH)
print("\nOCR RESULTS")
print("=" * 50)
for item in ocr_results:
    print(item)
print("\nPHONE DETECTION")
print("=" * 50)
for item in ocr_results:
    text = item["text"]
    result = detect_phone(
        text,
        default_region="IN"
    )

    if result:
        print(f"{text} -> {result}")