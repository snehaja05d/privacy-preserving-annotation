# Privacy-Preserving Annotation System

A privacy-preserving AI platform that detects and anonymizes sensitive information in images before they are used for annotation.

The system detects **faces, license plates, and text-based PII** such as names, phone numbers, email addresses, and IDs. Detected information is masked before the image is sent for annotation, helping reduce exposure of sensitive data.

The platform also supports **human-in-the-loop review** for cases where automatic detection requires verification. Images marked as **Review Required** can be manually checked and approved before delivery.

---

## How It Works

```text
Image / External Application
            ↓
       PrivacyHub
            ↓
   Privacy Detection
     ↙      ↓       ↘
  Faces   Plates    Text PII
     ↘      ↓       ↙
       Privacy Masking
            ↓
    Confidence Check
            ↓
     ┌──────┴──────┐
     ↓             ↓
  Approved    Review Required
     ↓             ↓
     └──────┬──────┘
            ↓
     Delivery & Integration
        ↙           ↘
 Return Image      Xtreme1
```

PrivacyHub provides a **web interface built with FastAPI** and a **REST API** for external applications.

External applications can send images to PrivacyHub using a **Bearer token**, receive a job ID, track processing status, and retrieve the processed image after completion.

The API also includes **token management, API usage tracking, rate limiting, and job tracking**.

For annotation workflows, approved privacy-safe images can be delivered directly to **Xtreme1** using the Xtreme1 dataset ID and Bearer token.

---

## Main Features

* Face detection and anonymization
* License plate detection and anonymization
* OCR-based text detection
* PII detection for names, emails, phone numbers, IDs, etc.
* Confidence-based processing
* Human review for uncertain detections
* FastAPI REST API
* Bearer-token authentication
* API token generation, expiry, and revocation
* API usage tracking
* Rate limiting
* Asynchronous job tracking
* Return Image delivery
* Xtreme1 integration
* Web-based PrivacyHub interface

---

## Technologies

* Python
* FastAPI
* OpenCV
* YOLO
* PaddleOCR
* PyTorch
* Hugging Face Transformers
* ONNX Runtime
* SQLite
* Xtreme1
* HTML / CSS / JavaScript

---

## Project Structure

```text
privacy-preserving-annotation/
│
├── data/
├── database/
├── evaluation/
├── modules/
├── privacy_engine/
├── privacy_module/
├── privacyhub_web/
├── scripts/
│
├── requirements.txt
├── requirements-full.txt
├── run_privacy.py
└── structure.txt
```

---

## Installation

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

**Windows PowerShell:**

```powershell
.\.venv\Scripts\Activate.ps1
```

### 4. Install Dependencies

```powershell
pip install -r requirements.txt
```

For the complete dependency set:

```powershell
pip install -r requirements-full.txt
```

---

## Running PrivacyHub

Start the web application with:

```powershell
.\.venv\Scripts\python.exe .\privacyhub_web\run_web.py
```

Once the server starts, open the local address shown in the terminal.

FastAPI API documentation is available at:

```text
http://127.0.0.1:8501/docs
```

---

## API Workflow

External applications can communicate with PrivacyHub through the REST API:

```text
External Application
        ↓
PrivacyHub API
        ↓
Privacy Processing
        ↓
Job ID
        ↓
Check Job Status
        ↓
Review if Required
        ↓
Retrieve / Deliver Approved Image
```

API requests require a valid **PrivacyHub Bearer token**.

---

## Xtreme1 Delivery

Approved privacy-safe images can be delivered to an **Xtreme1 dataset** through the **Delivery & Integrations** section.

Required:

* Xtreme1 Dataset ID
* Xtreme1 Bearer Token
* Approved privacy-safe image

The system sends only the protected image to the annotation environment.

---

