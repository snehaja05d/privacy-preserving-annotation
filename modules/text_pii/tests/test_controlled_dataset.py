import csv
from pathlib import Path

from modules.text_pii.pipeline import TextPIIPipeline


# --------------------------------------------------
# PATHS
# --------------------------------------------------

GROUND_TRUTH = Path(
    "data/text_pii/controlled_pii/ground_truth.csv"
)

IMAGE_DIR = Path(
    "data/text_pii/controlled_pii/images"
)


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def parse_expected_types(value):
    """
    Convert:
        NAME+PHONE+EMAIL
    into:
        {"NAME", "PHONE", "EMAIL"}
    """

    if value == "NONE":
        return set()

    return set(value.split("+"))


def get_predicted_types(results):
    """
    Extract unique PII types from pipeline results.
    """

    return {
        result["pii_type"]
        for result in results
        if result.get("pii_type")
    }


# --------------------------------------------------
# EVALUATION
# --------------------------------------------------

def main():

    pipeline = TextPIIPipeline()

    total = 0
    passed = 0

    print("\nCONTROLLED DATASET EVALUATION")
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
            expected = parse_expected_types(
                row["pii_type"]
            )

            image_path = IMAGE_DIR / image_name

            print(f"\nIMAGE: {image_name}")
            print(f"EXPECTED: {expected}")

            # --------------------------------------
            # Run pipeline
            # --------------------------------------

            results = pipeline.process(
                str(image_path)
            )

            predicted = get_predicted_types(
                results
            )

            print(f"PREDICTED: {predicted}")

            # --------------------------------------
            # Compare
            # --------------------------------------

            missing = expected - predicted
            unexpected = predicted - expected

            if not missing and not unexpected:

                print("RESULT: PASS")
                passed += 1

            else:

                print("RESULT: FAIL")

                if missing:
                    print(
                        f"MISSING: {missing}"
                    )

                if unexpected:
                    print(
                        f"UNEXPECTED: {unexpected}"
                    )

            # --------------------------------------
            # Show individual detections
            # --------------------------------------

            for result in results:

                print(
                    f"  -> {result['pii_type']}: "
                    f"{result['text']} | "
                    f"{result['status']}"
                )

    # --------------------------------------------------
    # SUMMARY
    # --------------------------------------------------

    print("\n")
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"Total cases : {total}")
    print(f"Passed      : {passed}")
    print(f"Failed      : {total - passed}")

    if total > 0:

        accuracy = (
            passed / total
        ) * 100

        print(
            f"Case accuracy: {accuracy:.2f}%"
        )


if __name__ == "__main__":
    main()