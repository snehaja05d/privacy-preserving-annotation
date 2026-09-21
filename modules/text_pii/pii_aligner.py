class PIIBBoxAligner:
    
    # =========================================================
    # NORMALIZE TEXT
    # =========================================================

    def _normalize(self, text):

        if text is None:
            return ""

        return str(text).strip().lower()

    # =========================================================
    # TOKENIZE PII TEXT
    #
    # We deliberately preserve:
    #
    #   +
    #   @
    #   .
    #   numbers
    #   words
    #
    # because they are part of the sensitive information.
    # =========================================================

    def _tokens(self, text):

        if not text:
            return []

        text = str(text).strip()

        tokens = []

        current = ""

        for char in text:

            # -------------------------------------------------
            # Whitespace separates tokens
            # -------------------------------------------------

            if char.isspace():

                if current:
                    tokens.append(
                        current.lower()
                    )

                    current = ""

                continue

            # -------------------------------------------------
            # Punctuation is its own token
            # -------------------------------------------------

            if char in "@.+-()/":

                if current:
                    tokens.append(
                        current.lower()
                    )

                    current = ""

                tokens.append(
                    char.lower()
                )

                continue

            current += char

        if current:

            tokens.append(
                current.lower()
            )

        return tokens

    # =========================================================
    # CLEAN OCR WORD
    # =========================================================

    def _clean_ocr_text(self, text):

        if text is None:
            return ""

        return str(text).strip().lower()

    # =========================================================
    # CHECK WHETHER OCR TOKEN BELONGS TO PII
    # =========================================================

    def _find_matching_words(
        self,
        pii_text,
        words
    ):

        pii_tokens = self._tokens(
            pii_text
        )

        if not pii_tokens:
            return []

        # -----------------------------------------------------
        # Normalize OCR words
        # -----------------------------------------------------

        ocr_words = []

        for word in words:

            text = self._clean_ocr_text(
                word.get("text", "")
            )

            bbox = word.get(
                "bbox"
            )

            if not text or not bbox:
                continue

            ocr_words.append({
                "text": text,
                "bbox": bbox
            })

        # -----------------------------------------------------
        # We need to find the PII token sequence inside OCR.
        # -----------------------------------------------------

        for start in range(
            len(ocr_words)
        ):

            matched = []

            pii_index = 0

            for index in range(
                start,
                len(ocr_words)
            ):

                ocr_text = (
                    ocr_words[index]["text"]
                )

                target = (
                    pii_tokens[pii_index]
                )

                # -------------------------------------------------
                # Exact match
                # -------------------------------------------------

                if ocr_text == target:

                    matched.append(
                        ocr_words[index]
                    )

                    pii_index += 1

                    if (
                        pii_index
                        == len(pii_tokens)
                    ):

                        return matched

                    continue

                # -------------------------------------------------
                # OCR may combine punctuation with a token.
                #
                # Example:
                #
                # OCR: ":+" 
                #
                # PII: "+"
                #
                # We must extract only "+"
                # -------------------------------------------------

                if (
                    target
                    and target in ocr_text
                ):

                    position = (
                        ocr_text.find(
                            target
                        )
                    )

                    # -------------------------------------------------
                    # If target is inside OCR token, calculate
                    # approximate character-level horizontal box.
                    # -------------------------------------------------

                    x1, y1, x2, y2 = map(
                        float,
                        ocr_words[index][
                            "bbox"
                        ]
                    )

                    width = (
                        x2 - x1
                    )

                    char_count = max(
                        len(ocr_text),
                        1
                    )

                    char_width = (
                        width
                        / char_count
                    )

                    partial_x1 = (
                        x1
                        + position
                        * char_width
                    )

                    partial_x2 = (
                        partial_x1
                        + char_width
                    )

                    matched.append({
                        "text": target,
                        "bbox": [
                            int(round(
                                partial_x1
                            )),
                            int(round(y1)),
                            int(round(
                                partial_x2
                            )),
                            int(round(y2))
                        ]
                    })

                    pii_index += 1

                    if (
                        pii_index
                        == len(pii_tokens)
                    ):

                        return matched

                    continue

                # -------------------------------------------------
                # If this OCR word doesn't match, abandon this
                # starting position.
                # -------------------------------------------------

                break

        return []

    # =========================================================
    # PUBLIC ALIGNMENT
    # =========================================================

    def align(
        self,
        pii_results,
        ocr_results
    ):

        aligned_results = []

        for pii in pii_results:

            if (
                pii.get("status")
                != "CONFIRMED"
            ):
                continue

            pii_text = pii.get(
                "text"
            )

            if not pii_text:
                continue

            best_match = []

            # -------------------------------------------------
            # Search every OCR line
            # -------------------------------------------------

            for ocr in ocr_results:

                words = ocr.get(
                    "words",
                    []
                )

                if not words:
                    continue

                match = self._find_matching_words(
                    pii_text,
                    words
                )

                if match:

                    best_match = match
                    break

            # -------------------------------------------------
            # Alignment failed
            # -------------------------------------------------

            if not best_match:

                print(
                    f"WARNING: Could not align "
                    f"{pii.get('pii_type')}: "
                    f"{pii_text}"
                )

                continue

            # -------------------------------------------------
            # Build result
            # -------------------------------------------------

            result = dict(pii)

            result["mask_words"] = [
                item["text"]
                for item in best_match
            ]

            result["mask_bboxes"] = [
                item["bbox"]
                for item in best_match
            ]

            aligned_results.append(
                result
            )

        return aligned_results