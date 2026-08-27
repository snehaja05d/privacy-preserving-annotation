from modules.text_pii.pii_detector import detect_id


TEST_CASES = [
    "Employee ID: ABC12345",
    "Customer ID: CUST-88291",
    "Account ID: ACC20261234",
    "Patient ID: P-928371",
    "Registration ID: REG/2026/00451",

    "Invoice Number: 123456789",
    "Order Number: 123456789",
    "Reference Number: 123456789",
    "Transaction ID: TXN-84739201",
    "Phone: 9876543210",
    "Mobile: +91 98765 43210",
    "Total Amount: 9876543210",

    "123456789",
    "ABC12345",
]


print("\nID GENERALIZATION TEST")
print("=" * 70)

for text in TEST_CASES:

    results = detect_id(text)

    print(f"\nTEXT: {text}")

    if not results:
        print("RESULT: No ID detected.")
    else:
        for result in results:
            print("RESULT:", result)