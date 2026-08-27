import pandas as pd
import re


# --------------------------------------------------
# 1. Load OCR ground truth
# --------------------------------------------------

input_file = (
    "data/text_pii/sroie_text_ground_truth.csv"
)

df = pd.read_csv(input_file)

print(f"Loaded {len(df)} text regions.")


# --------------------------------------------------
# 2. Detect obvious PII patterns
# --------------------------------------------------

def detect_candidate(text):

    text = str(text).strip()

    # Email
    if re.search(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        text
    ):
        return "EMAIL"

    # Phone number
    if re.search(
        r"(?<!\d)(?:\+?\d[\d\s\-()]{7,}\d)(?!\d)",
        text
    ):
        return "PHONE"

    # Date
    if re.search(
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        text
    ):
        return "DATE"

    if re.search(
        r"\b\d{1,2}\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+\d{2,4}\b",
        text.upper()
    ):
        return "DATE"

    return "REVIEW"


# --------------------------------------------------
# 3. Apply candidate detection
# --------------------------------------------------

df["candidate_type"] = df["text"].apply(
    detect_candidate
)


# --------------------------------------------------
# 4. Save candidate file
# --------------------------------------------------

output_file = (
    "data/text_pii/pii_candidates.csv"
)

df.to_csv(
    output_file,
    index=False
)


# --------------------------------------------------
# 5. Show summary
# --------------------------------------------------

print()
print("DONE!")
print(f"Saved to: {output_file}")
print()
print("Candidate summary:")
print(df["candidate_type"].value_counts())