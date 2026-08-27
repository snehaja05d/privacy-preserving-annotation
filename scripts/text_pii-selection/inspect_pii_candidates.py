import pandas as pd


# Load candidate labels
df = pd.read_csv(
    "data/text_pii/pii_candidates.csv"
)


# Show examples from each category
for category in ["PHONE", "DATE", "EMAIL", "REVIEW"]:

    print()
    print("=" * 50)
    print(category)
    print("=" * 50)

    examples = df[
        df["candidate_type"] == category
    ].head(20)

    for _, row in examples.iterrows():
        print(
            f"{row['image_id']} | "
            f"{row['text']}"
        )