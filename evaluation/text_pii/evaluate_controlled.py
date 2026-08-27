import csv
import json
import time
from pathlib import Path

from modules.text_pii.pipeline import TextPIIPipeline


# ============================================================
# PATHS
# ============================================================

GROUND_TRUTH = Path(
    "data/text_pii/controlled_pii/ground_truth.csv"
)

IMAGE_DIR = Path(
    "data/text_pii/controlled_pii/images"
)

RESULT_DIR = Path(
    "evaluation/text_pii/results/controlled"
)

RESULT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# HELPERS
# ============================================================

def parse_expected_types(value):
    if value == "NONE":
        return set()

    return set(value.split("+"))


def get_predicted_types(results):
    return {
        result.get("pii_type")
        for result in results
        if result.get("pii_type")
    }


def get_statuses(results):
    return sorted({
        result.get("status")
        for result in results
        if result.get("status")
    })


# ============================================================
# EVALUATION
# ============================================================

def main():

    pipeline = TextPIIPipeline()

    per_image = []

    total = 0
    detection_pass = 0
    processing_success = 0

    print("=" * 70)
    print("CONTROLLED PII EVALUATION")
    print("=" * 70)

    with open(
        GROUND_TRUTH,
        newline="",
        encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            total += 1

            image_name = row["image"]
            expected_types = parse_expected_types(
                row["pii_type"]
            )
            expected_action = row["expected_action"]

            image_path = IMAGE_DIR / image_name

            print()
            print("-" * 70)
            print(f"IMAGE           : {image_name}")
            print(f"EXPECTED TYPES  : {expected_types}")
            print(f"EXPECTED ACTION : {expected_action}")

            start = time.time()

            try:

                results = pipeline.process(
                    str(image_path)
                )

                processing_time = time.time() - start

                processing_success += 1

                predicted_types = get_predicted_types(results)
                statuses = get_statuses(results)

                missing = sorted(
                    expected_types - predicted_types
                )

                unexpected = sorted(
                    predicted_types - expected_types
                )

                detection_ok = (
                    not missing and
                    not unexpected
                )

                if detection_ok:
                    detection_pass += 1

                # --------------------------------------------
                # Expected action validation
                # --------------------------------------------

                if expected_action == "MASK":

                    action_ok = (
                        detection_ok
                        and len(predicted_types) > 0
                    )

                elif expected_action == "KEEP":

                    action_ok = (
                        len(predicted_types) == 0
                    )

                elif expected_action == "REVIEW":

                    action_ok = (
                        "DATE" in predicted_types
                    )

                else:

                    action_ok = False

                overall_ok = (
                    detection_ok
                    and action_ok
                )

                print(f"PREDICTED TYPES : {predicted_types}")
                print(f"STATUSES        : {statuses}")
                print(f"MISSING         : {missing}")
                print(f"UNEXPECTED      : {unexpected}")
                print(
                    f"DETECTION       : "
                    f"{'PASS' if detection_ok else 'FAIL'}"
                )
                print(
                    f"ACTION          : "
                    f"{'PASS' if action_ok else 'FAIL'}"
                )
                print(
                    f"OVERALL         : "
                    f"{'PASS' if overall_ok else 'FAIL'}"
                )

                for result in results:

                    print(
                        f"  -> "
                        f"{result.get('pii_type')}: "
                        f"{result.get('text')} | "
                        f"{result.get('status')}"
                    )

                per_image.append({
                    "image": image_name,
                    "expected_pii": "+".join(
                        sorted(expected_types)
                    ) if expected_types else "NONE",
                    "expected_action": expected_action,
                    "predicted_pii": "+".join(
                        sorted(predicted_types)
                    ) if predicted_types else "NONE",
                    "missing_pii": "+".join(missing),
                    "unexpected_pii": "+".join(unexpected),
                    "statuses": "+".join(statuses),
                    "detection_pass": detection_ok,
                    "action_pass": action_ok,
                    "overall_pass": overall_ok,
                    "processing_status": "SUCCESS",
                    "processing_time_seconds": round(
                        processing_time, 3
                    )
                })

            except Exception as e:

                processing_time = time.time() - start

                print(f"PROCESSING     : FAILED")
                print(f"ERROR          : {e}")

                per_image.append({
                    "image": image_name,
                    "expected_pii": "+".join(
                        sorted(expected_types)
                    ) if expected_types else "NONE",
                    "expected_action": expected_action,
                    "predicted_pii": "",
                    "missing_pii": "+".join(
                        sorted(expected_types)
                    ),
                    "unexpected_pii": "",
                    "statuses": "",
                    "detection_pass": False,
                    "action_pass": False,
                    "overall_pass": False,
                    "processing_status": "FAILED",
                    "processing_time_seconds": round(
                        processing_time, 3
                    )
                })


    # ========================================================
    # SUMMARY
    # ========================================================

    overall_pass = sum(
        1 for r in per_image
        if r["overall_pass"]
    )

    detection_accuracy = (
        detection_pass / total * 100
        if total else 0
    )

    overall_accuracy = (
        overall_pass / total * 100
        if total else 0
    )

    processing_rate = (
        processing_success / total * 100
        if total else 0
    )


    # ========================================================
    # SAVE PER-IMAGE CSV
    # ========================================================

    per_image_path = (
        RESULT_DIR / "controlled_per_image.csv"
    )

    if per_image:

        with open(
            per_image_path,
            "w",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=per_image[0].keys()
            )

            writer.writeheader()
            writer.writerows(per_image)


    # ========================================================
    # SAVE SUMMARY CSV
    # ========================================================

    summary = {
        "dataset": "Controlled PII",
        "total_cases": total,
        "processing_success": processing_success,
        "processing_failed": total - processing_success,
        "processing_success_rate_percent":
            round(processing_rate, 2),
        "detection_pass_cases": detection_pass,
        "detection_accuracy_percent":
            round(detection_accuracy, 2),
        "overall_pass_cases": overall_pass,
        "overall_accuracy_percent":
            round(overall_accuracy, 2)
    }

    summary_path = (
        RESULT_DIR / "controlled_summary.csv"
    )

    with open(
        summary_path,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow(["metric", "value"])

        for key, value in summary.items():
            writer.writerow([key, value])


    # ========================================================
    # SAVE JSON
    # ========================================================

    results_json = {
        "dataset": "Controlled PII",
        "summary": summary,
        "per_image": per_image
    }

    json_path = (
        RESULT_DIR / "controlled_results.json"
    )

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            results_json,
            file,
            indent=2
        )


    # ========================================================
    # FINAL PRINT
    # ========================================================

    print()
    print("=" * 70)
    print("CONTROLLED PII EVALUATION SUMMARY")
    print("=" * 70)

    print(f"Total cases             : {total}")
    print(f"Processing successful   : {processing_success}")
    print(f"Processing failed       : {total - processing_success}")
    print(
        f"Processing success rate : "
        f"{processing_rate:.2f}%"
    )

    print()
    print(
        f"Detection pass cases   : "
        f"{detection_pass}/{total}"
    )

    print(
        f"Detection accuracy     : "
        f"{detection_accuracy:.2f}%"
    )

    print(
        f"Overall pass cases     : "
        f"{overall_pass}/{total}"
    )

    print(
        f"Overall accuracy       : "
        f"{overall_accuracy:.2f}%"
    )

    print()
    print("OUTPUT FILES")
    print("-" * 70)

    print(f"Summary CSV  : {summary_path}")
    print(f"Results JSON : {json_path}")
    print(f"Per-image CSV: {per_image_path}")

    print()
    print("=" * 70)
    print("CONTROLLED PII EVALUATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
