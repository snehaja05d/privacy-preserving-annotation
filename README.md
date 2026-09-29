# Privacy-Preserving Annotation System

A privacy-preserving AI platform that detects and anonymizes sensitive information in images before they are used for annotation.

The system automatically detects **faces, license plates, and text-based PII** — including names, phone numbers, email addresses, and ID numbers — and masks that information before an image is sent downstream for annotation. This reduces the exposure of sensitive data throughout the annotation pipeline.

For cases where automatic detection needs verification, the platform supports **human-in-the-loop review**: images flagged as **Review Required** can be manually checked and approved before delivery.

Approved images can be delivered to **Xtreme1, CVAT, or Label Studio**, and can also be sent to any HTTP endpoint through a **webhook**.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Main Features](#main-features)
- [Technologies](#technologies)
- [Project Structure](#project-structure)
- [Run with Docker](#run-with-docker)
- [Local Development](#local-development)
- [Running PrivacyHub](#running-privacyhub)
- [API Workflow](#api-workflow)
- [Annotation Platform Delivery](#annotation-platform-delivery)
- [Webhooks](#webhooks)

---

## How It Works

```mermaid
flowchart TD
    A["Image / External Application"] --> B["PrivacyHub"]
    B --> C["Privacy Detection"]
    C --> D["Face Detection"]
    C --> E["License Plate Detection"]
    C --> F["Text PII Detection"]
    D --> G["Privacy Masking"]
    E --> G
    F --> G
    G --> H{"Confidence Check"}
    H -->|High confidence| I["Approved"]
    H -->|Low confidence| J["Review Required"]
    J -->|Manual review & approval| I
    I --> K["Delivery & Integration"]
    K --> L["Return Processed Image"]
    K --> M["Xtreme1"]
    K --> N["CVAT"]
    K --> O["Label Studio"]
    K --> P["Webhook (HTTP POST)"]

    style A fill:#1f2937,stroke:#4b5563,color:#fff
    style B fill:#2563eb,stroke:#1d4ed8,color:#fff
    style C fill:#374151,stroke:#4b5563,color:#fff
    style G fill:#374151,stroke:#4b5563,color:#fff
    style H fill:#b45309,stroke:#92400e,color:#fff
    style I fill:#15803d,stroke:#166534,color:#fff
    style J fill:#b91c1c,stroke:#991b1b,color:#fff
    style K fill:#2563eb,stroke:#1d4ed8,color:#fff
    style L fill:#374151,stroke:#4b5563,color:#fff
    style M fill:#374151,stroke:#4b5563,color:#fff
    style N fill:#374151,stroke:#4b5563,color:#fff
    style O fill:#374151,stroke:#4b5563,color:#fff
    style P fill:#374151,stroke:#4b5563,color:#fff
```

PrivacyHub provides a **web interface built with FastAPI** and a **REST API** for external applications.

External applications authenticate with a **Bearer token**, submit images for processing, receive a job ID, poll job status, and retrieve the processed image once it's ready. The API also handles **token management, usage tracking, rate limiting, and job tracking**.

Once an image is approved as privacy-safe, it can be delivered directly to **Xtreme1, CVAT, or Label Studio**, or posted to your own endpoint through a **webhook**.

---

## Main Features

| Category | Capabilities |
|---|---|
| **Detection** | Face detection, license plate detection, OCR-based text detection, PII detection (names, emails, phone numbers, IDs) |
| **Processing** | Confidence-based routing, automatic masking, human review for uncertain detections |
| **API** | FastAPI REST API, Bearer-token authentication, token generation/expiry/revocation, usage tracking, rate limiting, asynchronous job tracking |
| **Delivery** | Return processed image directly, or deliver to Xtreme1, CVAT, or Label Studio |
| **Webhooks** | Send the approved, masked image to any HTTP/HTTPS endpoint as a `multipart/form-data` POST |
| **Interface** | Web-based PrivacyHub dashboard |

---

## Technologies

- **Language:** Python
- **Web Framework:** FastAPI
- **Computer Vision:** OpenCV, YOLO, PaddleOCR
- **ML/DL:** PyTorch, Hugging Face Transformers, ONNX Runtime
- **Database:** SQLite
- **Frontend:** HTML, CSS, JavaScript
- **Integrations:** Xtreme1, CVAT (via `cvat-sdk`), Label Studio, Webhooks
- **Deployment:** Docker

---

## Project Structure

```text
privacy-preserving-annotation/
│
├── data/                  # Data and project resources
├── evaluation/            # Evaluation scripts and metrics
├── modules/               # Core processing modules
├── privacy_engine/        # Detection and masking logic
├── privacy_module/        # Privacy-related utilities
├── privacyhub_web/        # FastAPI web application
├── scripts/               # Helper / utility scripts
│
├── .dockerignore          # Docker build exclusions
├── .gitignore             # Git exclusions
├── Dockerfile             # Docker image configuration
├── docker-compose.yml     # Docker Compose configuration
├── requirements.txt       # Core dependencies
└── requirements-full.txt  # Full dependency set
```

---

## Run with Docker

The easiest way to run PrivacyHub is using the pre-built Docker image available on Docker Hub.

### Requirements

- Docker Desktop installed and running

### 1. Pull the Docker Image

```bash
docker pull rachit1104/privacy-preserving-annotation:latest
```

### 2. Start PrivacyHub

```bash
docker run -d --name privacy-app -p 8501:8501 -e WEB_HOST=0.0.0.0 -e WEB_PORT=8501 -e OPEN_BROWSER=0 rachit1104/privacy-preserving-annotation:latest
```

### 3. Check if the Container is Running

```bash
docker ps
```

You should see `privacy-app` running with port `8501` mapped.

### 4. Open PrivacyHub

Open in your browser:

```text
http://localhost:8501
```

### Check All Containers

To see both running and stopped containers:

```bash
docker ps -a
```

### View Application Logs

To view the PrivacyHub logs:

```bash
docker logs privacy-app
```

To continuously watch the logs:

```bash
docker logs -f privacy-app
```

Press `Ctrl + C` to stop watching the logs.

### Stop the Application

```bash
docker stop privacy-app
```

### Start it Again

```bash
docker start privacy-app
```

### Remove the Container

```bash
docker rm -f privacy-app
```

> If the container is removed, run the `docker run` command again to create a new one.

---

## Local Development

For development without Docker, clone the repository and install the dependencies locally.

### 1. Clone the Repository

```bash
git clone https://github.com/snehaja05d/privacy-preserving-annotation.git
cd privacy-preserving-annotation
```

### 2. Create a Virtual Environment

```bash
python -m venv .venv
```

### 3. Activate the Environment

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

For the complete dependency set:

```bash
pip install -r requirements-full.txt
```

---

## Running PrivacyHub

Start the web application locally:

```powershell
.\.venv\Scripts\python.exe .\privacyhub_web\run_web.py
```

Once the server starts, open:

```text
http://127.0.0.1:8501
```

Interactive FastAPI documentation (Swagger UI) is available at:

```text
http://127.0.0.1:8501/docs
```

---

## API Workflow

External applications communicate with PrivacyHub through the REST API using the following flow:

```mermaid
sequenceDiagram
    participant App as External Application
    participant API as PrivacyHub API
    participant AP as Annotation Platform<br/>(Xtreme1 / CVAT / Label Studio)
    participant WH as Webhook Endpoint

    App->>API: POST image (Bearer token)
    API-->>App: 202 Accepted + Job ID
    App->>API: GET job status
    API-->>App: Status: PENDING / REVIEW / APPROVED_WAITING_FOR_DELIVERY / DELIVERED

    alt Review Required
        API->>API: Manual review & approval
    end

    App->>API: GET processed image
    API-->>App: Approved privacy-safe image

    opt Deliver to annotation platform
        API->>AP: Send approved image
        AP-->>API: Delivery confirmation
    end

    opt Destination = WEBHOOK
        API->>WH: POST masked image (multipart/form-data)
        WH-->>API: 2xx response
    end
```

> **Note:** All API requests require a valid PrivacyHub Bearer token.

### Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/anonymize` | Submit an image for anonymization |
| `GET` | `/api/v1/jobs/{job_id}` | Check job status |
| `GET` | `/api/v1/jobs/{job_id}/result` | Download the protected image (when the destination is `RETURN`) |

### `POST /api/v1/anonymize` parameters

Sent as `multipart/form-data`:

| Field | Description |
|---|---|
| `file` | Image to process (required) |
| `selected_types` | Comma-separated detection types. Default: `FACE,PLATE,EMAIL,PHONE,NAME,ID` |
| `destination` | `RETURN` (default), `ANNOTATION`, or `WEBHOOK`. `XTREME1` is still accepted for backward compatibility |
| `webhook_url` | Required when `destination=WEBHOOK` |
| `annotation_platform` | `CVAT`, `XTREME1`, or `LABEL_STUDIO` (required when `destination=ANNOTATION`) |
| `platform_url` | Base URL of the annotation platform (required for `ANNOTATION`) |
| `platform_token` | Access token for the annotation platform (required for `ANNOTATION`) |
| `dataset_id` | Xtreme1 dataset ID (required for Xtreme1) |
| `project_id` | Label Studio project ID (required for Label Studio); optional for CVAT |
| `task_name` | Optional task name (used for CVAT tasks) |
| `image_field` | Label Studio image data field. Default: `image` |

### Job statuses

| Status | Meaning |
|---|---|
| `PENDING` | Job received, not ready yet |
| `REVIEW` | Low-confidence detections, waiting for manual review and approval |
| `APPROVED_WAITING_FOR_DELIVERY` | Approved, waiting to be delivered |
| `DELIVERED` | Delivered (or ready to return) |

---

## Annotation Platform Delivery

Approved, privacy-safe images can be delivered directly to an annotation platform through the Delivery & Integrations section of the dashboard, or through the API with `destination=ANNOTATION`.

| Platform | Required | Optional | Notes |
|---|---|---|---|
| **Xtreme1** | Platform URL, access (Bearer) token, Dataset ID | — | Image is uploaded to the given dataset |
| **CVAT** | Platform URL, Personal Access Token | Project ID, task name | Creates a CVAT task, uploads the image, and verifies that media was attached. Works with CVAT Cloud and self-hosted CVAT. Requires `cvat-sdk` |
| **Label Studio** | Platform URL, access token, Project ID | Image field name (default `image`) | Uploads the image into the project and waits for the import to finish |

The dashboard can also list the CVAT projects visible to a Personal Access Token, so you can pick a project instead of typing its ID.

Only the protected (masked) image is ever sent to the annotation environment — raw or unmasked images are never transmitted downstream.

---

## Webhooks

A webhook is a delivery destination: once an image is approved, PrivacyHub sends the **masked image** to your own HTTP or HTTPS endpoint.

- Set `destination=WEBHOOK` and provide `webhook_url` (via the API or the dashboard).
- PrivacyHub sends a `POST` request as `multipart/form-data` with:
  - `file`: the protected image
  - `filename`, `original_filename`, `source`, and `destination` (`WEBHOOK`)
  - `job_id` (when the image came through the API)
- Your endpoint must reply with a `2xx` status code; any other response is treated as a failed delivery.
- The request times out after 60 seconds.
