from paddleocr import PaddleOCR


IMAGE_PATH = "data/text_pii/controlled_pii/images/case_007_mixed.jpg"


ocr = PaddleOCR(
    lang="en"
)

results = ocr.predict(
    IMAGE_PATH,
    return_word_box=True
)


print("\nWORD-LEVEL OCR TEST")
print("=" * 60)


for result in results:

    words = result["text_word"]
    boxes = result["text_word_boxes"]

    for line_words, line_boxes in zip(words, boxes):

        print("\nLINE")
        print("-" * 40)

        for word, box in zip(line_words, line_boxes):

            print(
                "TEXT:",
                repr(word),
                "| BBOX:",
                box.tolist()
            )