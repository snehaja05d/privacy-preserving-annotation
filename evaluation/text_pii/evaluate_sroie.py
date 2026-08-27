import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

GROUND_TRUTH = (
    BASE_DIR
    / "data"
    / "text_pii"
    / "sroie_text_pii"
    / "sroie_text_ground_truth.csv"
)

CANDIDATES = (
    BASE_DIR
    / "data"
    / "text_pii"
    / "sroie_text_pii"
    / "pii_candidates_experiment.csv"
)

RESULTS_DIR = (
    BASE_DIR
    / "evaluation"
    / "text_pii"
    / "results"
    / "sroie"
)

SUMMARY_CSV = RESULTS_DIR / "sroie_summary.csv"
RESULTS_JSON = RESULTS_DIR / "sroie_results.json"
VALIDATION_CSV = RESULTS_DIR / "candidate_validation.csv"


# ============================================================
# PATTERN CHECKS
# ============================================================

DATE_PATTERN = re.compile(
    r"\b(?:"
    r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    r"|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}"
    r"|"
    r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}"
    r")\b",
    re.IGNORECASE,
)


def looks_like_date(text):
    return bool(DATE_PATTERN.search(text))


def looks_like_phone(text):
    """
    Basic phone-number validation.

    This is intentionally conservative enough for evaluation,
    but it is NOT treated as ground-truth PII classification.
    """
    digits = re.sub(r"\D", "", text)

    return 7 <= len(digits) <= 15


# ============================================================
# LOAD CSV
# ============================================================

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ============================================================
# MAIN EVALUATION
# ============================================================

def main():

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    ground_truth_rows = load_csv(GROUND_TRUTH)
    candidate_rows = load_csv(CANDIDATES)

    ground_truth_images = {
        row["image_id"]
        for row in ground_truth_rows
    }

    candidate_images = {
        row["image_id"]
        for row in candidate_rows
    }

    # --------------------------------------------------------
    # Candidate type counts
    # --------------------------------------------------------

    candidate_counts = Counter(
        row["candidate_type"]
        for row in candidate_rows
    )

    date_rows = [
        row for row in candidate_rows
        if row["candidate_type"] == "DATE"
    ]

    phone_rows = [
        row for row in candidate_rows
        if row["candidate_type"] == "PHONE"
    ]

    review_rows = [
        row for row in candidate_rows
        if row["candidate_type"] == "REVIEW"
    ]

    # --------------------------------------------------------
    # Validate DATE and PHONE candidates
    # --------------------------------------------------------

    validation_rows = []

    valid_date = 0
    invalid_date = 0

    valid_phone = 0
    invalid_phone = 0

    for row in candidate_rows:

        candidate_type = row["candidate_type"]
        text = row["text"].strip()

        if candidate_type == "DATE":

            valid = looks_like_date(text)

            if valid:
                valid_date += 1
            else:
                invalid_date += 1

        elif candidate_type == "PHONE":

            valid = looks_like_phone(text)

            if valid:
                valid_phone += 1
            else:
                invalid_phone += 1

        else:
            # REVIEW is not automatically considered valid/invalid.
            valid = None

        validation_rows.append({
            "image_id": row["image_id"],
            "text": text,
            "candidate_type": candidate_type,
            "x1": row["x1"],
            "y1": row["y1"],
            "x2": row["x2"],
            "y2": row["y2"],
            "pattern_valid": (
                ""
                if valid is None
                else str(valid)
            ),
        })

    typed_candidates = len(date_rows) + len(phone_rows)

    valid_typed_candidates = valid_date + valid_phone

    if typed_candidates > 0:
        validity_rate = (
            valid_typed_candidates
            / typed_candidates
            * 100
        )
    else:
        validity_rate = 0.0

    # --------------------------------------------------------
    # Per-image statistics
    # --------------------------------------------------------

    per_image = defaultdict(
        lambda: {
            "ocr_regions": 0,
            "review": 0,
            "date": 0,
            "phone": 0,
            "typed_candidates": 0,
        }
    )

    for row in ground_truth_rows:
        per_image[row["image_id"]]["ocr_regions"] += 1

    for row in candidate_rows:

        image_id = row["image_id"]
        candidate_type = row["candidate_type"]

        if candidate_type == "REVIEW":
            per_image[image_id]["review"] += 1

        elif candidate_type == "DATE":
            per_image[image_id]["date"] += 1
            per_image[image_id]["typed_candidates"] += 1

        elif candidate_type == "PHONE":
            per_image[image_id]["phone"] += 1
            per_image[image_id]["typed_candidates"] += 1

    # --------------------------------------------------------
    # Save candidate validation CSV
    # --------------------------------------------------------

    with open(
        VALIDATION_CSV,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        fieldnames = [
            "image_id",
            "text",
            "candidate_type",
            "x1",
            "y1",
            "x2",
            "y2",
            "pattern_valid",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(validation_rows)

    # --------------------------------------------------------
    # Save per-image CSV
    # --------------------------------------------------------

    per_image_csv = RESULTS_DIR / "sroie_per_image.csv"

    with open(
        per_image_csv,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        fieldnames = [
            "image_id",
            "ocr_regions",
            "review_candidates",
            "date_candidates",
            "phone_candidates",
            "typed_candidates",
        ]

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for image_id in sorted(per_image):

            data = per_image[image_id]

            writer.writerow({
                "image_id": image_id,
                "ocr_regions": data["ocr_regions"],
                "review_candidates": data["review"],
                "date_candidates": data["date"],
                "phone_candidates": data["phone"],
                "typed_candidates": data["typed_candidates"],
            })

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    summary = {
        "dataset": "SROIE",
        "ground_truth_ocr_rows": len(ground_truth_rows),
        "ground_truth_images": len(ground_truth_images),
        "candidate_rows": len(candidate_rows),
        "candidate_images": len(candidate_images),

        "review_candidates": len(review_rows),

        "date_candidates": len(date_rows),
        "valid_date_candidates": valid_date,
        "invalid_date_candidates": invalid_date,

        "phone_candidates": len(phone_rows),
        "valid_phone_candidates": valid_phone,
        "invalid_phone_candidates": invalid_phone,

        "total_typed_candidates": typed_candidates,
        "pattern_valid_typed_candidates": valid_typed_candidates,
        "pattern_validity_rate_percent": round(
            validity_rate,
            2,
        ),

        "note": (
            "SROIE ground truth contains OCR text and bounding boxes, "
            "but does not provide explicit PII labels. Therefore "
            "precision, recall and F1 for PII detection are not "
            "reported from this dataset."
        ),
    }

    # --------------------------------------------------------
    # Save summary CSV
    # --------------------------------------------------------

    with open(
        SUMMARY_CSV,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.writer(f)

        writer.writerow(["metric", "value"])

        for key, value in summary.items():
            writer.writerow([key, value])

    # --------------------------------------------------------
    # Save JSON
    # --------------------------------------------------------

    results_json = {
        "summary": summary,
        "candidate_type_counts": dict(candidate_counts),
        "invalid_candidates": [
            row
            for row in validation_rows
            if row["pattern_valid"] == "False"
        ],
    }

    with open(
        RESULTS_JSON,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            results_json,
            f,
            indent=4,
        )

    # ========================================================
    # TERMINAL OUTPUT
    # ========================================================

    print("=" * 70)
    print("SROIE TEXT-PII EVALUATION")
    print("=" * 70)

    print()
    print("DATASET")
    print("-" * 70)
    print(f"Ground-truth OCR rows : {len(ground_truth_rows)}")
    print(f"Ground-truth images   : {len(ground_truth_images)}")
    print(f"Candidate rows        : {len(candidate_rows)}")
    print(f"Candidate images      : {len(candidate_images)}")

    print()
    print("CANDIDATE TYPES")
    print("-" * 70)
    print(f"REVIEW : {len(review_rows)}")
    print(f"DATE   : {len(date_rows)}")
    print(f"PHONE  : {len(phone_rows)}")

    print()
    print("PATTERN VALIDATION")
    print("-" * 70)
    print(
        f"DATE  : {valid_date}/{len(date_rows)} valid"
    )
    print(
        f"PHONE : {valid_phone}/{len(phone_rows)} valid"
    )
    print(
        f"Typed candidates valid : "
        f"{valid_typed_candidates}/{typed_candidates}"
    )
    print(
        f"Pattern validity rate  : "
        f"{validity_rate:.2f}%"
    )

    print()
    print("OUTPUT FILES")
    print("-" * 70)
    print(f"Summary CSV       : {SUMMARY_CSV}")
    print(f"Results JSON      : {RESULTS_JSON}")
    print(f"Validation CSV    : {VALIDATION_CSV}")
    print(f"Per-image CSV     : {per_image_csv}")

    print()
    print("=" * 70)
    print("SROIE EVALUATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()