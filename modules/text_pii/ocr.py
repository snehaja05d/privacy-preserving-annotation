import os

# =========================================================
# Paddle / CPU compatibility
# =========================================================

# Disable PaddleX default MKLDNN selection.
# Helps avoid oneDNN issues on some CPU environments.
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"


from pathlib import Path
import tempfile

from PIL import Image
from paddleocr import PaddleOCR


class TextOCR:

    def __init__(self):

        # =====================================================
        # Configuration
        # =====================================================

        self.MAX_OCR_SIDE = 1600

        # =====================================================
        # PaddleOCR
        # =====================================================

        self.ocr = PaddleOCR(

            # English OCR
            lang="en",

            # Explicit PP-OCRv5 models
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="en_PP-OCRv5_mobile_rec",

            # Keep coordinates aligned with original image
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,

            # Required for PII alignment
            return_word_box=True,

            # OCR detection size
            text_det_limit_side_len=self.MAX_OCR_SIDE,

            # Disable MKLDNN explicitly
            enable_mkldnn=False,
        )

    # =========================================================
    # OCR
    # =========================================================

    def extract_text(self, image_path):

        image_path = Path(image_path)

        # =====================================================
        # Read original image dimensions
        # =====================================================

        with Image.open(image_path) as img:

            original_width, original_height = img.size

        # =====================================================
        # Determine whether resizing is necessary
        # =====================================================

        longest_side = max(
            original_width,
            original_height
        )

        temp_path = None

        scale_x = 1.0
        scale_y = 1.0

        if longest_side > self.MAX_OCR_SIDE:

            scale = (
                self.MAX_OCR_SIDE /
                float(longest_side)
            )

            resized_width = max(
                1,
                int(round(
                    original_width * scale
                ))
            )

            resized_height = max(
                1,
                int(round(
                    original_height * scale
                ))
            )

            # -------------------------------------------------
            # Resize image
            # -------------------------------------------------

            with Image.open(image_path) as img:

                # Ensure consistent input format
                img = img.convert("RGB")

                resized = img.resize(
                    (
                        resized_width,
                        resized_height
                    ),
                    Image.Resampling.LANCZOS
                )

                with tempfile.NamedTemporaryFile(
                    suffix=".jpg",
                    delete=False
                ) as temp_file:

                    temp_path = Path(
                        temp_file.name
                    )

                resized.save(
                    temp_path,
                    "JPEG",
                    quality=95
                )

            ocr_image_path = temp_path

            # -------------------------------------------------
            # Coordinate conversion factors
            # -------------------------------------------------

            scale_x = (
                original_width /
                float(resized_width)
            )

            scale_y = (
                original_height /
                float(resized_height)
            )

            print(
                f"OCR: resized "
                f"{original_width}x{original_height} "
                f"-> "
                f"{resized_width}x{resized_height}"
            )

        else:

            ocr_image_path = image_path

        # =====================================================
        # Run OCR
        # =====================================================

        try:

            result = self.ocr.predict(
                str(ocr_image_path)
            )

        finally:

            # -------------------------------------------------
            # Remove temporary image
            # -------------------------------------------------

            if (
                temp_path is not None
                and temp_path.exists()
            ):

                try:
                    temp_path.unlink()
                except OSError:
                    pass

        # =====================================================
        # No OCR result
        # =====================================================

        if not result:

            return []

        page_result = result[0]

        # =====================================================
        # Extract OCR fields
        # =====================================================

        texts = page_result.get(
            "rec_texts",
            []
        )

        scores = page_result.get(
            "rec_scores",
            []
        )

        boxes = page_result.get(
            "rec_boxes",
            []
        )

        word_texts = page_result.get(
            "text_word",
            []
        )

        word_boxes = page_result.get(
            "text_word_boxes",
            []
        )

        detections = []

        # =====================================================
        # Process OCR detections
        # =====================================================

        for i, text in enumerate(texts):

            # -------------------------------------------------
            # Confidence
            # -------------------------------------------------

            score = (
                float(scores[i])
                if i < len(scores)
                else 0.0
            )

            # -------------------------------------------------
            # Detection bounding box
            # -------------------------------------------------

            box = None

            if i < len(boxes):

                raw_box = (
                    boxes[i].tolist()
                    if hasattr(
                        boxes[i],
                        "tolist"
                    )
                    else list(boxes[i])
                )

                if len(raw_box) >= 4:

                    box = [

                        int(round(
                            raw_box[0] * scale_x
                        )),

                        int(round(
                            raw_box[1] * scale_y
                        )),

                        int(round(
                            raw_box[2] * scale_x
                        )),

                        int(round(
                            raw_box[3] * scale_y
                        ))

                    ]

            # -------------------------------------------------
            # Word-level boxes
            # -------------------------------------------------

            words = []

            if (
                i < len(word_texts)
                and i < len(word_boxes)
            ):

                current_words = word_texts[i]
                current_boxes = word_boxes[i]

                for word, word_box in zip(
                    current_words,
                    current_boxes
                ):

                    raw_word_box = (

                        word_box.tolist()

                        if hasattr(
                            word_box,
                            "tolist"
                        )

                        else list(word_box)

                    )

                    if len(raw_word_box) >= 4:

                        converted_word_box = [

                            int(round(
                                raw_word_box[0] *
                                scale_x
                            )),

                            int(round(
                                raw_word_box[1] *
                                scale_y
                            )),

                            int(round(
                                raw_word_box[2] *
                                scale_x
                            )),

                            int(round(
                                raw_word_box[3] *
                                scale_y
                            ))

                        ]

                    else:

                        converted_word_box = raw_word_box

                    words.append({

                        "text": str(word),

                        "bbox": converted_word_box

                    })

            # -------------------------------------------------
            # Final detection
            # -------------------------------------------------

            detections.append({

                "text": str(text),

                "confidence": score,

                "bbox": box,

                "words": words

            })

        return detections