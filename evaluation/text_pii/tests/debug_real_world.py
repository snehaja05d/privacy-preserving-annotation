import os

from PIL import Image, ImageDraw, ImageFont

from modules.text_pii.pipeline import TextPIIPipeline


# =========================================================
# PATHS
# =========================================================

INPUT_DIR = "data/text_pii/icdar2015/selected"

DEBUG_OUTPUT_DIR = (
    "evaluation/text_pii/outputs/icdar2015/debug"
)


# =========================================================
# CREATE OUTPUT DIRECTORY
# =========================================================

os.makedirs(
    DEBUG_OUTPUT_DIR,
    exist_ok=True
)


# =========================================================
# DEBUG DRAWING
# =========================================================

def draw_debug_boxes(
    image_path,
    aligned_results,
    output_path
):

    image = Image.open(
        image_path
    ).convert("RGB")

    draw = ImageDraw.Draw(
        image
    )

    # -----------------------------------------------------
    # Try to use a readable font.
    # If unavailable, PIL uses its default font.
    # -----------------------------------------------------

    try:

        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            24
        )

    except:

        font = ImageFont.load_default()

    # -----------------------------------------------------
    # Draw every confirmed PII detection
    # -----------------------------------------------------

    for detection in aligned_results:

        pii_type = detection.get(
            "pii_type",
            "PII"
        )

        text = detection.get(
            "text",
            ""
        )

        boxes = detection.get(
            "mask_bboxes",
            []
        )

        for bbox in boxes:

            if not bbox or len(bbox) != 4:
                continue

            x1, y1, x2, y2 = map(
                int,
                bbox
            )

            # -------------------------------------------------
            # RED rectangle around detected PII
            # -------------------------------------------------

            draw.rectangle(
                (
                    x1,
                    y1,
                    x2,
                    y2
                ),
                outline="red",
                width=4
            )

            # -------------------------------------------------
            # Label
            # -------------------------------------------------

            label = (
                f"{pii_type}: {text}"
            )

            # Calculate label size
            try:

                label_box = draw.textbbox(
                    (0, 0),
                    label,
                    font=font
                )

                label_width = (
                    label_box[2]
                    - label_box[0]
                )

                label_height = (
                    label_box[3]
                    - label_box[1]
                )

            except:

                label_width = len(label) * 10
                label_height = 20

            # -------------------------------------------------
            # Put label above the box where possible
            # -------------------------------------------------

            label_x = x1

            label_y = (
                y1
                - label_height
                - 8
            )

            if label_y < 0:
                label_y = y2 + 5

            # -------------------------------------------------
            # Label background
            # -------------------------------------------------

            draw.rectangle(
                (
                    label_x,
                    label_y,
                    label_x + label_width + 10,
                    label_y + label_height + 6
                ),
                fill="red"
            )

            # -------------------------------------------------
            # Label text
            # -------------------------------------------------

            draw.text(
                (
                    label_x + 5,
                    label_y + 3
                ),
                label,
                fill="white",
                font=font
            )

    # =====================================================
    # SAVE
    # =====================================================

    image.save(
        output_path,
        quality=95
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 70)
    print("ICDAR2015 PII DEBUG EVALUATION")
    print("=" * 70)

    # -----------------------------------------------------
    # Create pipeline
    # -----------------------------------------------------

    pipeline = TextPIIPipeline()

    # -----------------------------------------------------
    # Get selected images
    # -----------------------------------------------------

    if not os.path.exists(INPUT_DIR):

        print(
            f"ERROR: Input directory not found:"
        )

        print(
            INPUT_DIR
        )

        return

    image_files = sorted(
        [
            filename
            for filename in os.listdir(
                INPUT_DIR
            )
            if filename.lower().endswith(
                (
                    ".jpg",
                    ".jpeg",
                    ".png"
                )
            )
        ]
    )

    print()
    print(
        f"Selected images found: "
        f"{len(image_files)}"
    )

    print()

    # -----------------------------------------------------
    # Process each selected image
    # -----------------------------------------------------

    for filename in image_files:

        image_path = os.path.join(
            INPUT_DIR,
            filename
        )

        debug_filename = (
            "debug_"
            + filename
        )

        debug_path = os.path.join(
            DEBUG_OUTPUT_DIR,
            debug_filename
        )

        print("-" * 70)

        print(
            f"IMAGE: {filename}"
        )

        # -------------------------------------------------
        # Run OCR + PII detection + alignment
        #
        # We DO NOT save a masked image here.
        # This script is only for debugging detections.
        # -------------------------------------------------

        aligned_results = pipeline.process(
            image_path,
            output_path=None
        )

        # -------------------------------------------------
        # Print detections
        # -------------------------------------------------

        if not aligned_results:

            print(
                "  PII DETECTIONS: NONE"
            )

        else:

            print(
                f"  PII DETECTIONS: "
                f"{len(aligned_results)}"
            )

            for detection in aligned_results:

                print(
                    f"  - {detection.get('pii_type')}: "
                    f"{detection.get('text')}"
                )

                print(
                    f"    Boxes: "
                    f"{detection.get('mask_bboxes')}"
                )

        # -------------------------------------------------
        # Draw debug boxes
        # -------------------------------------------------

        draw_debug_boxes(
            image_path,
            aligned_results,
            debug_path
        )

        print(
            f"  Debug output: "
            f"{debug_path}"
        )

    # =====================================================
    # COMPLETE
    # =====================================================

    print()
    print("=" * 70)

    print(
        "DEBUG EVALUATION COMPLETE"
    )

    print(
        f"Debug images saved in:"
    )

    print(
        DEBUG_OUTPUT_DIR
    )

    print("=" * 70)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()