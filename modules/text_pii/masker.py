from PIL import Image, ImageFilter

class TextPIIMasker:
    def __init__(
        self,
        blur_radius=10
    ):
        self.blur_radius = blur_radius

    # BLUR EXACT BOX
    def _blur_box(
        self,
        image,
        bbox
    ):

        if not bbox:
            return

        if len(bbox) != 4:
            return

        x1, y1, x2, y2 = map(
            int,
            bbox
        )

        if x2 <= x1 or y2 <= y1:
            return

        crop = image.crop(
            (
                x1,
                y1,
                x2,
                y2
            )
        )

        # -----------------------------------------------------
        # Blur ONLY this crop.
        # -----------------------------------------------------

        blurred = crop.filter(
            ImageFilter.GaussianBlur(
                radius=self.blur_radius
            )
        )

        # -----------------------------------------------------
        # Put the blurred crop back at EXACTLY the same
        # coordinates.
        # -----------------------------------------------------

        image.paste(
            blurred,
            (
                x1,
                y1
            )
        )

    # =========================================================
    # MAIN MASK FUNCTION
    # =========================================================

    def mask(
        self,
        image_path,
        aligned_results,
        output_path
    ):

        image = Image.open(
            image_path
        ).convert("RGB")

        masked_entities = 0

        print()
        print("MASKING DEBUG")
        print("=" * 60)

        # -----------------------------------------------------
        # Process every detected PII entity
        # -----------------------------------------------------

        for detection in aligned_results:

            if detection.get(
                "status"
            ) != "CONFIRMED":

                continue

            boxes = detection.get(
                "mask_bboxes",
                []
            )

            if not boxes:
                continue

            print(
                f"{detection['pii_type']}: "
                f"{detection['text']}"
            )

            print(
                f"  EXACT PII BOXES: {boxes}"
            )

            # -------------------------------------------------
            # IMPORTANT:
            #
            # Blur EACH PII OCR box independently.
            #
            # We DO NOT merge them.
            # We DO NOT expand them.
            # -------------------------------------------------

            for bbox in boxes:

                self._blur_box(
                    image,
                    bbox
                )

            masked_entities += 1

        # -----------------------------------------------------
        # Save
        # -----------------------------------------------------

        image.save(
            output_path,
            quality=95
        )

        print()
        print(
            f"PII entities masked: "
            f"{masked_entities}"
        )

        return output_path