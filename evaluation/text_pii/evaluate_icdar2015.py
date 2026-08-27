import csv
import os
import statistics


CSV_PATH = "evaluation/text_pii/results/icdar2015/icdar2015_summary.csv"

print("=" * 70)
print("ICDAR2015 TEXT-PII EVALUATION SUMMARY")
print("=" * 70)


# ---------------------------------------------------------
# READ RESULTS
# ---------------------------------------------------------

rows = []

with open(CSV_PATH, "r", newline="") as file:
    reader = csv.DictReader(file)

    for row in reader:
        rows.append(row)


if not rows:
    print("No evaluation results found.")
    raise SystemExit


# ---------------------------------------------------------
# BASIC COUNTS
# ---------------------------------------------------------

total_images = len(rows)

successful = sum(
    1
    for row in rows
    if row["status"] == "SUCCESS"
)

failed = sum(
    1
    for row in rows
    if row["status"] != "SUCCESS"
)


# ---------------------------------------------------------
# PII COUNTS
# ---------------------------------------------------------

pii_counts = [
    int(row["pii_entities"])
    for row in rows
]

total_pii = sum(pii_counts)

images_with_pii = sum(
    1
    for count in pii_counts
    if count > 0
)


# ---------------------------------------------------------
# PROCESSING TIME
# ---------------------------------------------------------

processing_times = [
    float(row["processing_time_seconds"])
    for row in rows
]

average_time = statistics.mean(
    processing_times
)

minimum_time = min(
    processing_times
)

maximum_time = max(
    processing_times
)


# ---------------------------------------------------------
# SUCCESS RATE
# ---------------------------------------------------------

success_rate = (
    successful / total_images * 100
)


# ---------------------------------------------------------
# PII DETECTION RATE
# ---------------------------------------------------------

pii_detection_rate = (
    images_with_pii / total_images * 100
)


# ---------------------------------------------------------
# DISPLAY RESULTS
# ---------------------------------------------------------

print()
print("DATASET")
print("-" * 70)
print(f"Dataset                     : ICDAR2015")
print(f"Images tested               : {total_images}")

print()
print("PROCESSING")
print("-" * 70)
print(f"Successful                  : {successful}")
print(f"Failed                      : {failed}")
print(f"Processing success rate     : {success_rate:.2f}%")

print()
print("PII DETECTION")
print("-" * 70)
print(f"Images with detected PII    : {images_with_pii}")
print(f"Total PII entities detected : {total_pii}")
print(f"Image-level detection rate  : {pii_detection_rate:.2f}%")

print()
print("PROCESSING TIME")
print("-" * 70)
print(f"Average                     : {average_time:.3f} seconds")
print(f"Minimum                     : {minimum_time:.3f} seconds")
print(f"Maximum                     : {maximum_time:.3f} seconds")

print()
print("=" * 70)
print("EVALUATION COMPLETE")
print("=" * 70)


# ---------------------------------------------------------
# SHOW IMAGES WHERE PII WAS DETECTED
# ---------------------------------------------------------

print()
print("IMAGES REQUIRING QUALITATIVE REVIEW")
print("-" * 70)

for row in rows:

    if int(row["pii_entities"]) > 0:

        print(
            f"{row['image']}  |  "
            f"PII entities: {row['pii_entities']}  |  "
            f"Output: {row['output']}"
        )