from modules.text_pii.pipeline import (
    TextPIIPipeline
)


IMAGE_PATH = (
    "data/text_pii/controlled_pii/images/"
    "case_010_multiple.jpg"
)

OUTPUT_PATH = (
    "data/text_pii/controlled_pii/"
    "masked_case_010_multiple.jpg"
)


pipeline = TextPIIPipeline(
    default_region="IN"
)


results = pipeline.process(
    IMAGE_PATH,
    OUTPUT_PATH
)


print("\nTEXT PII MASKING TEST")
print("=" * 70)


for result in results:

    print(
        f"\nPII TYPE: "
        f"{result['pii_type']}"
    )

    print(
        f"TEXT: "
        f"{result['text']}"
    )

    print(
        f"MASK BOXES: "
        f"{result['mask_bboxes']}"
    )

print("\nMASKING COMPLETE")
print("=" * 70)

print(
    f"Saved to: {OUTPUT_PATH}"
)