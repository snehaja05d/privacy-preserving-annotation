from pathlib import Path
import cv2
import numpy as np

from PIL import Image

from modules.visual_privacy.pipeline import VisualPrivacyPipeline
from modules.text_pii.pipeline import TextPIIPipeline


class PrivacyEngine:

    # =========================================================
    # SUPPORTED PRIVACY TYPES
    # =========================================================

    SUPPORTED_TYPES = {
        "FACE",
        "PLATE",
        "EMAIL",
        "PHONE",
        "NAME",
        "ID"
    }

    # =========================================================
    # INITIALIZE
    # =========================================================

    def __init__(
        self,
        face_model_path="privacy_module/models/yolov8n_100e.pt",
        default_region="IN"
    ):

        # Visual privacy pipeline
        self.visual_pipeline = VisualPrivacyPipeline(
            face_model_path=face_model_path
        )

        # Text PII pipeline
        self.text_pipeline = TextPIIPipeline(
            default_region=default_region
        )

    # =========================================================
    # PROCESS IMAGE
    # =========================================================

    def process(
        self,
        image_path,
        output_path,
        selected_types=None
    ):

        image_path = Path(image_path)
        output_path = Path(output_path)

        # =====================================================
        # 1. VALIDATE INPUT
        # =====================================================

        if not image_path.exists():

            raise FileNotFoundError(
                f"Input image not found: {image_path}"
            )

        # =====================================================
        # 2. DETERMINE SELECTED PRIVACY TYPES
        # =====================================================

        if selected_types is None:

            selected_types = set(
                self.SUPPORTED_TYPES
            )

        else:

            selected_types = {
                str(item).upper()
                for item in selected_types
            }

            invalid_types = (
                selected_types
                - self.SUPPORTED_TYPES
            )

            if invalid_types:

                raise ValueError(
                    f"Unsupported privacy types: "
                    f"{sorted(invalid_types)}. "
                    f"Supported types are: "
                    f"{sorted(self.SUPPORTED_TYPES)}"
                )

        # =====================================================
        # 3. READ ORIGINAL IMAGE
        # =====================================================

        original_image = cv2.imread(
            str(image_path)
        )

        if original_image is None:

            raise ValueError(
                f"Could not read image: {image_path}"
            )

        # =====================================================
               # =====================================================
        # 4. VISUAL PRIVACY DETECTION
        # =====================================================

        import time
        _t0 = time.time()

        visual_result = self.visual_pipeline.process(
            image_path,
            output_path=None
        )

        print(f"[TIMING] Visual pipeline (face/plate): {time.time() - _t0:.1f}s")

        # =====================================================
        # 5. TEXT PII DETECTION
        # =====================================================

        _t1 = time.time()

        text_result = self.text_pipeline.process(
            image_path,
            output_path=None
        )

        print(f"[TIMING] Text pipeline (OCR/PII): {time.time() - _t1:.1f}s")
        print(f"[TIMING] Number of text detections: {len(text_result)}")

        # =====================================================
        # 6. FILTER VISUAL DETECTIONS
        # =====================================================

        visual_regions = []

        # -----------------------------------------------------
        # Faces
        # -----------------------------------------------------

        if "FACE" in selected_types:

            for face in visual_result.get(
                "faces",
                []
            ):

                region = face.get(
                    "bbox"
                )

                if region:

                    visual_regions.append(
                        {
                            "bbox": region,
                            "type": "face",
                            "confidence": face.get(
                                "confidence"
                            )
                        }
                    )

        # -----------------------------------------------------
        # License plates
        # -----------------------------------------------------

        if "PLATE" in selected_types:

            for plate in visual_result.get(
                "plates",
                []
            ):

                region = plate.get(
                    "bbox"
                )

                if region:

                    visual_regions.append(
                        {
                            "bbox": region,
                            "type": "plate",
                            "confidence": plate.get(
                                "confidence"
                            )
                        }
                    )

        # =====================================================
        # 7. FILTER TEXT PII DETECTIONS
        # =====================================================

        text_regions = []

        selected_text_types = {
            item
            for item in selected_types
            if item in {
                "EMAIL",
                "PHONE",
                "NAME",
                "ID"
            }
        }

        for detection in text_result:

            if detection.get(
                "status"
            ) != "CONFIRMED":

                continue

            pii_type = str(
                detection.get(
                    "pii_type",
                    ""
                )
            ).upper()

            # -------------------------------------------------
            # Ignore text PII that the user did not select
            # -------------------------------------------------

            if pii_type not in selected_text_types:

                continue

            boxes = detection.get(
                "mask_bboxes",
                []
            )

            for bbox in boxes:

                text_regions.append(
                    {
                        "bbox": bbox,
                        "type": "text_pii",
                        "pii_type": pii_type,
                        "text": detection.get(
                            "text"
                        ),
                        "confidence": detection.get(
                            "confidence"
                        )
                    }
                )

        # =====================================================
        # 8. COMBINE ALL SELECTED REGIONS
        # =====================================================

        all_regions = (
            visual_regions
            + text_regions
        )

        # =====================================================
        # 9. START MASKING FROM ORIGINAL IMAGE
        # =====================================================

        masked_image = (
            original_image.copy()
        )

        # =====================================================
        # 10. MASK VISUAL PRIVACY
        # =====================================================

        if visual_regions:

            masked_image = (
                self.visual_pipeline.masker.mask_regions(
                    masked_image,
                    visual_regions
                )
            )

        # =====================================================
        # 11. MASK TEXT PII
        # =====================================================

        pil_image = Image.fromarray(
            cv2.cvtColor(
                masked_image,
                cv2.COLOR_BGR2RGB
            )
        )

        for detection in text_result:

            if detection.get(
                "status"
            ) != "CONFIRMED":

                continue

            pii_type = str(
                detection.get(
                    "pii_type",
                    ""
                )
            ).upper()

            # Only mask selected PII types
            if pii_type not in selected_text_types:

                continue

            boxes = detection.get(
                "mask_bboxes",
                []
            )

            for bbox in boxes:

                self.text_pipeline.masker._blur_box(
                    pil_image,
                    bbox
                )

        # -----------------------------------------------------
        # Convert PIL back to OpenCV
        # -----------------------------------------------------

        masked_image = cv2.cvtColor(
            np.array(pil_image),
            cv2.COLOR_RGB2BGR
        )

        # =====================================================
        # 12. HUMAN REVIEW LOGIC
        # =====================================================

        needs_review = False

        # -----------------------------------------------------
        # Low-confidence faces
        # -----------------------------------------------------

        if "FACE" in selected_types:

            for face in visual_result.get(
                "faces",
                []
            ):

                confidence = face.get(
                    "confidence",
                    0
                )

                if confidence < 0.60:

                    needs_review = True

        # -----------------------------------------------------
        # Low-confidence license plates
        # -----------------------------------------------------

        if "PLATE" in selected_types:

            for plate in visual_result.get(
                "plates",
                []
            ):

                confidence = plate.get(
                    "confidence",
                    0
                )

                if confidence < 0.60:

                    needs_review = True

        # -----------------------------------------------------
        # Text PII alignment failure
        # -----------------------------------------------------

        for detection in text_result:

            if detection.get(
                "status"
            ) != "CONFIRMED":

                continue

            pii_type = str(
                detection.get(
                    "pii_type",
                    ""
                )
            ).upper()

            # Only selected PII matters
            if pii_type not in selected_text_types:

                continue

            # Confirmed PII without a usable
            # image location requires review.
            if not detection.get(
                "mask_bboxes",
                []
            ):

                needs_review = True

        # =====================================================
        # 13. REVIEW STATUS
        # =====================================================

        review_status = (
            "REVIEW"
            if needs_review
            else "APPROVED"
        )

        # =====================================================
        # 14. SAVE OUTPUT
        # =====================================================

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        success = cv2.imwrite(
            str(output_path),
            masked_image
        )

        if not success:

            raise IOError(
                f"Could not save output: "
                f"{output_path}"
            )

        # =====================================================
        # 15. RETURN STRUCTURED RESULT
        # =====================================================

        return {

            "input_path": str(
                image_path
            ),

            "output_path": str(
                output_path
            ),

            # User selection
            "selected_types": sorted(
                selected_types
            ),

            # Visual detections
            "faces": visual_result.get(
                "faces",
                []
            ),

            "plates": visual_result.get(
                "plates",
                []
            ),

            # Text PII detections
            "text_pii": text_result,

            # Selected masking regions
            "visual_regions": visual_regions,

            "text_regions": text_regions,

            "all_regions": all_regions,

            # Review
            "review_status": review_status,

            "needs_human_review": needs_review
        }