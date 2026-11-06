
import json
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("VULTR_INFERENCE_API_KEY")
BASE_URL = os.getenv(
    "VULTR_INFERENCE_BASE_URL",
    "https://api.vultrinference.com/v1",
).rstrip("/")
MODEL = os.getenv(
    "VULTR_INFERENCE_MODEL",
    "deepseek-v4.1-flash-1017",
)

TIMEOUT = 60.0


SYSTEM_PROMPT = """
You are Sample Check, an AI assistant for laboratory sample intake.

Analyze administrative data-quality exceptions from customer orders
and laboratory manifests.

Rules:
- Use only the supplied information and evidence.
- Never invent facts or patient information.
- Pay attention to source files, row numbers, and conflicting values.
- Explain what each exception means in simple language.
- Recommend practical administrative next steps.
- Do not diagnose patients or make clinical decisions.
- Do not approve, reject, or resolve samples.
- Do not claim that a sample is clinically unsafe.
- Keep every explanation concise.
- If evidence is incomplete, clearly state that.
- Return ONLY a valid JSON object.

Required JSON structure:
{
  "summary": "Short overview of the findings",
  "priority_actions": [
    {
      "sample_id": "Sample ID",
      "issue": "Issue type",
      "explanation": "Explanation based on supplied evidence",
      "recommended_action": "Practical next step",
      "priority": "High"
    }
  ],
  "customer_message": "Polite clarification draft",
  "limitations": "What cannot be concluded"
}

Use High, Medium, or Low for priority.
Keep the entire response concise.
"""


def clean_json_response(content):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The AI returned an empty response.")

    content = content.strip()

    content = re.sub(
        r"^```(?:json)?\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)

    start = content.find("{")
    end = content.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("The AI response did not contain complete JSON.")

    return content[start:end + 1]


def validate_analysis(analysis):
    if not isinstance(analysis, dict):
        raise ValueError("AI response is not a JSON object.")

    required_keys = {
        "summary",
        "priority_actions",
        "customer_message",
        "limitations",
    }

    if not required_keys.issubset(analysis):
        raise ValueError("AI response is missing required fields.")

    if not isinstance(analysis["summary"], str):
        raise ValueError("AI summary has an invalid format.")

    if not isinstance(analysis["priority_actions"], list):
        raise ValueError("AI priority actions have an invalid format.")

    if not isinstance(analysis["customer_message"], str):
        raise ValueError("AI customer message has an invalid format.")

    if not isinstance(analysis["limitations"], str):
        raise ValueError("AI limitations have an invalid format.")

    return analysis


def prepare_findings(findings, limit=15):
    """Prepare concise findings while preserving reconciliation evidence."""

    safe_findings = []

    for item in findings[:limit]:
        safe_item = {
            "sample_id": str(item.get("sample_id", ""))[:60],
            "issue_type": str(item.get("issue_type", ""))[:100],
            "description": str(item.get("description", ""))[:250],
            "severity": str(item.get("severity", "Medium"))[:20],
        }

        evidence = item.get("evidence", [])

        if isinstance(evidence, list):
            safe_evidence = []

            for entry in evidence[:5]:
                if not isinstance(entry, dict):
                    continue

                safe_evidence.append({
                    "file": str(entry.get("file", ""))[:100],
                    "row": str(entry.get("row", ""))[:20],
                    "field": str(entry.get("field", ""))[:80],
                    "value": str(entry.get("value", ""))[:120],
                })

            safe_item["evidence"] = safe_evidence

        safe_findings.append(safe_item)

    return safe_findings


def send_ai_request(safe_findings, retry=False):
    user_prompt = (
        "Investigate these actual reconciliation exceptions.\n"
        "Use the supplied evidence, including filenames and row numbers.\n"
        "Explain metadata conflicts using the supplied values.\n"
        "Return complete, valid JSON only.\n\n"
        + json.dumps(safe_findings, ensure_ascii=False)
    )

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": 0.1,
        "max_completion_tokens": 2200 if retry else 1800,
        "response_format": {
            "type": "json_object"
        },
    }

    response = httpx.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    result = response.json()
    choices = result.get("choices", [])

    if not choices:
        raise ValueError("Vultr returned no AI choices.")

    choice = choices[0]

    if choice.get("finish_reason") == "length":
        raise ValueError(
            "The AI response was truncated because its token limit was reached."
        )

    message = choice.get("message", {})
    content = message.get("content")

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Vultr returned an empty AI message.")

    cleaned_content = clean_json_response(content)
    analysis = json.loads(cleaned_content)

    return validate_analysis(analysis)


def analyze_findings(findings):
    """
    Analyze supplied findings using Vultr AI.

    Findings may come from cross-file reconciliation or SQLite.
    This function never modifies or resolves records.
    """

    if not API_KEY:
        raise RuntimeError(
            "Vultr API key is missing. Check your .env file."
        )

    if not findings:
        return {
            "summary": "No exceptions were provided for analysis.",
            "priority_actions": [],
            "customer_message": "",
            "limitations": "No findings were available to review.",
        }

    safe_findings = prepare_findings(findings)

    try:
        try:
            return send_ai_request(
                safe_findings,
                retry=False,
            )

        except (json.JSONDecodeError, ValueError) as first_error:
            print(
                "Vultr AI response could not be parsed. Retrying:",
                str(first_error),
            )

        smaller_findings = safe_findings[:8]

        try:
            return send_ai_request(
                smaller_findings,
                retry=True,
            )

        except (json.JSONDecodeError, ValueError) as second_error:
            raise RuntimeError(
                "Vultr AI returned incomplete or invalid JSON "
                "even after retrying. Please try again."
            ) from second_error

    except httpx.TimeoutException:
        raise RuntimeError(
            "Vultr AI request timed out. Please try again."
        )

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code

        if status == 401:
            raise RuntimeError(
                "Vultr rejected the API key. Check your .env configuration."
            )

        if status == 429:
            raise RuntimeError(
                "Vultr rate limit reached. Please try again shortly."
            )

        raise RuntimeError(
            f"Vultr AI returned an HTTP {status} error."
        )

    except httpx.RequestError:
        raise RuntimeError(
            "Could not connect to Vultr AI. Check your internet connection."
        )
