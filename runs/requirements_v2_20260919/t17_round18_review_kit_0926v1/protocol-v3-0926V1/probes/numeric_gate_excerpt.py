"""Isolated numeric subcheck transcribed from the reviewed GitHub source.

Source: services/api/app/writing_reference.py, commit
53feb06fc1402df820a6dba5d8b6e3fa15d50437, numeric-counter block inside
 evaluate_translation_fidelity (retrieved lines 3000-3305).
Only the enclosing signature, return value and imports are harness additions.
Numeric tokens are explicit fixture inputs: preprocessing, other fidelity gates,
model calls, admission and database writes are NOT exercised here.
"""
import re
from collections import Counter


def numeric_subcheck(source_text, translated_text, source_numbers,
                     translated_numbers, source_word_numbers=None):
    source_word_numbers = Counter(source_word_numbers or {})
    source_number_counts = Counter(source_numbers)
    translated_number_counts = Counter(translated_numbers)

    def _chinese_scaled_number_tokens(text: str) -> Counter:
        scaled: Counter = Counter()
        for match in re.finditer(r"(\d+(?:\.\d+)?)([万亿])", text):
            mantissa, unit = match.group(1), match.group(2)
            try:
                float(mantissa)
            except ValueError:
                continue
            digits = mantissa.replace(".", "")
            if digits:
                scaled[digits] += 1
            if mantissa != digits:
                scaled[mantissa] += 1
        return scaled

    scaled_source_tokens = _chinese_scaled_number_tokens(source_text)
    scaled_translated_tokens = _chinese_scaled_number_tokens(translated_text)
    source_number_counts += scaled_translated_tokens
    translated_number_counts += scaled_source_tokens + scaled_translated_tokens

    def unexpanded_frequency_numbers(text: str) -> list[str]:
        values: list[str] = []
        for match in re.finditer(
            r"(?<![A-Za-z0-9])q(\d+)[DWM](?![A-Za-z0-9])", text, re.I,
        ):
            number = match.group(1)
            nearby_prefix = text[max(0, match.start() - 24) : match.start()]
            if re.search(
                rf"(?:每\s*)?{re.escape(number)}\s*(?:天|日|周|月|days?|weeks?|months?)"
                r"[^，。；;]{0,8}[（(]?\s*$", nearby_prefix, re.I,
            ):
                continue
            values.append(number)
        return values

    source_number_counts.update(unexpanded_frequency_numbers(source_text))
    translated_number_counts.update(unexpanded_frequency_numbers(translated_text))
    missing_source_numbers = source_number_counts - translated_number_counts
    extra_translated_numbers = translated_number_counts - source_number_counts
    unlicensed_extra_numbers = extra_translated_numbers - source_word_numbers

    def _digit_key(token: str) -> str:
        return token.replace(".", "")

    def _is_magnitude_rewire(source_token: str, translated_token: str) -> bool:
        source_digits = _digit_key(source_token)
        translated_digits = _digit_key(translated_token)
        if not source_digits or not translated_digits:
            return False
        if translated_digits.startswith(source_digits):
            return set(translated_digits[len(source_digits):]) <= {"0"}
        return translated_digits == source_digits

    translated_digit_keys = Counter(
        _digit_key(token)
        for token in translated_number_counts
        for _ in range(translated_number_counts[token])
    )
    forgiven_missing = set()
    for token, count in missing_source_numbers.items():
        if translated_digit_keys.get(_digit_key(token), 0) >= count:
            forgiven_missing.add(token)
            continue
        if any(
            _is_magnitude_rewire(token, other)
            for other in translated_number_counts
        ):
            forgiven_missing.add(token)
    source_digit_keys = Counter(
        _digit_key(token)
        for token in source_number_counts
        for _ in range(source_number_counts[token])
    )
    forgiven_extra = set()
    for token, count in unlicensed_extra_numbers.items():
        if source_digit_keys.get(_digit_key(token), 0) >= count:
            forgiven_extra.add(token)
            continue
        if any(
            _is_magnitude_rewire(source_token, token)
            for source_token in source_number_counts
        ):
            forgiven_extra.add(token)
    missing_source_numbers = Counter(
        {token: count for token, count in missing_source_numbers.items() if token not in forgiven_missing}
    )
    unlicensed_extra_numbers = Counter(
        {token: count for token, count in unlicensed_extra_numbers.items() if token not in forgiven_extra}
    )
    # Harness return, equivalent to the source's numeric_tokens_changed branch.
    return bool(missing_source_numbers or unlicensed_extra_numbers)
