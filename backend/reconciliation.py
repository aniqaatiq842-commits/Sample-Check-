
import csv
import re
from io import StringIO


COMPARE_FIELDS = [
    "patient_code",
    "sample_type",
    "collection_date",
]

FIELD_ALIASES = {
    "sample_id": {
        "sample_id", "sample id", "sampleid",
        "specimen_id", "specimen id",
    },
    "patient_code": {
        "patient_code", "patient code", "patient_id",
        "patient id", "customer_patient_code",
    },
    "sample_type": {
        "sample_type", "sample type", "specimen_type",
        "specimen type",
    },
    "collection_date": {
        "collection_date", "collection date",
        "collectiondate", "date_collected",
    },
}


def normalize_header(value):
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def read_sample_csv(content, file_label):
    reader = csv.DictReader(StringIO(content))

    if not reader.fieldnames:
        raise ValueError(f"{file_label} CSV is empty or has no header.")

    header_map = {}

    for original in reader.fieldnames:
        if not original:
            continue

        normalized = normalize_header(original)

        for standard, aliases in FIELD_ALIASES.items():
            normalized_aliases = {
                normalize_header(alias) for alias in aliases
            }

            if normalized == normalize_header(standard) or normalized in normalized_aliases:
                header_map[standard] = original
                break

    if "sample_id" not in header_map:
        raise ValueError(
            f"{file_label} must contain a sample_id column."
        )

    records = []

    for row_number, row in enumerate(reader, start=2):
        record = {
            field: (row.get(original) or "").strip()
            for field, original in header_map.items()
        }

        if not any(record.values()):
            continue

        record["sample_id"] = record.get("sample_id", "").strip()
        record["_row"] = row_number

        if not record["sample_id"]:
            records.append(record)
        else:
            records.append(record)

    if not records:
        raise ValueError(f"{file_label} contains no sample records.")

    return records


def index_records(records):
    indexed = {}

    for record in records:
        sample_id = record.get("sample_id", "")

        if sample_id:
            indexed.setdefault(sample_id, []).append(record)

    return indexed


def evidence(file_name, record, field=None):
    item = {
        "file": file_name,
        "row": record["_row"],
    }

    if field:
        item["field"] = field
        item["value"] = record.get(field, "")

    return item


def reconcile_csv_files(order_content, manifest_content):
    """
    Compare customer orders against the laboratory manifest.

    This function only detects administrative data inconsistencies.
    It does not approve, reject, or modify samples.
    """

    orders = read_sample_csv(order_content, "Customer order")
    manifest = read_sample_csv(manifest_content, "Lab manifest")

    order_index = index_records(orders)
    manifest_index = index_records(manifest)

    findings = []

    # Records without sample IDs
    for record in orders:
        if not record.get("sample_id"):
            findings.append({
                "sample_id": f"ORDER-ROW-{record['_row']}",
                "issue_type": "Missing sample ID in customer order",
                "severity": "High",
                "description": "Customer order contains a record without a sample ID.",
                "evidence": [
                    evidence("Customer Order", record)
                ],
            })

    for record in manifest:
        if not record.get("sample_id"):
            findings.append({
                "sample_id": f"MANIFEST-ROW-{record['_row']}",
                "issue_type": "Missing sample ID in lab manifest",
                "severity": "High",
                "description": "Lab manifest contains a record without a sample ID.",
                "evidence": [
                    evidence("Lab Manifest", record)
                ],
            })

    # Duplicate sample IDs
    for file_name, indexed in [
        ("Customer Order", order_index),
        ("Lab Manifest", manifest_index),
    ]:
        for sample_id, records in indexed.items():
            if len(records) > 1:
                findings.append({
                    "sample_id": sample_id,
                    "issue_type": "Duplicate sample ID",
                    "severity": "High",
                    "description": (
                        f"Sample ID {sample_id} appears "
                        f"{len(records)} times in {file_name}."
                    ),
                    "evidence": [
                        evidence(file_name, record)
                        for record in records
                    ],
                })

    order_ids = set(order_index)
    manifest_ids = set(manifest_index)

    # Customer ordered a sample that is absent from the manifest
    for sample_id in sorted(order_ids - manifest_ids):
        record = order_index[sample_id][0]

        findings.append({
            "sample_id": sample_id,
            "issue_type": "Missing from lab manifest",
            "severity": "High",
            "description": (
                f"Sample {sample_id} appears in the customer order "
                "but not in the lab manifest."
            ),
            "evidence": [
                evidence("Customer Order", record)
            ],
        })

    # Manifest contains a sample not listed in the customer order
    for sample_id in sorted(manifest_ids - order_ids):
        record = manifest_index[sample_id][0]

        findings.append({
            "sample_id": sample_id,
            "issue_type": "Unexpected sample in lab manifest",
            "severity": "High",
            "description": (
                f"Sample {sample_id} appears in the lab manifest "
                "but not in the customer order."
            ),
            "evidence": [
                evidence("Lab Manifest", record)
            ],
        })

    # Compare information for IDs present in both files
    matched_ids = order_ids & manifest_ids

    for sample_id in sorted(matched_ids):
        order_record = order_index[sample_id][0]
        manifest_record = manifest_index[sample_id][0]

        for field in COMPARE_FIELDS:
            order_value = order_record.get(field, "").strip()
            manifest_value = manifest_record.get(field, "").strip()

            # Do not report a conflict if either side is blank.
            if not order_value or not manifest_value:
                continue

            if order_value.casefold() != manifest_value.casefold():
                findings.append({
                    "sample_id": sample_id,
                    "issue_type": f"Conflicting {field}",
                    "severity": (
                        "High" if field == "patient_code" else "Medium"
                    ),
                    "description": (
                        f"{field} differs between the customer order "
                        f"('{order_value}') and lab manifest "
                        f"('{manifest_value}')."
                    ),
                    "evidence": [
                        evidence("Customer Order", order_record, field),
                        evidence("Lab Manifest", manifest_record, field),
                    ],
                })

    clean_matches = sum(
        1 for sample_id in matched_ids
        if not any(
            item["sample_id"] == sample_id
            for item in findings
        )
    )

    return {
        "customer_order_count": len(orders),
        "lab_manifest_count": len(manifest),
        "matched_sample_count": len(matched_ids),
        "clean_matched_count": clean_matches,
        "exception_count": len(findings),
        "findings": findings,
    }
