from ocr import TextOCR
from pii_detector import detect_name


IMAGE_PATH = "data/text_pii/controlled_pii/images/case_007_mixed.jpg"


ocr = TextOCR()

ocr_results = ocr.extract_text(IMAGE_PATH)


print("\nACTUAL NAME DETECTOR TEST")
print("=" * 70)


for detection in ocr_results:

    text = detection["text"]
    words = detection["words"]

    print("\nOCR TEXT:", text)

    results = detect_name(text, words)

    if results:
        for result in results:
            print("NAME RESULT:", result)
    else:
        print("No name detected.")