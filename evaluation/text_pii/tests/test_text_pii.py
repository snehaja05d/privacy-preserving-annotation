from pathlib import Path
from PIL import Image

from modules.text_pii.pipeline import TextPIIPipeline


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "text_pii"
    / "controlled_pii"
    / "images"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "evaluation"
    / "text_pii"
    / "outputs"
    / "masked"
)

RESULTS_DIR = (
    PROJECT_ROOT
    / "evaluation"
    / "text_pii"
    / "results"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

RESULTS_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# CONTROLLED DATASET
# ============================================================

TEST_IMAGES = [
    "case_001_name.jpg",
    "case_002_phone.jpg",
    "case_003_email.jpg",
    "case_004_address.jpg",
    "case_005_id.jpg",
    "case_006_no_pii.jpg",
    "case_007_mixed.jpg",
    "case_008_business.jpg",
    "case_009_date.jpg",
    "case_010_multiple.jpg",
]


# ============================================================
# PIPELINE
# ============================================================

pipeline = TextPIIPipeline(
    default_region="IN"
)


# ============================================================
# RUN TESTS
# ============================================================

results = []

print()
print("=" * 70)
print("TEXT-PII CONTROLLED DATASET EVALUATION")
print("=" * 70)


for image_name in TEST_IMAGES:

    input_path = INPUT_DIR / image_name

    output_path = OUTPUT_DIR / (
        f"masked_{image_name}"
    )

    print()
    print("-" * 70)
    print(f"TEST IMAGE: {image_name}")
    print("-" * 70)

    if not input_path.exists():

        print(
            f"ERROR: Image not found: "
            f"{input_path}"
        )

        results.append({
            "image": image_name,
            "status": "FILE_NOT_FOUND"
        })

        continue

    try:

        detections = pipeline.process(
            image_path=str(input_path),
            output_path=str(output_path)
        )

        confirmed = [
            d for d in detections
            if d.get("status") == "CONFIRMED"
        ]

        print(
            f"Confirmed PII entities: "
            f"{len(confirmed)}"
        )

        for detection in confirmed:

            print(
                f"  {detection.get('pii_type')}: "
                f"{detection.get('text')}"
            )

            print(
                f"  Mask boxes: "
                f"{detection.get('mask_bboxes')}"
            )

        if output_path.exists():

            print(
                f"Output saved: "
                f"{output_path}"
            )

            status = "PASS"

        else:

            print(
                "ERROR: Output image was not created."
            )

            status = "FAIL"

        results.append({
            "image": image_name,
            "status": status,
            "pii_entities": len(confirmed),
            "output": str(output_path)
        })

    except Exception as e:

        print(
            f"ERROR while processing: {e}"
        )

        results.append({
            "image": image_name,
            "status": "ERROR",
            "error": str(e)
        })


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 70)
print("EVALUATION SUMMARY")
print("=" * 70)

total = len(results)

passed = sum(
    1
    for r in results
    if r["status"] == "PASS"
)

failed = sum(
    1
    for r in results
    if r["status"] != "PASS"
)

print(f"Total images : {total}")
print(f"Passed       : {passed}")
print(f"Failed       : {failed}")

print()
print("Evaluation complete.")