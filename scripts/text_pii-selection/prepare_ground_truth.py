from datasets import load_dataset
import csv
import os


# --------------------------------------------------
# 1. Load SROIE dataset
# --------------------------------------------------

dataset = load_dataset("jsdnrs/ICDAR2019-SROIE")

print("SROIE dataset loaded.")


# --------------------------------------------------
# 2. Read the 50 selected image names
# --------------------------------------------------

selected_folder = os.path.expanduser(
    "~/Desktop/SROIE_selected"
)

selected_files = os.listdir(selected_folder)

selected_ids = set()

for filename in selected_files:
    if filename.endswith(".jpg"):
        # Example:
        # sroie_001_X51006387931.jpg
        # Extract the original SROIE key
        parts = filename.replace(".jpg", "").split("_")

        if len(parts) >= 3:
            selected_ids.add(parts[-1])


print(f"Selected images found: {len(selected_ids)}")


# --------------------------------------------------
# 3. Create ground-truth CSV
# --------------------------------------------------

output_folder = os.path.expanduser(
    "~/Documents/privacy-preserving-annotation/data/text_pii"
)

if not os.path.exists(output_folder):
    os.makedirs(output_folder)

csv_path = os.path.join(
    output_folder,
    "sroie_text_ground_truth.csv"
)


# --------------------------------------------------
# 4. Extract OCR annotations
# --------------------------------------------------

rows = []

for split in ["train", "test"]:

    for item in dataset[split]:

        if item["key"] not in selected_ids:
            continue

        words = item["words"]
        bboxes = item["bboxes"]

        for word, bbox in zip(words, bboxes):

            rows.append([
                item["key"],
                word,
                bbox[0],
                bbox[1],
                bbox[2],
                bbox[3]
            ])


# --------------------------------------------------
# 5. Save CSV
# --------------------------------------------------

with open(
    csv_path,
    "w",
    newline="",
    encoding="utf-8"
) as file:

    writer = csv.writer(file)

    writer.writerow([
        "image_id",
        "text",
        "x1",
        "y1",
        "x2",
        "y2"
    ])

    writer.writerows(rows)


print()
print("DONE!")
print(f"Ground-truth rows created: {len(rows)}")
print(f"Saved to: {csv_path}")