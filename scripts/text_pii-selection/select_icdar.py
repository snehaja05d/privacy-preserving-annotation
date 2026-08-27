import random
import shutil
from pathlib import Path


# Source and destination folders
source_folder = Path("data/icdar2015/images")
output_folder = Path("data/icdar2015/selected")


# Create output folder
output_folder.mkdir(parents=True, exist_ok=True)


# Find all ICDAR images
images = sorted(source_folder.glob("*.jpg"))

print(f"Total ICDAR images found: {len(images)}")


# Select 50 images
random.seed(42)
selected_images = random.sample(images, 50)


# Copy selected images
for image in selected_images:
    shutil.copy2(image, output_folder / image.name)


print(f"Selected images: {len(selected_images)}")
print(f"Saved to: {output_folder}")