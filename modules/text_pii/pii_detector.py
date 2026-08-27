import re
import phonenumbers
from transformers import pipeline


# ============================================================
# PHONE CONTEXT
# ============================================================

PHONE_CONTEXT_WORDS = {
    "phone",
    "mobile",
    "telephone",
    "tel",
    "contact",
    "call",
    "whatsapp",
}


NON_PHONE_CONTEXT_WORDS = {
    "invoice",
    "amount",
    "total",
    "order",
    "reference",
    "gst",
    "tax",
    "product",
    "receipt",
    "transaction",
}


# ============================================================
# NAME NER MODEL
# ============================================================

name_ner = pipeline(
    "ner",
    model="dslim/bert-base-NER",
    aggregation_strategy="simple"
)


# ============================================================
# PHONE CONTEXT HELPER
# ============================================================

def get_phone_context(text, start, end):

    context_words = []

    for match in re.finditer(
        r"[a-zA-Z]+",
        text.lower()
    ):

        word = match.group()

        if (
            word in PHONE_CONTEXT_WORDS
            or word in NON_PHONE_CONTEXT_WORDS
        ):

            distance = min(
                abs(match.start() - end),
                abs(start - match.end())
            )

            context_words.append(
                (distance, word)
            )

    if not context_words:
        return "AMBIGUOUS"

    context_words.sort()

    nearest_word = context_words[0][1]

    if nearest_word in PHONE_CONTEXT_WORDS:
        return "PHONE"

    if nearest_word in NON_PHONE_CONTEXT_WORDS:
        return "NON_PHONE"

    return "AMBIGUOUS"


# ============================================================
# OCR WORD → PII BBOX HELPER
# ============================================================

def find_text_bbox(text, target, words):
    """
    Map a detected PII text span back to OCR word coordinates.

    Handles:

    1. Full OCR-word matches
    2. Multiple OCR words forming one PII value
    3. Partial overlap when OCR combines punctuation
       with PII text

    Example:

        OCR word:
            ": +"

        Detected PII:
            "+91 98765 43210"

        Instead of masking the complete ": +" OCR box,
        estimate the portion corresponding to the PII.
    """

    if not text or not target or not words:
        return None

    # --------------------------------------------------------
    # Find PII text inside OCR line
    # --------------------------------------------------------

    start = text.find(target)

    if start == -1:
        return None

    end = start + len(target)

    matched_boxes = []

    current_position = 0

    # --------------------------------------------------------
    # Map OCR words to character positions in OCR text
    # --------------------------------------------------------

    for word in words:

        word_text = word.get("text", "")
        bbox = word.get("bbox")

        if not word_text or not bbox:
            continue

        # Find this OCR word in the OCR line.
        word_start = text.find(
            word_text,
            current_position
        )

        if word_start == -1:
            continue

        word_end = (
            word_start
            + len(word_text)
        )

        current_position = word_end

        # Ignore whitespace-only OCR tokens
        if not word_text.strip():
            continue

        # ----------------------------------------------------
        # No overlap between OCR word and PII
        # ----------------------------------------------------

        if (
            word_end <= start
            or word_start >= end
        ):
            continue

        # ----------------------------------------------------
        # Determine exact character overlap
        # ----------------------------------------------------

        overlap_start = max(
            start,
            word_start
        )

        overlap_end = min(
            end,
            word_end
        )

        # Position of overlap inside OCR word
        relative_start = (
            overlap_start
            - word_start
        )

        relative_end = (
            overlap_end
            - word_start
        )

        word_length = len(word_text)

        if word_length <= 0:
            continue

        x1, y1, x2, y2 = map(
            float,
            bbox
        )

        word_width = x2 - x1

        if word_width <= 0:
            continue

        # ----------------------------------------------------
        # FULL OCR WORD belongs to PII
        # ----------------------------------------------------

        if (
            relative_start <= 0
            and relative_end >= word_length
        ):

            matched_boxes.append(
                [
                    x1,
                    y1,
                    x2,
                    y2
                ]
            )

            continue

        # ----------------------------------------------------
        # PARTIAL OCR WORD belongs to PII
        #
        # Example:
        #
        # OCR:
        #     ": +"
        #
        # PII:
        #       "+"
        #
        # We estimate the x-coordinate of the PII
        # portion using the character position.
        # ----------------------------------------------------

        char_width = (
            word_width
            / word_length
        )

        partial_x1 = (
            x1
            + relative_start * char_width
        )

        partial_x2 = (
            x1
            + relative_end * char_width
        )

        matched_boxes.append(
            [
                partial_x1,
                y1,
                partial_x2,
                y2
            ]
        )

    # --------------------------------------------------------
    # No OCR boxes matched
    # --------------------------------------------------------

    if not matched_boxes:
        return None

    # --------------------------------------------------------
    # Combine all matched regions
    # --------------------------------------------------------

    x1 = min(
        box[0]
        for box in matched_boxes
    )

    y1 = min(
        box[1]
        for box in matched_boxes
    )

    x2 = max(
        box[2]
        for box in matched_boxes
    )

    y2 = max(
        box[3]
        for box in matched_boxes
    )

    return [
        int(round(x1)),
        int(round(y1)),
        int(round(x2)),
        int(round(y2))
    ]


# ============================================================
# EMAIL DETECTOR
# ============================================================

def detect_email(
    text,
    words=None,
    confidence=None
):

    pattern = (
        r"\b"
        r"[A-Za-z0-9._%+-]+"
        r"@"
        r"[A-Za-z0-9.-]+"
        r"\."
        r"[A-Za-z]{2,}"
        r"\b"
    )

    matches = re.finditer(
        pattern,
        text
    )

    results = []

    for match in matches:

        email = match.group()

        bbox = None

        if words is not None:

            bbox = find_text_bbox(
                text,
                email,
                words
            )

        results.append({

            "text": email,

            "pii_type": "EMAIL",

            "status": "CONFIRMED",

            "confidence": confidence,

            "bbox": bbox

        })

    return results


# ============================================================
# PHONE DETECTOR
# ============================================================

def detect_phone(
    text,
    default_region=None,
    words=None,
    confidence=None
):

    results = []

    for match in phonenumbers.PhoneNumberMatcher(
        text,
        default_region
    ):

        number = match.number

        raw_number = match.raw_string

        # ----------------------------------------------------
        # Reject impossible phone numbers
        # ----------------------------------------------------

        if not phonenumbers.is_possible_number(
            number
        ):
            continue

        # ----------------------------------------------------
        # Determine surrounding context
        # ----------------------------------------------------

        context = get_phone_context(
            text,
            match.start,
            match.end
        )

        # ----------------------------------------------------
        # Find OCR coordinates
        # ----------------------------------------------------

        bbox = None

        if words is not None:

            bbox = find_text_bbox(
                text,
                raw_number,
                words
            )

        # ----------------------------------------------------
        # CONFIRMED PHONE
        # ----------------------------------------------------

        if context == "PHONE":

            results.append({

                "text": raw_number,

                "pii_type": "PHONE",

                "status": "CONFIRMED",

                "confidence": confidence,

                "bbox": bbox

            })

        # ----------------------------------------------------
        # NON-PHONE
        # ----------------------------------------------------

        elif context == "NON_PHONE":

            results.append({

                "text": raw_number,

                "pii_type": None,

                "status": "NON_PHONE",

                "confidence": confidence,

                "bbox": bbox

            })

        # ----------------------------------------------------
        # AMBIGUOUS
        # ----------------------------------------------------

        else:

            results.append({

                "text": raw_number,

                "pii_type": "PHONE",

                "status": "AMBIGUOUS",

                "confidence": confidence,

                "bbox": bbox

            })

    return results


# ============================================================
# NAME DETECTOR
# ============================================================

def detect_name(
    text,
    words
):

    results = []

    # --------------------------------------------------------
    # Run BERT NER
    # --------------------------------------------------------

    entities = name_ner(text)

    for entity in entities:

        # Only PERSON entities
        if entity["entity_group"] != "PER":
            continue

        name_text = entity["word"].strip()

        start = entity["start"]

        end = entity["end"]

        matched_words = []

        current_position = 0

        # ----------------------------------------------------
        # Match BERT entity to OCR words
        # ----------------------------------------------------

        for word in words:

            word_text = word["text"]

            word_start = text.find(
                word_text,
                current_position
            )

            if word_start == -1:
                continue

            word_end = (
                word_start
                + len(word_text)
            )

            current_position = word_end

            # Check overlap
            if (
                word_end > start
                and word_start < end
            ):

                if word_text.strip():

                    matched_words.append(
                        word
                    )

        # ----------------------------------------------------
        # Couldn't map entity
        # ----------------------------------------------------

        if not matched_words:
            continue

        # ----------------------------------------------------
        # Combine OCR word boxes
        # ----------------------------------------------------

        x1 = min(
            word["bbox"][0]
            for word in matched_words
        )

        y1 = min(
            word["bbox"][1]
            for word in matched_words
        )

        x2 = max(
            word["bbox"][2]
            for word in matched_words
        )

        y2 = max(
            word["bbox"][3]
            for word in matched_words
        )

        # ----------------------------------------------------
        # Final NAME result
        # ----------------------------------------------------

        results.append({

            "text": name_text,

            "pii_type": "NAME",

            "status": "CONFIRMED",

            "confidence": float(
                entity["score"]
            ),

            "bbox": [
                x1,
                y1,
                x2,
                y2
            ]

        })

    return results


# ============================================================
# ID DETECTOR CONFIGURATION
# ============================================================

ID_CONTEXT_WORDS = {

    "id",

    "identification",

    "identifier",

    "employee",

    "customer",

    "member",

    "patient",

    "student",

    "account",

    "user",

    "registration",

    "license",

}


ID_STRONG_CONTEXT = {

    "id number",

    "identification number",

    "employee id",

    "customer id",

    "member id",

    "patient id",

    "student id",

    "account id",

    "user id",

    "registration id",

    "license number",

    "transaction id",

}


NON_ID_CONTEXT_WORDS = {

    "invoice",

    "order",

    "reference",

    "transaction",

    "amount",

    "total",

    "phone",

    "mobile",

    "telephone",

    "tel",

    "contact",

    "call",

}


# ============================================================
# ID DETECTOR
# ============================================================

def detect_id(
    text,
    words=None,
    confidence=None
):
    """
    Detect likely identification numbers/identifiers.

    The detector uses:

    1. Context around the candidate
    2. Identifier-like structure
    3. Exclusion of known non-ID contexts

    Ambiguous candidates are not automatically
    classified as ID.
    """

    results = []

    # --------------------------------------------------------
    # Normalize text
    # --------------------------------------------------------

    normalized = text.lower()

    # --------------------------------------------------------
    # Find ID-related context
    # --------------------------------------------------------

    strong_context = any(
        phrase in normalized
        for phrase in ID_STRONG_CONTEXT
    )

    context_matches = []

    for word in re.finditer(
        r"[a-zA-Z]+",
        normalized
    ):

        if word.group() in ID_CONTEXT_WORDS:

            context_matches.append(
                word.group()
            )

    non_id_context = any(
        word in NON_ID_CONTEXT_WORDS
        for word in re.findall(
            r"[a-zA-Z]+",
            normalized
        )
    )

    # --------------------------------------------------------
    # Find identifier candidates
    #
    # Allows:
    #
    # ID123456789
    # EMP2026001
    # A7F92K31
    # 1234-5678
    # ABC-12345
    # --------------------------------------------------------

    candidates = re.finditer(
        r"\b[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*\b",
        text
    )

    for match in candidates:

        candidate = match.group()

        # ----------------------------------------------------
        # Ignore very short candidates
        # ----------------------------------------------------

        if len(candidate) < 4:
            continue

        # ----------------------------------------------------
        # Candidate must contain at least one digit
        # ----------------------------------------------------

        if not re.search(
            r"\d",
            candidate
        ):
            continue

        # ----------------------------------------------------
        # Avoid pure dates
        # ----------------------------------------------------

        if re.fullmatch(
            r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}",
            candidate
        ):
            continue

        # ----------------------------------------------------
        # Avoid obvious phone candidates
        # ----------------------------------------------------

        digits_only = re.sub(
            r"\D",
            "",
            candidate
        )

        if (
            len(digits_only) >= 10
            and candidate.isdigit()
        ):
            continue

        # ----------------------------------------------------
        # Determine surrounding context
        # ----------------------------------------------------

        candidate_start = match.start()

        candidate_end = match.end()

        before_text = normalized[
            max(
                0,
                candidate_start - 40
            ):
            candidate_start
        ]

        after_text = normalized[
            candidate_end:
            min(
                len(normalized),
                candidate_end + 40
            )
        ]

        surrounding_text = (
            before_text
            + " "
            + after_text
        )

        has_strong_context = any(
            phrase in surrounding_text
            for phrase in ID_STRONG_CONTEXT
        )

        has_non_id_context = any(
            word in surrounding_text.split()
            for word in NON_ID_CONTEXT_WORDS
        )

        # ----------------------------------------------------
        # Decision
        # ----------------------------------------------------

        if (
            has_non_id_context
            and not has_strong_context
        ):
            continue

        if not (
            strong_context
            or context_matches
            or has_strong_context
        ):

            # No useful ID context.
            # Don't force ambiguous values into ID.
            continue

        # ----------------------------------------------------
        # Find OCR words overlapping candidate
        # ----------------------------------------------------

        matched_words = []

        if words:

            current_position = 0

            for word in words:

                word_text = word["text"]

                word_start = text.find(
                    word_text,
                    current_position
                )

                if word_start == -1:
                    continue

                word_end = (
                    word_start
                    + len(word_text)
                )

                current_position = word_end

                if (
                    word_end > candidate_start
                    and word_start < candidate_end
                ):

                    if word_text.strip():

                        matched_words.append(
                            word
                        )

        # ----------------------------------------------------
        # Calculate bbox
        # ----------------------------------------------------

        bbox = None

        if matched_words:

            x1 = min(
                word["bbox"][0]
                for word in matched_words
            )

            y1 = min(
                word["bbox"][1]
                for word in matched_words
            )

            x2 = max(
                word["bbox"][2]
                for word in matched_words
            )

            y2 = max(
                word["bbox"][3]
                for word in matched_words
            )

            bbox = [
                x1,
                y1,
                x2,
                y2
            ]

        # ----------------------------------------------------
        # Confidence
        # ----------------------------------------------------

        result_confidence = (
            float(confidence)
            if confidence is not None
            else 1.0
        )

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        if has_strong_context:

            status = "CONFIRMED"

        else:

            status = "AMBIGUOUS"

        # ----------------------------------------------------
        # Final ID result
        # ----------------------------------------------------

        results.append({

            "text": candidate,

            "pii_type": "ID",

            "status": status,

            "confidence": result_confidence,

            "bbox": bbox

        })

    return results