from modules.text_pii.ocr import TextOCR


IMAGE_PATH = (
    "data/text_pii/controlled_pii/images/"
    "case_010_multiple.jpg"
)


ocr = TextOCR()

results = ocr.extract_text(
    IMAGE_PATH
)

print()
print(
    "OCR CHARACTER BOX TEST"
)
print("=" * 70)

for result in results:

    print()
    print(
        "TEXT:",
        result["text"]
    )

    print(
        "CHARACTERS:"
    )

    for character in result.get(
        "characters",
        []
    ):

        print(
            f"    "
            f"{character['text']!r}"
            f" -> "
            f"{character['bbox']}"
        )