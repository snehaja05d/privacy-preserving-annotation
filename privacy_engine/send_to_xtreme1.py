import os
from pathlib import Path
import requests


# ============================================================
# SETTINGS
# ============================================================

XTREME1_URL = "http://localhost:8190"

DATASET_ID = 3

PROJECT_ROOT = Path(__file__).resolve().parent.parent

APPROVED_DIR = (
    PROJECT_ROOT
    / "privacy_module"
    / "review"
    / "approved"
)


# ============================================================
# UPLOAD APPROVED IMAGE TO XTREME1
# ============================================================

def upload_image(
    image_path,
    token
):

    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    headers = {
        "Authorization": f"Bearer {token}"
    }

    filename = image_path.name

    print("\n======================================")
    print("UPLOADING TO XTREME1")
    print("======================================")
    print("File:", filename)
    print("Dataset ID:", DATASET_ID)

    # ========================================================
    # 1. REQUEST PRESIGNED URL
    # ========================================================

    print("\n[1/3] Requesting presigned URL...")

    response = requests.get(
        f"{XTREME1_URL}/api/data/generatePresignedUrl",
        params={
            "fileName": filename,
            "datasetId": DATASET_ID
        },
        headers=headers,
        timeout=30
    )

    print(
        "Status:",
        response.status_code
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") != "OK":

        raise RuntimeError(
            f"Xtreme1 error: {data}"
        )

    presigned_url = (
        data["data"]["presignedUrl"]
    )

    access_url = (
        data["data"]["accessUrl"]
    )

    print("✓ Presigned URL received")

    # ========================================================
    # 2. UPLOAD IMAGE TO STORAGE
    # ========================================================

    print("\n[2/3] Uploading image...")

    with open(
        image_path,
        "rb"
    ) as image_file:

        upload_response = requests.put(
            presigned_url,
            data=image_file,
            headers={
                "Content-Type":
                    "application/octet-stream"
            },
            timeout=120
        )

    print(
        "Storage upload status:",
        upload_response.status_code
    )

    upload_response.raise_for_status()

    print("✓ Image uploaded to storage")

    # ========================================================
    # 3. REGISTER IMAGE IN XTREME1
    # ========================================================

    print("\n[3/3] Registering image in Xtreme1...")

    payload = {
        "dataFormat": "XTREME1",
        "datasetId": str(DATASET_ID),
        "fileUrl": access_url,
        "source": "LOCAL"
    }

    register_response = requests.post(
        f"{XTREME1_URL}/api/data/upload",
        json=payload,
        headers=headers,
        timeout=30
    )

    print(
        "Xtreme1 upload status:",
        register_response.status_code
    )

    register_response.raise_for_status()

    print("✓ Image registered in Xtreme1")

    print("\n======================================")
    print("XTREME1 UPLOAD SUCCESSFUL")
    print("======================================")

    return {
        "success": True,
        "filename": filename,
        "dataset_id": DATASET_ID,
        "access_url": access_url
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("======================================")
    print("XTREME1 PRIVACY-SAFE IMAGE UPLOADER")
    print("======================================")

    # --------------------------------------------------------
    # Check approved folder
    # --------------------------------------------------------

    if not APPROVED_DIR.exists():

        print(
            "\nApproved folder does not exist:"
        )

        print(APPROVED_DIR)

        return

    # --------------------------------------------------------
    # Find approved images
    # --------------------------------------------------------

    image_files = sorted(
        [
            file
            for file in APPROVED_DIR.iterdir()
            if file.is_file()
            and file.suffix.lower()
            in {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp"
            }
        ]
    )

    print(
        "\nApproved images found:",
        len(image_files)
    )

    if not image_files:

        print(
            "No approved images available."
        )

        return

    # --------------------------------------------------------
    # Get token
    # --------------------------------------------------------

    token = input(
        "\nPaste Xtreme1 Bearer token: "
    ).strip()

    if not token:

        print(
            "No token entered."
        )

        return

    # --------------------------------------------------------
    # Upload images
    # --------------------------------------------------------

    successful = 0
    failed = 0

    for index, image_path in enumerate(
        image_files,
        start=1
    ):

        print(
            f"\n\nIMAGE {index}/{len(image_files)}"
        )

        try:

            upload_image(
                image_path,
                token
            )

            successful += 1

        except Exception as error:

            print(
                "\n✗ Upload failed"
            )

            print(
                "Reason:",
                error
            )

            failed += 1

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n======================================")
    print("XTREME1 UPLOAD COMPLETE")
    print("======================================")

    print(
        "Total approved images:",
        len(image_files)
    )

    print(
        "Successfully uploaded:",
        successful
    )

    print(
        "Failed:",
        failed
    )

    print("======================================")


if __name__ == "__main__":
    main()