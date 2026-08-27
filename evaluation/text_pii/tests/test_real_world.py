from pathlib import Path
import csv
import json
import time

from modules.text_pii.pipeline import TextPIIPipeline


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "text_pii"
    / "icdar2015"
    / "selected"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "evaluation"
    / "text_pii"
    / "outputs"
    / "icdar2015"
    / "masked"
)

RESULT_DIR = (
    PROJECT_ROOT
    / "evaluation"
    / "text_pii"
    / "results"
    / "icdar2015"
)


# ============================================================
# SUPPORTED IMAGE TYPES
# ============================================================

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp"
}


# ============================================================
# SETUP
# ============================================================

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

RESULT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# FIND SELECTED ICDAR IMAGES
# ============================================================

images = sorted(
    [
        path
        for path in INPUT_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
)


# ============================================================
# CHECK DATASET
# ============================================================

if not images:

    print()
    print("=" * 70)
    print("NO IMAGES FOUND")
    print("=" * 70)
    print()
    print(f"Expected selected images in:")
    print(INPUT_DIR)
    print()

    raise SystemExit(1)


# ============================================================
# START PIPELINE
# ============================================================

pipeline = TextPIIPipeline(
    default_region=None
)


# ============================================================
# RESULTS
# ============================================================

results = []

total_images = len(images)
successful_images = 0
failed_images = 0

total_pii_entities = 0


print()
print("=" * 70)
print("ICDAR2015 SELECTED DATASET EVALUATION")
print("=" * 70)

print()
print(f"Input directory : {INPUT_DIR}")
print(f"Output directory: {OUTPUT_DIR}")
print(f"Total images    : {total_images}")

print()
print("=" * 70)


# ============================================================
# PROCESS EACH IMAGE
# ============================================================

for index, image_path in enumerate(images, start=1):

    print()
    print("-" * 70)
    print(
        f"[{index}/{total_images}] "
        f"{image_path.name}"
    )
    print("-" * 70)

    output_path = (
        OUTPUT_DIR
        / f"masked_{image_path.name}"
    )

    start_time = time.time()

    try:

        aligned_results = pipeline.process(
            str(image_path),
            str(output_path)
        )

        elapsed_time = (
            time.time() - start_time
        )

        pii_count = len(
            aligned_results
        )

        total_pii_entities += pii_count

        successful_images += 1

        print()
        print(
            f"PII entities detected: "
            f"{pii_count}"
        )

        print(
            f"Output saved: "
            f"{output_path}"
        )

        print(
            f"Processing time: "
            f"{elapsed_time:.2f} seconds"
        )

        # ----------------------------------------------------
        # Store detailed result
        # ----------------------------------------------------

        detected_entities = []

        for entity in aligned_results:

            detected_entities.append({

                "pii_type": entity.get(
                    "pii_type"
                ),

                "text": entity.get(
                    "text"
                ),

                "confidence": entity.get(
                    "confidence"
                ),

                "mask_words": entity.get(
                    "mask_words",
                    []
                ),

                "mask_bboxes": entity.get(
                    "mask_bboxes",
                    []
                )

            })

        results.append({

            "image": image_path.name,

            "status": "SUCCESS",

            "pii_entities": pii_count,

            "processing_time_seconds": round(
                elapsed_time,
                3
            ),

            "output": str(
                output_path
            ),

            "detections": detected_entities

        })

    except Exception as error:

        failed_images += 1

        elapsed_time = (
            time.time() - start_time
        )

        print()
        print(
            f"ERROR processing "
            f"{image_path.name}"
        )

        print(
            str(error)
        )

        results.append({

            "image": image_path.name,

            "status": "FAILED",

            "pii_entities": 0,

            "processing_time_seconds": round(
                elapsed_time,
                3
            ),

            "output": None,

            "error": str(error),

            "detections": []

        })


# ============================================================
# SAVE JSON RESULTS
# ============================================================

json_path = (
    RESULT_DIR
    / "icdar2015_results.json"
)

with open(
    json_path,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        results,
        file,
        indent=4,
        ensure_ascii=False
    )


# ============================================================
# SAVE CSV SUMMARY
# ============================================================

csv_path = (
    RESULT_DIR
    / "icdar2015_summary.csv"
)

with open(
    csv_path,
    "w",
    newline="",
    encoding="utf-8"
) as file:

    writer = csv.writer(file)

    writer.writerow([
        "image",
        "status",
        "pii_entities",
        "processing_time_seconds",
        "output"
    ])

    for result in results:

        writer.writerow([

            result.get(
                "image"
            ),

            result.get(
                "status"
            ),

            result.get(
                "pii_entities"
            ),

            result.get(
                "processing_time_seconds"
            ),

            result.get(
                "output"
            )

        ])


# ============================================================
# FINAL SUMMARY
# ============================================================

print()
print()
print("=" * 70)
print("ICDAR2015 EVALUATION SUMMARY")
print("=" * 70)

print(
    f"Total images processed : "
    f"{total_images}"
)

print(
    f"Successful             : "
    f"{successful_images}"
)

print(
    f"Failed                 : "
    f"{failed_images}"
)

print(
    f"PII entities detected  : "
    f"{total_pii_entities}"
)

print()
print(
    f"Masked images:"
)

print(
    OUTPUT_DIR
)

print()
print(
    f"Detailed JSON results:"
)

print(
    json_path
)

print()
print(
    f"CSV summary:"
)

print(
    csv_path
)

print()
print("=" * 70)
print("ICDAR2015 EVALUATION COMPLETE")
print("=" * 70)