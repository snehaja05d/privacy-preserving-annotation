from modules.text_pii.ocr import TextOCR
from modules.text_pii.pii_detector import detect_id


IMAGE_PATH = "data/text_pii/icdar2015/images/img_329.jpg"

ocr = TextOCR()

print("\nREAL IMAGE ID TEST")
print("=" * 70)
print("IMAGE:", IMAGE_PATH)

detections = ocr.extract_text(IMAGE_PATH)

for detection in detections:

    text = detection["text"]

    print("\nOCR TEXT:", text)
    print("OCR CONFIDENCE:", detection["confidence"])
    print("OCR BBOX:", detection["bbox"])

    results = detect_id(
        text,
        words=detection.get("words", []),
        confidence=detection["confidence"]
    )

    if not results:
        print("ID: None")

    else:
        for result in results:
            print("ID RESULT:", result)