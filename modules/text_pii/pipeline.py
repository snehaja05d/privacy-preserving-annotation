from modules.text_pii.ocr import TextOCR

from modules.text_pii.pii_detector import (
    detect_email,
    detect_phone,
    detect_name,
    detect_id
)

from modules.text_pii.pii_aligner import (
    PIIBBoxAligner
)

from modules.text_pii.masker import (
    TextPIIMasker
)


class TextPIIPipeline:

    def __init__(
        self,
        default_region=None
    ):

        self.default_region = default_region

        self.ocr = TextOCR()

        self.aligner = PIIBBoxAligner()

        self.masker = TextPIIMasker(
            blur_radius=10
        )

    # =========================================================
    # PROCESS
    # =========================================================

    def process(
        self,
        image_path,
        output_path=None
    ):

        # =====================================================
        # 1. OCR
        # =====================================================

        ocr_results = self.ocr.extract_text(
            image_path
        )

        if not ocr_results:
            print("WARNING: OCR returned no text.")
            return []

        # =====================================================
        # 2. DETECT PII
        # =====================================================

        all_pii = []

        for detection in ocr_results:

            text = detection.get(
                "text",
                ""
            )

            confidence = detection.get(
                "confidence",
                0.0
            )

            words = detection.get(
                "words",
                []
            )

            # -------------------------------------------------
            # EMAIL
            # -------------------------------------------------

            all_pii.extend(
                detect_email(
                    text,
                    words=words,
                    confidence=confidence
                )
            )

            # -------------------------------------------------
            # PHONE
            # -------------------------------------------------

            all_pii.extend(
                detect_phone(
                    text,
                    default_region=self.default_region,
                    words=words,
                    confidence=confidence
                )
            )

            # -------------------------------------------------
            # NAME
            # -------------------------------------------------

            all_pii.extend(
                detect_name(
                    text,
                    words
                )
            )

            # -------------------------------------------------
            # ID
            # -------------------------------------------------

            all_pii.extend(
                detect_id(
                    text,
                    words=words,
                    confidence=confidence
                )
            )

        # =====================================================
        # 3. ALIGN
        # =====================================================

        aligned_results = self.aligner.align(
            all_pii,
            ocr_results
        )

        # =====================================================
        # 4. MASK
        # =====================================================

        if output_path:

            self.masker.mask(
                image_path,
                aligned_results,
                output_path
            )

        return aligned_results