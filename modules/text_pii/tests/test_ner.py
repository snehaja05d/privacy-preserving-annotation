import spacy


nlp = spacy.load("en_core_web_sm")


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
    doc = nlp(text)

    print("\nTEXT:", text)

    if not doc.ents:
        print("No entities detected.")
        continue

    for ent in doc.ents:
        print(
            "ENTITY:", ent.text,
            "| LABEL:", ent.label_,
            "| START:", ent.start_char,
            "| END:", ent.end_char
        )