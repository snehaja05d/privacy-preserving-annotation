from modules.text_pii.ocr import TextOCR
from modules.text_pii.pii_detector import (
    detect_email,
    detect_phone,
    detect_name
)


IMAGE_PATH = "data/text_pii/controlled_pii/images/case_007_mixed.jpg"


ocr = TextOCR()

detections = ocr.extract_text(IMAGE_PATH)


print("\nPII BBOX TEST")
print("=" * 70)


for detection in detections:

    text = detection["text"]
    words = detection["words"]
    confidence = detection["confidence"]

    print("\nOCR TEXT:", text)

    emails = detect_email(
        text,
        words,
        confidence
    )

    phones = detect_phone(
        text,
        words=words,
        confidence=confidence
    )

    names = detect_name(
        text,
        words
    )

    for result in emails:
        print("EMAIL:", result)

    for result in phones:
        print("PHONE:", result)

    for result in names:
        print("NAME:", result)