import cv2

from modules.visual_privacy.detector import VisualPrivacyDetector
from modules.visual_privacy.masker import VisualPrivacyMasker


class VisualPrivacyPipeline:

    def __init__(
        self,
        face_model_path,
        face_confidence=0.25,
        plate_confidence=0.10,
        pixel_size=6
    ):

        # ---------------------------------------------
        # Detector
        # ---------------------------------------------

        self.detector = VisualPrivacyDetector(
            face_model_path=face_model_path,
            face_confidence=face_confidence,
            plate_confidence=plate_confidence
        )

        # ---------------------------------------------
        # Masker
        # ---------------------------------------------

        self.masker = VisualPrivacyMasker(
            pixel_size=pixel_size
        )

    # =================================================
    # PROCESS
    # =================================================

    def process(
        self,
        image_path,
        output_path=None
    ):

        # ---------------------------------------------
        # 1. Read image
        # ---------------------------------------------

        image = cv2.imread(
            str(image_path)
        )

        if image is None:
            raise ValueError(
                f"Could not read image: {image_path}"
            )

        # ---------------------------------------------
        # 2. Detect faces + plates
        # ---------------------------------------------

        detections = self.detector.detect(
            image_path,
            image
        )

        # ---------------------------------------------
        # 3. Convert detections into mask regions
        # ---------------------------------------------

        regions = []

        for face in detections["faces"]:

            regions.append(
                {
                    "bbox": face["bbox"],
                    "type": "face",
                    "confidence": face["confidence"]
                }
            )

        for plate in detections["plates"]:

            regions.append(
                {
                    "bbox": plate["bbox"],
                    "type": "plate",
                    "confidence": plate["confidence"]
                }
            )

        # ---------------------------------------------
        # 4. Mask
        # ---------------------------------------------

        masked_image = self.masker.mask_regions(
            image,
            regions
        )

        # ---------------------------------------------
        # 5. Save
        # ---------------------------------------------

        if output_path:

            success = cv2.imwrite(
                str(output_path),
                masked_image
            )

            if not success:
                raise IOError(
                    f"Could not save output: {output_path}"
                )

        # ---------------------------------------------
        # 6. Return structured result
        # ---------------------------------------------

        return {
            "faces": detections["faces"],
            "plates": detections["plates"],
            "regions": regions,
            "image": masked_image,
            "output_path": str(output_path)
            if output_path
            else None
        }