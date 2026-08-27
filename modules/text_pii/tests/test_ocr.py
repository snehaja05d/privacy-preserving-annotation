from ocr import TextOCR


image_path = "data/text_pii/controlled_pii/images/case_007_mixed.jpg"

ocr = TextOCR()

results = ocr.extract_text(image_path)

for item in results:
    print(item)