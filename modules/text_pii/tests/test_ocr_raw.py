from modules.text_pii.ocr import TextOCR


IMAGE = (
    "data/text_pii/controlled_pii/images/"
    "case_010_multiple.jpg"
)


ocr = TextOCR()

results = ocr.extract_text(
    IMAGE
)

print()
print("RAW OCR TEST")
print("=" * 70)

for item in results:

    print()
    print("TEXT:", item["text"])
    print("BOX :", item["bbox"])

    print("WORDS:")

    for word in item.get(
        "words",
        []
    ):

        print(
            "   ",
            repr(word["text"]),
            "->",
            word["bbox"]
        )