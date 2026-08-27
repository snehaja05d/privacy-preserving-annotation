from transformers import pipeline


ner = pipeline(
    "ner",
    model="dslim/bert-base-NER",
    aggregation_strategy="simple"
)


test_cases = [
    # Strong name context
    "Customer: Snehaja D",
    "Name: Rahul Sharma",
    "Mr. Arjun Reddy",
    "Patient: Priya Kumar",
    "Employee: John Smith",

    # Potentially ambiguous
    "Name: Jordan",
    "Customer: Jordan",
    "Customer: Washington",

    # Potential false-positive situations
    "Company: John Smith Enterprises",
    "Store Owner: Snehaja D",
    "Company: Jordan Electronics",
    "Address: Washington",
]


for text in test_cases:

    print("\nTEXT:", text)

    results = ner(text)

    if not results:
        print("No entities detected.")
        continue

    for entity in results:
        print(
            "ENTITY:", entity["word"],
            "| LABEL:", entity["entity_group"],
            "| SCORE:", round(entity["score"], 4),
            "| START:", entity["start"],
            "| END:", entity["end"]
        )