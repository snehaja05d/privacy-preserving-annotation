from datasets import load_dataset
import os
import csv
import random


# --------------------------------------------------
# 1. Load SROIE dataset
# --------------------------------------------------

dataset = load_dataset("jsdnrs/ICDAR2019-SROIE")

print("SROIE dataset loaded.")
print(dataset)


# --------------------------------------------------
# 2. Create output folder
# --------------------------------------------------

output_dir = os.path.expanduser(
    "~/Desktop/SROIE_selected"
)

os.makedirs(output_dir, exist_ok=True)


# --------------------------------------------------
# 3. Inspect all 987 images
# --------------------------------------------------

all_data = []

for split in ["train", "test"]:

    for index in range(len(dataset[split])):

        item = dataset[split][index]

        width = item["image_size"]["width"]
        height = item["image_size"]["height"]

        word_count = len(item["words"])

        aspect_ratio = width / height

        all_data.append({
            "split": split,
            "index": index,
            "key": item["key"],
            "width": width,
            "height": height,
            "aspect_ratio": aspect_ratio,
            "word_count": word_count,
            "item": item
        })


print(f"Total images inspected: {len(all_data)}")


# --------------------------------------------------
# 4. Sort by amount of text
# --------------------------------------------------

all_data.sort(
    key=lambda x: x["word_count"]
)


# --------------------------------------------------
# 5. Divide images into 5 text-density groups
# --------------------------------------------------

groups = []

group_size = len(all_data) // 5

for i in range(5):

    start = i * group_size

    if i == 4:
        end = len(all_data)
    else:
        end = (i + 1) * group_size

    groups.append(all_data[start:end])


# --------------------------------------------------
# 6. Select 10 images from each group
# --------------------------------------------------

random.seed(42)

selected = []

for group in groups:

    random.shuffle(group)

    selected.extend(group[:10])


print(f"Candidate images selected: {len(selected)}")


# --------------------------------------------------
# 7. Save selected images + metadata
# --------------------------------------------------

csv_path = os.path.join(
    output_dir,
    "sroie_candidates.csv"
)


with open(
    csv_path,
    "w",
    newline="",
    encoding="utf-8"
) as file:

    writer = csv.writer(file)

    writer.writerow([
        "image_id",
        "source_split",
        "dataset_index",
        "width",
        "height",
        "aspect_ratio",
        "word_count"
    ])

    for number, item in enumerate(
        selected,
        start=1
    ):

        filename = (
            f"sroie_{number:03d}_"
            f"{item['key']}.jpg"
        )

        image_path = os.path.join(
            output_dir,
            filename
        )

        item["item"]["image"].save(
            image_path
        )

        writer.writerow([
            filename,
            item["split"],
            item["index"],
            item["width"],
            item["height"],
            round(item["aspect_ratio"], 3),
            item["word_count"]
        ])


print()
print("DONE!")
print(f"50 candidate images saved to: {output_dir}")
print(f"Metadata saved to: {csv_path}")