from pathlib import Path
import shutil


class HumanVerification:

    def __init__(
        self,
        review_dir="privacy_module/review"
    ):

        self.review_dir = Path(
            review_dir
        )

        self.approved_dir = (
            self.review_dir / "approved"
        )

        self.rejected_dir = (
            self.review_dir / "rejected"
        )

        # Create directories if they don't exist
        self.approved_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        self.rejected_dir.mkdir(
            parents=True,
            exist_ok=True
        )

    # =========================================================
    # CHECK WHETHER HUMAN REVIEW IS REQUIRED
    # =========================================================

    def requires_review(
        self,
        result
    ):

        return result.get(
            "needs_human_review",
            False
        )

    # =========================================================
    # APPROVE
    # =========================================================

    def approve(
        self,
        output_path
    ):

        output_path = Path(
            output_path
        )

        if not output_path.exists():

            raise FileNotFoundError(
                f"Output image not found: {output_path}"
            )

        destination = (
            self.approved_dir
            / output_path.name
        )

        shutil.copy2(
            output_path,
            destination
        )

        return {
            "decision": "APPROVED",
            "source": str(output_path),
            "final_output": str(destination)
        }

    # =========================================================
    # REJECT
    # =========================================================

    def reject(
        self,
        output_path
    ):

        output_path = Path(
            output_path
        )

        if not output_path.exists():

            raise FileNotFoundError(
                f"Output image not found: {output_path}"
            )

        destination = (
            self.rejected_dir
            / output_path.name
        )

        shutil.copy2(
            output_path,
            destination
        )

        return {
            "decision": "REJECTED",
            "source": str(output_path),
            "rejected_output": str(destination)
        }