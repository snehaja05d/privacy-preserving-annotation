# Privacy-Preserving Annotation System

A configurable privacy-preserving preprocessing and desensitisation layer designed to protect sensitive information in images before they are used for computer vision annotation.

The system detects sensitive visual and textual information, applies appropriate masking techniques, evaluates detection confidence, supports human verification, and transfers only approved privacy-safe images to the annotation environment.

---

## Overview

Modern computer vision datasets often contain sensitive information such as:

- Human faces
- Vehicle license plates
- Names
- Phone numbers
- Email addresses
- Addresses
- Identification numbers
- Other personally identifiable information (PII)

This project provides a preprocessing layer between **raw image data** and the **annotation platform**.

Instead of sending the original image directly for annotation, the image first passes through privacy detection and desensitisation.

```text
Raw Image
    │
    ▼
Privacy Detection
    │
    ├── Face Detection
    ├── License Plate Detection
    └── Text / PII Detection
    │
    ▼
Privacy Masking
    │
    ▼
Confidence Evaluation
    │
    ├── High Confidence ─────► Approved
    │
    └── Low Confidence ──────► Human Verification
                                      │
                              ┌───────┴───────┐
                              ▼               ▼
                           Approve          Reject
                              │
                              ▼
                    Privacy-Safe Image
                              │
                              ▼
                         Xtreme1
```

---

# Key Features

### 1. Face Privacy Protection

Detects human faces in images and applies masking to prevent direct identification.

### 2. License Plate Protection

Detects vehicle license plates and masks them before the image is made available for annotation.

### 3. Text PII Detection

Uses OCR-based processing to identify potentially sensitive information contained within image text.

Supported examples include:

- Names
- Phone numbers
- Email addresses
- Addresses
- Identification numbers
- Other configurable PII patterns

### 4. Privacy-Safe Image Generation

The original image is processed to generate a desensitised version while preserving the useful visual information required for annotation.

### 5. Confidence-Based Verification

Detection results can be evaluated using confidence thresholds.

Low-confidence cases can be routed to human verification instead of being automatically approved.

### 6. Human Verification

Provides a review stage where uncertain results can be manually checked before they are transferred to the annotation environment.

### 7. Xtreme1 Integration

Approved privacy-safe images can be transferred to an Xtreme1 annotation dataset.

The system also includes verification of uploaded images.

### 8. Evaluation and Testing

The project includes evaluation scripts and test cases for the text PII pipeline, including controlled and real-world image scenarios.

---

# System Architecture

The system is organized into separate components to keep detection, masking, privacy orchestration, and evaluation modular.

```text
                         ┌─────────────────────┐
                         │     Input Image     │
                         └──────────┬──────────┘
                                    │
                                    ▼
                    ┌────────────────────────────┐
                    │    Privacy Detection       │
                    ├────────────────────────────┤
                    │ • Face Detection            │
                    │ • License Plate Detection   │
                    │ • OCR / Text Detection      │
                    │ • PII Detection             │
                    └─────────────┬──────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │     Privacy Masking         │
                    └─────────────┬──────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │   Confidence Evaluation     │
                    └─────────────┬──────────────┘
                                  │
                     ┌────────────┴────────────┐
                     │                         │
                     ▼                         ▼
              High Confidence            Low Confidence
                     │                         │
                     │                         ▼
                     │                ┌─────────────────┐
                     │                │ Human Review    │
                     │                └────────┬────────┘
                     │                         │
                     └────────────┬────────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ Approved Image      │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │ Xtreme1 Annotation  │
                       └─────────────────────┘
```

---

# Project Structure

```text
privacy-preserving-annotation/
│
├── app.py
├── run_privacy.py
├── requirements.txt
├── requirements-full.txt
├── README.md
│
├── modules/
│   │
│   ├── text_pii/
│   │   ├── ocr.py
│   │   ├── pii_detector.py
│   │   ├── pii_aligner.py
│   │   ├── masker.py
│   │   ├── pipeline.py
│   │   └── tests/
│   │
│   └── visual_privacy/
│       ├── detector.py
│       ├── masker.py
│       ├── pipeline.py
│       └── __init__.py
│
├── privacy_engine/
│   ├── pipeline.py
│   ├── human_verification.py
│   ├── paths.py
│   └── send_to_xtreme1.py
│
├── privacy_module/
│   ├── input/
│   └── models/
│
├── evaluation/
│   └── text_pii/
│       ├── evaluate_controlled.py
│       ├── evaluate_icdar2015.py
│       ├── evaluate_sroie.py
│       └── tests/
│
├── data/
│   └── text_pii/
│
└── scripts/
    └── text_pii-selection/
```

---

# Processing Pipeline

## Step 1 — Image Input

An image is provided to the privacy-preserving preprocessing system.

## Step 2 — Sensitive Information Detection

The system analyzes the image for different categories of sensitive information.

### Visual information

- Faces
- License plates

### Textual information

- Names
- Phone numbers
- Email addresses
- Addresses
- IDs and other PII

## Step 3 — Masking

Detected sensitive regions are masked using the appropriate privacy-preserving technique.

The goal is to remove identifiable information while retaining the useful context of the image.

## Step 4 — Confidence Evaluation

Detection results are evaluated against configured confidence thresholds.

Results that require additional verification can be routed to the human review stage.

## Step 5 — Human Verification

A reviewer can inspect uncertain results and decide whether the processed image should be approved or rejected.

## Step 6 — Annotation Platform

Approved privacy-safe images can be transferred to the Xtreme1 annotation environment.

---

# Text PII Pipeline

The text privacy component follows a dedicated OCR and PII processing pipeline:

```text
Image
  │
  ▼
OCR
  │
  ▼
Extracted Text + Word Locations
  │
  ▼
PII Detection
  │
  ▼
PII-to-Image Alignment
  │
  ▼
PII Bounding Regions
  │
  ▼
Mask Sensitive Text
  │
  ▼
Privacy-Safe Image
```

This approach allows sensitive textual information to be detected and mapped back to its corresponding location within the original image.

---

# Visual Privacy Pipeline

Visual privacy processing handles image regions that can directly identify people or vehicles.

```text
Image
  │
  ├──────────────► Face Detection
  │
  └──────────────► License Plate Detection
                         │
                         ▼
                    Region Masking
                         │
                         ▼
                 Privacy-Safe Image
```

---

# Human Verification

Automatic detection systems can produce uncertain results, particularly in difficult real-world images.

To address this, the system supports a human verification stage.

```text
Detection
    │
    ▼
Confidence Check
    │
    ├── High Confidence ──► Continue
    │
    └── Low Confidence ───► Human Review
                                │
                          ┌─────┴─────┐
                          ▼           ▼
                       Approve      Reject
```

This provides an additional validation layer before privacy-safe images are used for annotation.

---

# Evaluation

The repository contains evaluation and testing components for the text PII system.

Evaluation scripts include:

```text
evaluation/text_pii/
│
├── evaluate_controlled.py
├── evaluate_icdar2015.py
├── evaluate_sroie.py
└── tests/
```

The evaluation setup includes:

- Controlled PII test images
- Real-world document images
- OCR evaluation
- PII detection tests
- Bounding-box alignment tests
- Masking tests
- End-to-end pipeline tests

---

# Technologies

| Technology | Purpose |
|---|---|
| Python | Core implementation |
| Streamlit | Application interface |
| OpenCV | Image processing |
| YOLO | Visual object detection |
| PaddleOCR | Optical character recognition |
| ONNX Runtime | Model inference |
| scikit-learn | Evaluation and supporting utilities |
| Xtreme1 | Image annotation environment |

---

# Installation

## 1. Clone the Repository

```bash
git clone https://github.com/snehaja05d/privacy-preserving-annotation.git
cd privacy-preserving-annotation
```

## 2. Create a Virtual Environment

### Windows

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

For the complete dependency set:

```bash
pip install -r requirements-full.txt
```

---

# Running the Application

Start the Streamlit application:

```bash
streamlit run app.py
```

The terminal will provide the local URL for accessing the application.

---

# Privacy and Data Handling

The system is designed around a privacy-first preprocessing workflow.

```text
Original Data
     │
     ▼
Privacy Processing
     │
     ▼
Sensitive Information Masked
     │
     ▼
Human Verification
     │
     ▼
Approved Privacy-Safe Data
     │
     ▼
Annotation
```

The purpose of the preprocessing stage is to reduce the exposure of sensitive information during dataset annotation.

---

# Configuration

Privacy processing behavior can be configured through the project's processing modules and confidence thresholds.

Examples include:

- Detection confidence thresholds
- Minimum detected region sizes
- Input/output directories
- Privacy processing stages

Configuration should be reviewed according to the requirements of the target dataset and annotation workflow.

---

# Intended Use

This system is intended for workflows where images need to be annotated while reducing exposure of personally identifiable or sensitive visual information.

Potential applications include:

- Automotive dataset annotation
- Computer vision dataset preparation
- Privacy-aware data preprocessing
- Research datasets
- Human-in-the-loop annotation workflows
- Pre-annotation desensitisation

---

# Limitations

Automatic privacy detection is not guaranteed to identify every sensitive region in every image.

Performance may vary depending on:

- Image resolution
- Image quality
- Lighting conditions
- Occlusion
- Text orientation
- Detection confidence
- OCR quality

For this reason, the system includes human verification for cases requiring additional review.

---

# Future Improvements

Potential future improvements include:

- Additional PII categories
- Improved multilingual OCR support
- Additional privacy detection models
- More automated evaluation metrics
- Improved human-review interfaces
- Additional annotation platform integrations
- Batch processing optimization
- More extensive real-world benchmarking

---

# License

Add the appropriate project license here.

---

# Project Status

**Status:** Active Development

The system currently includes privacy detection, masking, text PII processing, human verification, evaluation components, and Xtreme1 integration.