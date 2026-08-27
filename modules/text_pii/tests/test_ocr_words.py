from modules.text_pii.ocr import TextOCR
IMAGE_PATH = "data/text_pii/controlled_pii/images/case_010_multiple.jpg"
ocr = TextOCR()

results = ocr.extract_text(IMAGE_PATH)


print("\nOCR WITH WORD BOXES")
print("=" * 60)


for detection in results:

    print("\nTEXT:", detection["text"])
    print("CONFIDENCE:", detection["confidence"])
    print("LINE BBOX:", detection["bbox"])

    print("WORDS:")

    for word in detection["words"]:
        print(
            "   ",
            repr(word["text"]),
            "->",
            word["bbox"]
        )