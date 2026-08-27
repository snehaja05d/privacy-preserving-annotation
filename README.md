# privacy-preserving-annotation
Configurable privacy-preserving preprocessing and desensitisation layer for automotive data annotation.
# Privacy-Preserving Annotation System

A privacy-preserving image annotation system that protects sensitive information in images before they are sent to an annotation platform.

## Features

- Image upload and processing
- Face detection and masking
- License plate detection and masking
- Privacy-safe image generation
- Human review and approval
- Approved and rejected image management
- Xtreme1 dataset verification
- Upload approved images to Xtreme1
- Verification that uploaded images appear in the Xtreme1 dataset

---

## Workflow

```text
Original Image
      ↓
Privacy Detection
      ↓
Face / License Plate Masking
      ↓
Privacy-Safe Image
      ↓
Human Review
      ↓
Approve / Reject
      ↓
Approved Image
      ↓
Xtreme1 Upload
      ↓
Xtreme1 Dataset