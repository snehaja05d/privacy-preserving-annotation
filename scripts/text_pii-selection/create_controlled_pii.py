from PIL import Image, ImageDraw, ImageFont
import os
import csv


# --------------------------------------------------
# 1. Output folder
# --------------------------------------------------

output_dir = "data/controlled_pii/images"
os.makedirs(output_dir, exist_ok=True)


# --------------------------------------------------
# 2. Test cases
# --------------------------------------------------

test_cases = [
    {
        "filename": "case_001_name.jpg",
        "text": [
            "Customer Information",
            "Name: John Smith"
        ],
        "pii_type": "NAME",
        "expected_action": "MASK"
    },

    {
        "filename": "case_002_phone.jpg",
        "text": [
            "Contact Information",
            "Phone: +91 98765 43210"
        ],
        "pii_type": "PHONE",
        "expected_action": "MASK"
    },

    {
        "filename": "case_003_email.jpg",
        "text": [
            "Contact Information",
            "Email: john.smith@example.com"
        ],
        "pii_type": "EMAIL",
        "expected_action": "MASK"
    },

    {
        "filename": "case_004_address.jpg",
        "text": [
            "Delivery Information",
            "Address: 12 MG Road, Bengaluru"
        ],
        "pii_type": "ADDRESS",
        "expected_action": "MASK"
    },

    {
        "filename": "case_005_id.jpg",
        "text": [
            "Identification",
            "ID Number: ID123456789"
        ],
        "pii_type": "ID",
        "expected_action": "MASK"
    },

    {
        "filename": "case_006_no_pii.jpg",
        "text": [
            "Shopping Receipt",
            "Item: Notebook",
            "Quantity: 2",
            "Total Amount: Rs. 450"
        ],
        "pii_type": "NONE",
        "expected_action": "KEEP"
    },

    {
        "filename": "case_007_mixed.jpg",
        "text": [
            "Customer: John Smith",
            "Phone: +91 98765 43210",
            "Email: john@example.com"
        ],
        "pii_type": "NAME+PHONE+EMAIL",
        "expected_action": "MASK"
    },

    {
        "filename": "case_008_business.jpg",
        "text": [
            "ABC Supermarket",
            "Invoice Number: INV-2026-001",
            "Total: Rs. 1250"
        ],
        "pii_type": "NONE",
        "expected_action": "KEEP"
    },

    {
        "filename": "case_009_date.jpg",
        "text": [
            "Appointment",
            "Date: 15/08/2026",
            "Time: 10:30 AM"
        ],
        "pii_type": "DATE",
        "expected_action": "REVIEW"
    },

    {
        "filename": "case_010_multiple.jpg",
        "text": [
            "Employee Record",
            "Name: Alice Johnson",
            "Phone: +91 91234 56789",
            "Email: alice@example.com",
            "Employee ID: EMP2026001"
        ],
        "pii_type": "NAME+PHONE+EMAIL+ID",
        "expected_action": "MASK"
    }
]


# --------------------------------------------------
# 3. Font
# --------------------------------------------------

try:
    font = ImageFont.truetype(
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        32
    )
except:
    font = ImageFont.load_default()


# --------------------------------------------------
# 4. Create images
# --------------------------------------------------

for case in test_cases:

    image = Image.new(
        "RGB",
        (1200, 600),
        "white"
    )

    draw = ImageDraw.Draw(image)

    y = 60

    for line in case["text"]:

        draw.text(
            (60, y),
            line,
            fill="black",
            font=font
        )

        y += 70

    image_path = os.path.join(
        output_dir,
        case["filename"]
    )

    image.save(image_path)


# --------------------------------------------------
# 5. Create ground truth CSV
# --------------------------------------------------

csv_path = "data/controlled_pii/ground_truth.csv"

with open(
    csv_path,
    "w",
    newline="",
    encoding="utf-8"
) as file:

    writer = csv.writer(file)

    writer.writerow([
        "image",
        "pii_type",
        "expected_action"
    ])

    for case in test_cases:

        writer.writerow([
            case["filename"],
            case["pii_type"],
            case["expected_action"]
        ])


print()
print("DONE!")
print(f"Created {len(test_cases)} controlled test images.")
print(f"Images saved to: {output_dir}")
print(f"Ground truth saved to: {csv_path}")