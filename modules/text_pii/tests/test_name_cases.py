from transformers import pipeline


name_ner = pipeline(
    "ner",
    model="dslim/bert-base-NER",
    aggregation_strategy="simple"
)


test_cases = [
    "Customer: John Smith",
    "Name: Rahul Sharma",
    "Mr. Arjun Reddy",
    "Patient: Priya Kumar",
    "Employee: John Smith",
    "Name: Jordan",
    "Customer: Jordan",
    "Customer: Washington",
    "Company: John Smith Enterprises",
    "Store Owner: Snehaja D",
    "Company: Jordan Electronics",
    "Address: Washington",
]


print("\nNAME ROBUSTNESS TEST")
print("=" * 70)


for text in test_cases:

    entities = name_ner(text)

    print("\nTEXT:", text)

    if not entities:
        print("  No entities detected.")
        continue

    for entity in entities:
        print(
            f"  ENTITY: {entity['word']} "
            f"| LABEL: {entity['entity_group']} "
            f"| SCORE: {entity['score']:.4f}"
        )