from modules.text_pii.ocr import TextOCR
from modules.text_pii.pii_detector import detect_id


IMAGE_PATHS = [
    "data/text_pii/controlled_pii/images/case_005_id.jpg",
    "data/text_pii/controlled_pii/images/case_010_multiple.jpg",
]


ocr = TextOCR()

print("\nID DETECTOR TEST")
print("=" * 70)

for image_path in IMAGE_PATHS:

    print("\nIMAGE:", image_path)

    detections = ocr.extract_text(image_path)

    for detection in detections:

        text = detection["text"]

        print(f"\nOCR TEXT: {text}")

        results = detect_id(
            text,
            words=detection.get("words", []),
            confidence=detection["confidence"]
        )

        if not results:
            print("No ID detected.")

        else:
            for result in results:
                print("ID RESULT:", result)