from modules.text_pii.ocr import TextOCR
from modules.text_pii.pii_detector import (
    detect_email,
    detect_phone,
    detect_name,
    detect_id
)
from modules.text_pii.pii_aligner import PIIBBoxAligner


IMAGE_PATH = (
    "data/text_pii/controlled_pii/images/"
    "case_010_multiple.jpg"
)


ocr = TextOCR()

ocr_results = ocr.extract_text(
    IMAGE_PATH
)

aligner = PIIBBoxAligner()

all_pii = []


for detection in ocr_results:

    text = detection["text"]
    confidence = detection["confidence"]
    words = detection.get(
        "words",
        []
    )

    all_pii.extend(
        detect_email(
            text,
            words=words,
            confidence=confidence
        )
    )

    all_pii.extend(
        detect_phone(
            text,
            words=words,
            confidence=confidence
        )
    )

    all_pii.extend(
        detect_name(
            text,
            words
        )
    )

    all_pii.extend(
        detect_id(
            text,
            words=words,
            confidence=confidence
        )
    )


aligned = aligner.align(
    all_pii,
    ocr_results
)


print("\nPII ALIGNMENT TEST")
print("=" * 70)


for result in aligned:

    print(
        f"\nTYPE: {result['pii_type']}"
    )

    print(
        f"TEXT: {result['text']}"
    )

    print(
        "MASK WORDS:",
        result["mask_words"]
    )

    print(
        "MASK BOXES:",
        result["mask_bboxes"]
    )