from pii_detector import detect_phone
test_cases = [
    "Phone: 9876543210",
    "Mobile: 9876543210",
    "Tel: 9876543210",
    "Contact: 9876543210",
    "Call: 9876543210",

    "Total Amount: 9876543210",
    "Invoice Number: 9876543210",
    "Order Number: 9876543210",
    "Reference Number: 9876543210",

    "9876543210",

    "Phone: +91 98765 43210",
    "Contact: +44 20 7946 0958",
]

test_cases = [
    "Customer: John Smith Phone: 9876543210 Total Amount: 5000",
    "Invoice Number: 123456789 Phone: +91 98765 43210",
    "Total Amount: 9876543210 Contact: +91 91234 56789",
    "Order Number: 12345 Reference Number: 67890",
]

for text in test_cases:
    result = detect_phone(text, default_region="IN")
    print(f"{text} -> {result}")