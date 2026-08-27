from pathlib import Path
import sys

from privacy_engine.pipeline import PrivacyEngine
from privacy_engine.human_verification import HumanVerification


# ============================================================
# PRIVACY TYPES
# ============================================================

PRIVACY_OPTIONS = {
    "1": ("FACE", "Faces"),
    "2": ("PLATE", "License Plates"),
    "3": ("EMAIL", "Email Addresses"),
    "4": ("PHONE", "Phone Numbers"),
    "5": ("NAME", "Names"),
    "6": ("ID", "ID / Identification Numbers"),
}


# ============================================================
# DISPLAY OPTIONS
# ============================================================

def show_privacy_options():

    print()
    print("--------------------------------------")
    print("SELECT INFORMATION TO PROTECT")
    print("--------------------------------------")

    for number, (_, label) in PRIVACY_OPTIONS.items():

        print(
            f"[{number}] {label}"
        )

    print("[A] Select ALL")
    print()


# ============================================================
# GET USER SELECTION
# ============================================================

def get_selected_types():

    show_privacy_options()

    while True:

        choice = input(
            "Enter your selection "
            "(example: 1,2,4): "
        ).strip().upper()

        # ----------------------------------------------------
        # Select everything
        # ----------------------------------------------------

        if choice == "A":

            selected_types = [
                privacy_type
                for privacy_type, _ in PRIVACY_OPTIONS.values()
            ]

            return selected_types

        # ----------------------------------------------------
        # Parse individual selections
        # ----------------------------------------------------

        choices = [
            item.strip()
            for item in choice.split(",")
            if item.strip()
        ]

        # ----------------------------------------------------
        # Validate selection
        # ----------------------------------------------------

        invalid_choices = [
            item
            for item in choices
            if item not in PRIVACY_OPTIONS
        ]

        if invalid_choices:

            print()
            print(
                "Invalid selection:",
                ", ".join(invalid_choices)
            )

            print(
                "Please choose numbers from 1 to 6, "
                "or A for all."
            )

            continue

        # ----------------------------------------------------
        # Convert numbers to privacy types
        # ----------------------------------------------------

        selected_types = []

        for item in choices:

            privacy_type = PRIVACY_OPTIONS[item][0]

            if privacy_type not in selected_types:

                selected_types.append(
                    privacy_type
                )

        if not selected_types:

            print(
                "Please select at least one option."
            )

            continue

        return selected_types


# ============================================================
# MAIN
# ============================================================

def main():

    # ========================================================
    # CHECK INPUT ARGUMENT
    # ========================================================

    if len(sys.argv) < 2:

        print()
        print(
            "Usage:"
        )

        print(
            'python run_privacy.py "path/to/image.jpg"'
        )

        print()

        return

    image_path = Path(
        sys.argv[1]
    )

    # ========================================================
    # CHECK IMAGE
    # ========================================================

    if not image_path.exists():

        print()
        print(
            f"ERROR: Image not found: {image_path}"
        )

        return

    # ========================================================
    # OUTPUT PATH
    # ========================================================

    output_dir = Path(
        "privacy_module/output"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_path = (
        output_dir
        / f"masked_{image_path.name}"
    )

    # ========================================================
    # HEADER
    # ========================================================

    print()
    print("======================================")
    print("PRIVACY PRESERVING ANNOTATION")
    print("======================================")

    print(
        f"Input: {image_path}"
    )

    # ========================================================
    # USER SELECTS PRIVACY TYPES
    # ========================================================

    selected_types = get_selected_types()

    print()
    print("--------------------------------------")
    print("SELECTED PRIVACY TYPES")
    print("--------------------------------------")

    for privacy_type in selected_types:

        print(
            f"✓ {privacy_type}"
        )

    # ========================================================
    # CREATE PRIVACY ENGINE
    # ========================================================

    engine = PrivacyEngine()

    # ========================================================
    # PROCESS IMAGE
    # ========================================================

    print()
    print("Processing image...")
    print()

    result = engine.process(
        image_path,
        output_path,
        selected_types=selected_types
    )

    # ========================================================
    # DETECTION SUMMARY
    # ========================================================

    print()
    print("--------------------------------------")
    print("PRIVACY DETECTION SUMMARY")
    print("--------------------------------------")

    print(
        f"Faces detected: "
        f"{len(result.get('faces', []))}"
    )

    print(
        f"License plates detected: "
        f"{len(result.get('plates', []))}"
    )

    print(
        f"Text PII detected: "
        f"{len(result.get('text_pii', []))}"
    )

    print(
        f"Masked regions: "
        f"{len(result.get('all_regions', []))}"
    )

    print(
        f"Review status: "
        f"{result.get('review_status')}"
    )

    print(
        f"Masked output: "
        f"{result.get('output_path')}"
    )

    # ========================================================
    # HUMAN VERIFICATION
    # ========================================================

    verifier = HumanVerification()

    if verifier.requires_review(result):

        print()
        print("======================================")
        print("HUMAN REVIEW REQUIRED")
        print("======================================")

        print()
        print(
            "The image contains detections "
            "that require human verification."
        )

        print()
        print(
            "Masked image:"
        )

        print(
            result["output_path"]
        )

        while True:

            print()
            print("--------------------------------------")
            print("HUMAN VERIFICATION")
            print("--------------------------------------")

            print("[A] Approve")
            print("[R] Reject")
            print("[Q] Quit")

            decision = input(
                "Your decision: "
            ).strip().upper()

            # ------------------------------------------------
            # APPROVE
            # ------------------------------------------------

            if decision == "A":

                verification_result = (
                    verifier.approve(
                        result["output_path"]
                    )
                )

                print()
                print(
                    "✓ HUMAN DECISION: APPROVED"
                )

                print(
                    "Final output:",
                    verification_result[
                        "final_output"
                    ]
                )

                break

            # ------------------------------------------------
            # REJECT
            # ------------------------------------------------

            elif decision == "R":

                verification_result = (
                    verifier.reject(
                        result["output_path"]
                    )
                )

                print()
                print(
                    "✗ HUMAN DECISION: REJECTED"
                )

                print(
                    "Rejected output:",
                    verification_result[
                        "rejected_output"
                    ]
                )

                break

            # ------------------------------------------------
            # QUIT
            # ------------------------------------------------

            elif decision == "Q":

                print()
                print(
                    "Human verification cancelled."
                )

                break

            else:

                print()
                print(
                    "Invalid choice."
                )

                print(
                    "Please enter A, R, or Q."
                )

    # ========================================================
    # AUTOMATIC APPROVAL
    # ========================================================

    else:

        print()
        print(
            "✓ No human verification required."
        )

        print(
            "Privacy-safe output:",
            result["output_path"]
        )

    # ========================================================
    # COMPLETE
    # ========================================================

    print()
    print("======================================")
    print("PROCESS COMPLETE")
    print("======================================")
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()