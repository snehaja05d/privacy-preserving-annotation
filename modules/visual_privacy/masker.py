import cv2


class VisualPrivacyMasker:

    def __init__(
        self,
        pixel_size=6
    ):
        self.pixel_size = pixel_size

    # =========================================================
    # MASK FACES / PLATES
    # =========================================================

    def mask_regions(
        self,
        image,
        regions
    ):
        """
        Pixelate detected visual privacy regions.

        regions:
            [
                {
                    "bbox": [x1, y1, x2, y2],
                    "type": "face"
                },
                {
                    "bbox": [x1, y1, x2, y2],
                    "type": "plate"
                }
            ]
        """

        result = image.copy()

        for region in regions:

            bbox = region.get("bbox")

            if not bbox:
                continue

            x1, y1, x2, y2 = bbox

            h, w = result.shape[:2]

            # Keep coordinates inside image
            x1 = max(0, min(x1, w))
            x2 = max(0, min(x2, w))

            y1 = max(0, min(y1, h))
            y2 = max(0, min(y2, h))

            if x2 <= x1 or y2 <= y1:
                continue

            crop = result[y1:y2, x1:x2]

            if crop.size == 0:
                continue

            # Strong pixelation
            small = cv2.resize(
                crop,
                (self.pixel_size, self.pixel_size),
                interpolation=cv2.INTER_AREA
            )

            pixelated = cv2.resize(
                small,
                (crop.shape[1], crop.shape[0]),
                interpolation=cv2.INTER_NEAREST
            )

            result[y1:y2, x1:x2] = pixelated

        return result