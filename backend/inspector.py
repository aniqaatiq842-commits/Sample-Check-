import csv
import re
from io import StringIO


REQUIRED_FIELDS = [
    "sample_id",
    "patient_code",
    "sample_type",
    "collection_date",
]

FIELD_ALIASES = {
    "sample_id": {
        "sample_id",
        "sample id",
        "sampleid",
        "specimen_id",
        "specimen id",
    },
    "patient_code": {
        "patient_code",
        "patient code",
        "patient_id",
        "patient id",
        "customer_patient_code",
    },
    "sample_type": {
        "sample_type",
        "sample type",
        "specimen_type",
        "specimen type",
    },
    "collection_date": {
        "collection_date",
        "collection date",
        "collectiondate",
        "date_collected",
    },
}

ALLOWED_SAMPLE_TYPES = {
    "blood",
    "serum",
    "plasma",
    "saliva",
    "tissue",
    "urine",
}


def normalize_header(value):
    """Normalize CSV column names for flexible matching."""

    return re.sub(
        r"[^a-z0-9]+",
        "_",
        value.strip().lower(),
    ).strip("_")


def inspect_csv(content: str):
    """Inspect a CSV file for administrative data-quality issues."""

    reader = csv.DictReader(StringIO(content))

    if not reader.fieldnames:
        raise ValueError("CSV file is empty or has no header.")

    header_map = {}

    for original in reader.fieldnames:
        if not original:
            continue

        normalized = normalize_header(original)

        for standard, aliases in FIELD_ALIASES.items():
            normalized_aliases = {
                normalize_header(alias)
                for alias in aliases
            }

            if (
                normalized == normalize_header(standard)
                or normalized in normalized_aliases
            ):
                if standard in header_map:
                    raise ValueError(
                        f"CSV contains multiple columns matching '{standard}'."
                    )

                header_map[standard] = original
                break

    missing_headers = [
        field
        for field in REQUIRED_FIELDS
        if field not in header_map
    ]

    if missing_headers:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(missing_headers)
        )

    samples = []
    findings = []
    seen_ids = set()
    row_count = 0

    for line_number, row in enumerate(reader, start=2):
        if not any(
            str(value or "").strip()
            for value in row.values()
        ):
            continue

        row_count += 1

        sample = {
            field: (row.get(header_map[field]) or "").strip()
            for field in REQUIRED_FIELDS
        }

        original_sample_id = sample["sample_id"]
        normalized_sample_id = original_sample_id.casefold()

        # Preserve the actual sample ID separately from the
        # internal row reference used to associate findings.
        sample["_row"] = line_number
        sample["_record_id"] = (
            original_sample_id
            if original_sample_id
            else f"ROW-{line_number}"
        )

        if not original_sample_id:
            findings.append({
                "sample_id": sample["_record_id"],
                "issue_type": "Missing sample ID",
                "description": (
                    f"Row {line_number} has no sample ID."
                ),
                "severity": "High",
                "row": line_number,
            })

        elif normalized_sample_id in seen_ids:
            findings.append({
                "sample_id": sample["_record_id"],
                "issue_type": "Duplicate sample ID",
                "description": (
                    f"Sample ID {original_sample_id} appears more than once."
                ),
                "severity": "High",
                "row": line_number,
            })

        seen_ids.add(normalized_sample_id)

        for field in REQUIRED_FIELDS[1:]:
            if not sample[field]:
                findings.append({
                    "sample_id": sample["_record_id"],
                    "issue_type": f"Missing {field}",
                    "description": (
                        f"{field} is missing for sample "
                        f"{sample['_record_id']}."
                    ),
                    "severity": "Medium",
                    "row": line_number,
                })

        if (
            sample["sample_type"]
            and sample["sample_type"].casefold()
            not in ALLOWED_SAMPLE_TYPES
        ):
            findings.append({
                "sample_id": sample["_record_id"],
                "issue_type": "Unrecognized sample type",
                "description": (
                    f"Sample type '{sample['sample_type']}' "
                    "is not in the configured example list."
                ),
                "severity": "Medium",
                "row": line_number,
            })

        samples.append(sample)

    if row_count == 0:
        raise ValueError(
            "CSV contains headers but no sample records."
        )

    return samples, findings
