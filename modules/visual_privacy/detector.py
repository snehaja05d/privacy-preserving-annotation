from pathlib import Path

from ultralytics import YOLO
from open_image_models import create_detector


class VisualPrivacyDetector:

    def __init__(
        self,
        face_model_path,
        face_confidence=0.25,
        plate_confidence=0.10
    ):
        self.face_confidence = face_confidence
        self.plate_confidence = plate_confidence

        # Face detector
        self.face_model = YOLO(
            str(Path(face_model_path))
        )

        # License plate detector
        self.plate_detector = create_detector(
            "yolo-v9-s-608-license-plate-end2end",
            conf_thresh=plate_confidence
        )

    def detect(self, image_path, image):
        """
        Detect faces and license plates.

        Returns:
            {
                "faces": [...],
                "plates": [...]
            }
        """

        faces = self._detect_faces(
            image_path
        )

        plates = self._detect_plates(
            image
        )

        return {
            "faces": faces,
            "plates": plates
        }

    def _detect_faces(self, image_path):

        results = self.face_model(
            str(image_path),
            conf=self.face_confidence,
            imgsz=1536,
            augment=True,
            verbose=False
        )

        detections = []

        for detection in results[0].boxes:

            confidence = float(
                detection.conf[0]
            )

            x1, y1, x2, y2 = map(
                int,
                detection.xyxy[0]
            )

            detections.append(
                {
                    "bbox": [x1, y1, x2, y2],
                    "confidence": confidence
                }
            )

        return detections

    def _detect_plates(self, image):

        results = self.plate_detector.predict(
            image.copy()
        )

        detections = []

        for result in results:

            confidence = float(
                result.confidence
            )

            box = result.bounding_box

            detections.append(
                {
                    "bbox": [
                        int(box.x1),
                        int(box.y1),
                        int(box.x2),
                        int(box.y2)
                    ],
                    "confidence": confidence
                }
            )

        return detections