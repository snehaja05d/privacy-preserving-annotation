import streamlit as st
from pathlib import Path
import shutil
import time
import requests

from privacy_engine.pipeline import PrivacyEngine


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent

INPUT_DIR = PROJECT_ROOT / "privacy_module" / "input"
OUTPUT_DIR = PROJECT_ROOT / "privacy_module" / "output"
APPROVED_DIR = PROJECT_ROOT / "privacy_module" / "review" / "approved"


# ============================================================
# XTREME1 SETTINGS
# ============================================================

XTREME1_URL = "http://localhost:8190"

# Keep this as the dataset you were using before.
# You can change it in the UI if your Image Trial dataset has
# a different ID.
DEFAULT_DATASET_ID = 4

UPLOAD_POLL_SECONDS = 2
UPLOAD_TIMEOUT_SECONDS = 120
DATASET_VERIFY_TIMEOUT_SECONDS = 120


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Privacy-Preserving Annotation",
    page_icon="🔐",
    layout="wide"
)


# ============================================================
# DIRECTORIES
# ============================================================

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
APPROVED_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# SESSION STATE
# ============================================================

if "results" not in st.session_state:
    st.session_state["results"] = []

if "xtreme1_upload_results" not in st.session_state:
    st.session_state["xtreme1_upload_results"] = []


# ============================================================
# XTREME1 HELPERS
# ============================================================

def get_xtreme1_headers(token):
    token = token.strip()

    # Allow the user to paste either:
    #   abc123
    # or:
    #   Bearer abc123
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    return {
        "Authorization": f"Bearer {token}"
    }


def get_dataset_info(token, dataset_id):
    response = requests.get(
        f"{XTREME1_URL}/api/dataset/info/{dataset_id}",
        headers=get_xtreme1_headers(token),
        timeout=30
    )

    response.raise_for_status()

    body = response.json()

    if body.get("code") != "OK":
        raise RuntimeError(
            f"Xtreme1 dataset error: {body}"
        )

    return body["data"]


def get_dataset_items(token, dataset_id):
    response = requests.get(
        f"{XTREME1_URL}/api/data/findByPage",
        params={
            "datasetId": dataset_id,
            "pageNo": 1,
            "pageSize": 1000,
            "sortField": "CREATED_AT",
            "ascOrDesc": "DESC"
        },
        headers=get_xtreme1_headers(token),
        timeout=30
    )

    response.raise_for_status()

    body = response.json()

    if body.get("code") != "OK":
        raise RuntimeError(
            f"Xtreme1 data query error: {body}"
        )

    return body.get("data") or {}


def wait_for_xtreme1_upload(
    token,
    serial_number,
    filename,
    timeout_seconds=UPLOAD_TIMEOUT_SECONDS
):
    """
    /api/data/upload is asynchronous.

    HTTP 200 means the job was accepted, not necessarily that
    the image is already visible in the dataset.

    This waits for the upload-processing record to finish.
    """

    start_time = time.time()
    headers = get_xtreme1_headers(token)

    while True:
        if time.time() - start_time > timeout_seconds:
            raise TimeoutError(
                f"Xtreme1 processing timed out for {filename}. "
                f"Serial number: {serial_number}"
            )

        response = requests.get(
            f"{XTREME1_URL}/api/data/findUploadRecordBySerialNumbers",
            params={
                "serialNumbers": serial_number
            },
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        body = response.json()

        if body.get("code") != "OK":
            raise RuntimeError(
                f"Xtreme1 upload-status error: {body}"
            )

        records = body.get("data") or []

        if not records:
            time.sleep(UPLOAD_POLL_SECONDS)
            continue

        record = records[0]

        status_value = str(
            record.get("status", "")
        ).upper()

        total_data = int(
            record.get("totalDataNum") or 0
        )

        parsed_data = int(
            record.get("parsedDataNum") or 0
        )

        error_message = record.get("errorMessage")

        failure_states = {
            "FAILED",
            "FAIL",
            "ERROR",
            "INVALID"
        }

        if status_value in failure_states:
            raise RuntimeError(
                f"Xtreme1 processing failed for {filename}. "
                f"Status={status_value}. "
                f"Error={error_message}"
            )

        success_states = {
            "SUCCESS",
            "SUCCEEDED",
            "COMPLETED",
            "COMPLETE",
            "FINISHED"
        }

        if status_value in success_states:
            return record

        if (
            total_data > 0
            and parsed_data >= total_data
        ):
            return record

        time.sleep(UPLOAD_POLL_SECONDS)


def object_contains_filename(obj, filename):
    """
    Search the whole Xtreme1 dataset-item response because the
    filename may be stored inside content/files rather than
    directly as item['name'].
    """

    if isinstance(obj, dict):
        for key, value in obj.items():

            if key in {
                "name",
                "originalName",
                "fileName"
            }:
                if str(value) == filename:
                    return True

            if object_contains_filename(value, filename):
                return True

        return False

    if isinstance(obj, list):
        for value in obj:
            if object_contains_filename(value, filename):
                return True

        return False

    return str(obj) == filename


def wait_for_dataset_item(
    token,
    dataset_id,
    filename,
    timeout_seconds=DATASET_VERIFY_TIMEOUT_SECONDS
):
    """
    After the asynchronous upload job succeeds, Xtreme1 can still
    take a little time before the record appears in the dataset.

    Poll until the actual dataset item is visible.
    """

    start_time = time.time()

    while True:
        if time.time() - start_time > timeout_seconds:
            raise TimeoutError(
                f"Xtreme1 upload finished, but `{filename}` "
                f"did not appear in dataset {dataset_id} "
                f"within {timeout_seconds} seconds."
            )

        data_response = get_dataset_items(
            token,
            dataset_id
        )

        data_list = data_response.get("list", [])

        for item in data_list:
            if object_contains_filename(
                item,
                filename
            ):
                return item

        time.sleep(UPLOAD_POLL_SECONDS)


def upload_image_to_xtreme1(
    image_path,
    token,
    dataset_id
):
    """
    Complete Xtreme1 image-upload flow:

    1. Verify IMAGE dataset
    2. Generate presigned URL
    3. Upload image bytes to storage
    4. Register the uploaded file in Xtreme1
    5. Wait for asynchronous processing
    6. Poll until the actual dataset item is visible
    """

    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    if not token.strip():
        raise ValueError(
            "Xtreme1 Bearer token is empty."
        )

    filename = image_path.name

    # ------------------------------------------------------------
    # 1. VERIFY DATASET
    # ------------------------------------------------------------

    st.write(
        f"**Step 1/6:** Checking Xtreme1 dataset "
        f"`{dataset_id}`..."
    )

    dataset_info = get_dataset_info(
        token,
        dataset_id
    )

    dataset_name = dataset_info.get(
        "name",
        "Unknown"
    )

    dataset_type = dataset_info.get(
        "type",
        "Unknown"
    )

    st.write(
        f"Dataset: **{dataset_name}**  \n"
        f"Type: **{dataset_type}**"
    )

    if str(dataset_type).upper() != "IMAGE":
        raise RuntimeError(
            f"Dataset {dataset_id} is `{dataset_type}`, "
            "not an IMAGE dataset. "
            "Choose the Xtreme1 image dataset."
        )

    # ------------------------------------------------------------
    # 2. REQUEST PRESIGNED URL
    # ------------------------------------------------------------

    st.write(
        f"**Step 2/6:** Requesting storage URL "
        f"for `{filename}`..."
    )

    presign_response = requests.get(
        f"{XTREME1_URL}/api/data/generatePresignedUrl",
        params={
            "fileName": filename,
            "datasetId": dataset_id
        },
        headers=get_xtreme1_headers(token),
        timeout=30
    )

    presign_response.raise_for_status()

    presign_body = presign_response.json()

    if presign_body.get("code") != "OK":
        raise RuntimeError(
            f"Could not generate presigned URL: "
            f"{presign_body}"
        )

    presign_data = presign_body.get("data") or {}

    presigned_url = presign_data.get(
        "presignedUrl"
    )

    access_url = presign_data.get(
        "accessUrl"
    )

    if not presigned_url or not access_url:
        raise RuntimeError(
            "Xtreme1 did not return both "
            "presignedUrl and accessUrl."
        )

    # ------------------------------------------------------------
    # 3. UPLOAD BYTES TO OBJECT STORAGE
    # ------------------------------------------------------------

    st.write(
        "**Step 3/6:** Uploading image bytes "
        "to Xtreme1 storage..."
    )

    with open(image_path, "rb") as image_file:
        upload_response = requests.put(
            presigned_url,
            data=image_file,
            headers={
                "Content-Type": "application/octet-stream"
            },
            timeout=120
        )

    if upload_response.status_code not in {
        200,
        201,
        204
    }:
        raise RuntimeError(
            "Storage upload failed. "
            f"HTTP {upload_response.status_code}: "
            f"{upload_response.text[:500]}"
        )

    # ------------------------------------------------------------
    # 4. REGISTER FILE IN XTREME1
    # ------------------------------------------------------------

    st.write(
        "**Step 4/6:** Registering the uploaded "
        "file in Xtreme1..."
    )

    register_payload = {
        "fileUrl": access_url,
        "datasetId": dataset_id,
        "source": "LOCAL"
    }

    register_response = requests.post(
        f"{XTREME1_URL}/api/data/upload",
        json=register_payload,
        headers=get_xtreme1_headers(token),
        timeout=30
    )

    register_response.raise_for_status()

    register_body = register_response.json()

    if register_body.get("code") != "OK":
        raise RuntimeError(
            f"Xtreme1 registration failed: "
            f"{register_body}"
        )

    serial_number = register_body.get("data")

    if isinstance(serial_number, dict):
        serial_number = (
            serial_number.get("serialNumber")
            or serial_number.get("serial_number")
            or serial_number.get("id")
        )

    if not serial_number:
        raise RuntimeError(
            "Xtreme1 accepted the upload but did not "
            "return an upload serial number. "
            f"Response: {register_body}"
        )

    serial_number = str(serial_number)

    # ------------------------------------------------------------
    # 5. WAIT FOR ASYNC PROCESSING
    # ------------------------------------------------------------

    st.write(
        "**Step 5/6:** Waiting for Xtreme1 "
        "to finish processing..."
    )

    upload_record = wait_for_xtreme1_upload(
        token,
        serial_number,
        filename
    )

    # ------------------------------------------------------------
    # 6. VERIFY ACTUAL DATASET ITEM
    # ------------------------------------------------------------

    st.write(
        "**Step 6/6:** Waiting for the image "
        "to appear inside the dataset..."
    )

    matching_item = wait_for_dataset_item(
        token,
        dataset_id,
        filename
    )

    return {
        "success": True,
        "filename": filename,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "serial_number": serial_number,
        "upload_record": upload_record,
        "data_item": matching_item
    }


# ============================================================
# TITLE
# ============================================================

st.title(
    "🔐 Privacy-Preserving Annotation System"
)

st.caption(
    "Detect privacy-sensitive content, protect images, "
    "review the results, and send approved images to Xtreme1."
)


# ============================================================
# 1. UPLOAD IMAGES
# ============================================================

st.divider()
st.header("📤 1. Upload Images")

uploaded_files = st.file_uploader(
    "Choose image(s)",
    type=[
        "jpg",
        "jpeg",
        "png",
        "webp"
    ],
    accept_multiple_files=True
)

if uploaded_files:
    st.success(
        f"{len(uploaded_files)} image(s) selected."
    )

    for uploaded_file in uploaded_files:
        file_path = (
            INPUT_DIR
            / uploaded_file.name
        )

        with open(
            file_path,
            "wb"
        ) as file:
            file.write(
                uploaded_file.getbuffer()
            )

    st.subheader("Selected Images")

    columns = st.columns(
        min(4, len(uploaded_files))
    )

    for index, uploaded_file in enumerate(
        uploaded_files
    ):
        with columns[index % len(columns)]:

            # IMPORTANT:
            # Do NOT use use_container_width here.
            # Your installed Streamlit version does not
            # support it for st.image().
            st.image(
                uploaded_file,
                caption=uploaded_file.name
            )


# ============================================================
# 2. PRIVACY OPTIONS
# ============================================================

st.divider()
st.header("🛡️ 2. Privacy Protection Settings")

st.write(
    "Choose which types of sensitive information "
    "should be detected and protected."
)

selected_types = st.multiselect(
    "Privacy types to detect",
    options=[
        "FACE",
        "PLATE",
        "EMAIL",
        "PHONE",
        "NAME",
        "ID"
    ],
    default=[
        "FACE",
        "PLATE",
        "EMAIL",
        "PHONE",
        "NAME",
        "ID"
    ]
)

if selected_types:
    st.info(
        "Selected: "
        + ", ".join(selected_types)
    )
else:
    st.warning(
        "Select at least one privacy type "
        "before processing."
    )


# ============================================================
# 3. PRIVACY PROCESSING
# ============================================================

st.divider()
st.header("⚙️ 3. Privacy Processing")

if uploaded_files:

    if st.button(
        "🚀 Process Images",
        type="primary"
    ):

        if not selected_types:
            st.error(
                "Please select at least one "
                "privacy type."
            )

        else:

            progress = st.progress(0)
            status = st.empty()

            try:
                status.write(
                    "Loading privacy engine..."
                )

                engine = PrivacyEngine()

                # Clear old approved images.
                for old_file in APPROVED_DIR.iterdir():
                    if old_file.is_file():
                        old_file.unlink()

                image_results = []

                for index, uploaded_file in enumerate(
                    uploaded_files
                ):

                    status.write(
                        f"Processing "
                        f"{uploaded_file.name}..."
                    )

                    input_path = (
                        INPUT_DIR
                        / uploaded_file.name
                    )

                    output_path = (
                        OUTPUT_DIR
                        / f"masked_{uploaded_file.name}"
                    )

                    result = engine.process(
                        input_path,
                        output_path,
                        selected_types=selected_types
                    )

                    result["input_path"] = str(
                        input_path
                    )

                    result["output_path"] = str(
                        output_path
                    )

                    image_results.append(result)

                    # Automatically approve safe images.
                    if result.get(
                        "review_status"
                    ) == "APPROVED":

                        approved_path = (
                            APPROVED_DIR
                            / output_path.name
                        )

                        shutil.copy2(
                            output_path,
                            approved_path
                        )

                    progress.progress(
                        int(
                            100
                            * (index + 1)
                            / len(uploaded_files)
                        )
                    )

                st.session_state[
                    "results"
                ] = image_results

                status.success(
                    "Privacy processing completed!"
                )

                st.rerun()

            except Exception as error:
                st.error(
                    f"Processing failed: {error}"
                )

else:
    st.info(
        "Upload images first."
    )


# ============================================================
# 4. REVIEW RESULTS
# ============================================================

if st.session_state["results"]:

    st.divider()
    st.header(
        "🔍 4. Review Processing Results"
    )

    st.write(
        "Review each processed image. Images marked "
        "**REVIEW REQUIRED** must be approved manually "
        "before they can be sent to Xtreme1."
    )

    for index, result in enumerate(
        st.session_state["results"]
    ):

        input_path = Path(
            result["input_path"]
        )

        output_path = Path(
            result["output_path"]
        )

        filename = input_path.name

        faces = result.get(
            "faces",
            []
        )

        plates = result.get(
            "plates",
            []
        )

        review_status = result.get(
            "review_status",
            "REVIEW"
        )

        st.markdown("---")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Original")

            if input_path.exists():
                st.image(
                    str(input_path),
                    caption=filename
                )

        with col2:
            st.subheader(
                "Privacy-Safe Image"
            )

            if output_path.exists():
                st.image(
                    str(output_path),
                    caption=(
                        f"Protected: {filename}"
                    )
                )

        st.write(
            "### Detection Summary"
        )

        info1, info2, info3 = st.columns(3)

        with info1:
            st.metric(
                "Faces",
                len(faces)
            )

        with info2:
            st.metric(
                "License Plates",
                len(plates)
            )

        with info3:

            if review_status == "APPROVED":
                st.success(
                    "Automatically Approved"
                )

            elif review_status == "REJECTED":
                st.error(
                    "Rejected"
                )

            else:
                st.warning(
                    "Human Review Required"
                )

        if review_status != "APPROVED":

            if review_status == "REJECTED":
                st.error(
                    f"❌ {filename} has been rejected."
                )
            else:
                st.warning(
                    f"⚠️ {filename} requires "
                    "human review."
                )

            approve_col, reject_col = (
                st.columns(2)
            )

            with approve_col:

                if st.button(
                    f"✅ Approve {filename}",
                    key=f"approve_{index}"
                ):

                    if output_path.exists():

                        approved_path = (
                            APPROVED_DIR
                            / output_path.name
                        )

                        shutil.copy2(
                            output_path,
                            approved_path
                        )

                        st.session_state[
                            "results"
                        ][index][
                            "review_status"
                        ] = "APPROVED"

                        st.success(
                            f"{filename} approved."
                        )

                        st.rerun()

                    else:
                        st.error(
                            "Protected image "
                            "was not found."
                        )

            with reject_col:

                if st.button(
                    f"❌ Reject {filename}",
                    key=f"reject_{index}"
                ):

                    approved_path = (
                        APPROVED_DIR
                        / output_path.name
                    )

                    if approved_path.exists():
                        approved_path.unlink()

                    st.session_state[
                        "results"
                    ][index][
                        "review_status"
                    ] = "REJECTED"

                    st.warning(
                        f"{filename} rejected."
                    )

        else:
            st.success(
                f"✅ {filename} is approved "
                "for Xtreme1."
            )


# ============================================================
# 5. APPROVED IMAGES
# ============================================================

if st.session_state["results"]:

    st.divider()
    st.header(
        "✅ 5. Approved Images"
    )

    approved_images = sorted(
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

    if approved_images:

        st.success(
            f"{len(approved_images)} "
            "image(s) ready for Xtreme1."
        )

        columns = st.columns(
            min(4, len(approved_images))
        )

        for index, image_path in enumerate(
            approved_images
        ):

            with columns[index % len(columns)]:

                st.image(
                    str(image_path),
                    caption=image_path.name
                )

    else:
        st.warning(
            "No approved images yet. "
            "Approve images in the review "
            "section above."
        )


# ============================================================
# 6. XTREME1 UPLOAD
# ============================================================

if st.session_state["results"]:

    st.divider()
    st.header(
        "🚀 6. Send Approved Images to Xtreme1"
    )

    st.write(
        f"**Xtreme1:** `{XTREME1_URL}`"
    )

    dataset_id = st.number_input(
        "Xtreme1 Dataset ID",
        min_value=1,
        value=DEFAULT_DATASET_ID,
        step=1,
        help=(
            "Use the ID of your IMAGE dataset "
            "in Xtreme1. The app verifies that "
            "the dataset is actually an IMAGE dataset "
            "before uploading."
        )
    )

    token = st.text_input(
        "Xtreme1 Bearer Token",
        type="password",
        help=(
            "Paste the same Xtreme1 Bearer token "
            "that worked in Terminal."
        )
    )

    approved_images = sorted(
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

    if token.strip():

        try:
            dataset_info = get_dataset_info(
                token,
                int(dataset_id)
            )

            dataset_name = dataset_info.get(
                "name",
                "Unknown"
            )

            dataset_type = dataset_info.get(
                "type",
                "Unknown"
            )

            if str(dataset_type).upper() == "IMAGE":
                st.success(
                    f"Xtreme1 dataset verified: "
                    f"**{dataset_name}** "
                    f"(ID {int(dataset_id)}, IMAGE)"
                )
            else:
                st.error(
                    f"Dataset {int(dataset_id)} is "
                    f"**{dataset_type}**, not IMAGE."
                )

        except Exception as error:
            st.warning(
                "Could not verify the dataset yet: "
                f"{error}"
            )

    if approved_images:

        st.info(
            f"{len(approved_images)} approved "
            "image(s) will be uploaded."
        )

        if st.button(
            "📤 Upload Approved Images to Xtreme1",
            type="primary"
        ):

            if not token.strip():

                st.error(
                    "Please enter your "
                    "Xtreme1 Bearer token."
                )

            else:

                successful = 0
                failed = 0
                upload_results = []

                progress = st.progress(0)
                status_text = st.empty()

                for index, image_path in enumerate(
                    approved_images,
                    start=1
                ):

                    try:

                        status_text.write(
                            f"Uploading "
                            f"`{image_path.name}` "
                            f"({index}/"
                            f"{len(approved_images)})..."
                        )

                        result = (
                            upload_image_to_xtreme1(
                                image_path,
                                token,
                                int(dataset_id)
                            )
                        )

                        upload_results.append(
                            result
                        )

                        successful += 1

                        st.success(
                            "🎉 "
                            f"{image_path.name} "
                            "is uploaded, processed, "
                            "and VERIFIED as a dataset "
                            "item in Xtreme1."
                        )

                        st.write(
                            f"Serial number: "
                            f"`{result['serial_number']}`"
                        )

                        st.write(
                            f"Dataset: "
                            f"`{result['dataset_name']}`"
                        )

                    except Exception as error:

                        failed += 1

                        st.error(
                            f"❌ "
                            f"{image_path.name} "
                            f"failed: {error}"
                        )

                    progress.progress(
                        int(
                            100
                            * index
                            / len(approved_images)
                        )
                    )
                    status_text.success("✅ All uploads completed.")
                    print("[XTREME1] Upload workflow finished.")

                st.session_state[
                    "xtreme1_upload_results"
                ] = upload_results

                st.divider()

                if failed == 0:

                    st.success(
                        "🎉 Upload complete! "
                        f"{successful} image(s) "
                        "were processed by Xtreme1 "
                        "AND verified in the dataset."
                    )

                else:

                    st.warning(
                        "Upload finished: "
                        f"{successful} successful, "
                        f"{failed} failed."
                    )

    else:

        st.warning(
            "No approved images available. "
            "Approve an image before uploading "
            "to Xtreme1."
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Privacy-Preserving Annotation System • "
    "Visual Privacy + Text PII + Human Review + Xtreme1"
)
