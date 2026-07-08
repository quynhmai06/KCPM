#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Any


REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "access_token",
    "authorization",
    "jwt",
    "password",
    "refresh_token",
    "token",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one Jira issue payload for each failed Newman request."
    )
    parser.add_argument(
        "--newman-report",
        type=Path,
        action="append",
        required=True,
        help="Newman JSON report. Pass this option more than once for multiple collections.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--issue-type", default="Bug")
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--repository", default="unknown")
    parser.add_argument("--workflow", default="unknown")
    return parser.parse_args()


def stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return (
        normalized in SENSITIVE_KEYS
        or "password" in normalized
        or normalized.endswith("_token")
    )


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if is_sensitive_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def sanitize_body(body: str, limit: int = 5000) -> str:
    if not body:
        return "(empty)"
    try:
        parsed = json.loads(body)
        body = json.dumps(redact(parsed), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        body = re.sub(
            r'(?i)([a-z0-9_-]*(?:authorization|password|token)[a-z0-9_-]*)(["\s:=]+)([^\s,"}]+)',
            rf"\1\2{REDACTED}",
            body,
        )
    body = body.replace("\x00", "")
    if len(body) > limit:
        return body[:limit] + "\n... [truncated]"
    return body


def stream_to_text(stream: Any) -> str:
    if isinstance(stream, str):
        return stream
    if isinstance(stream, list):
        try:
            return bytes(stream).decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            return stringify(stream)
    if isinstance(stream, dict) and isinstance(stream.get("data"), list):
        try:
            return bytes(stream["data"]).decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            return stringify(stream["data"])
    return ""


def request_url(execution: dict[str, Any]) -> str:
    request = execution.get("request") or execution.get("item", {}).get("request", {})
    url = request.get("url", "")
    if isinstance(url, dict):
        return str(url.get("raw") or "")
    return str(url)


def request_method(execution: dict[str, Any]) -> str:
    request = execution.get("request") or execution.get("item", {}).get("request", {})
    return str(request.get("method") or "UNKNOWN")


def request_body(execution: dict[str, Any]) -> str:
    request = execution.get("request") or execution.get("item", {}).get("request", {})
    body = request.get("body") or {}
    if isinstance(body, dict):
        return sanitize_body(str(body.get("raw") or ""), limit=3000)
    return sanitize_body(stringify(body), limit=3000)


def failed_assertions(execution: dict[str, Any]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for assertion in execution.get("assertions") or []:
        error = assertion.get("error")
        if not error:
            continue
        failure = {
            "name": str(assertion.get("assertion") or "Unnamed assertion"),
            "message": str(error.get("message") or error.get("name") or "Assertion failed"),
        }
        if "expected" in error:
            failure["expected"] = stringify(error["expected"])
        if "actual" in error:
            failure["actual"] = stringify(error["actual"])
        failures.append(failure)

    request_error = execution.get("requestError")
    if request_error:
        if isinstance(request_error, dict):
            message = request_error.get("message") or stringify(request_error)
        else:
            message = stringify(request_error)
        failures.append({"name": "Request error", "message": str(message)})
    return failures


def text_node(text: str, bold: bool = False) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if bold:
        node["marks"] = [{"type": "strong"}]
    return node


def field_paragraph(label: str, value: str) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "content": [text_node(f"{label}: ", bold=True), text_node(value or "(empty)")],
    }


def assertion_list(failures: list[dict[str, str]]) -> dict[str, Any]:
    items = []
    for failure in failures:
        content = [
            {
                "type": "paragraph",
                "content": [text_node(failure["name"], bold=True)],
            },
            field_paragraph("Message", failure["message"]),
        ]
        if "expected" in failure:
            content.append(field_paragraph("Expected", failure["expected"]))
        if "actual" in failure:
            content.append(field_paragraph("Actual", failure["actual"]))
        items.append({"type": "listItem", "content": content})
    return {"type": "bulletList", "content": items}


def response_details(execution: dict[str, Any]) -> tuple[str, str]:
    response = execution.get("response") or {}
    if not response:
        return "No response received", "(empty)"
    code = response.get("code", "unknown")
    status = response.get("status", "")
    response_time = response.get("responseTime")
    summary = f"{code} {status}".strip()
    if response_time is not None:
        summary += f" ({response_time} ms)"
    return summary, sanitize_body(stream_to_text(response.get("stream")))


def short_path(url: str) -> str:
    match = re.match(r"https?://[^/]+(/[^?]*)", url)
    return match.group(1) if match else url


def clean_assertion_name(test_case: str, name: str) -> str:
    return re.sub(rf"^{re.escape(test_case)}\s*-\s*", "", name, flags=re.IGNORECASE)


def build_payload(
    execution: dict[str, Any],
    failures: list[dict[str, str]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    test_case = str(execution.get("item", {}).get("name") or "Unknown test case")
    method = request_method(execution)
    url = request_url(execution)
    response_summary, response_body = response_details(execution)
    assertion_name = clean_assertion_name(test_case, failures[0]["name"])
    error_message = failures[0]["message"]
    summary = f"[{test_case}] {method} {short_path(url)} - {assertion_name}: {error_message}"
    summary = summary.replace("\n", " ")[:255]

    content: list[dict[str, Any]] = [
        {"type": "heading", "attrs": {"level": 2}, "content": [text_node("Automated API test failure")]},
        field_paragraph("Test case", test_case),
        field_paragraph("Request", f"{method} {url}"),
        field_paragraph("Actual response", response_summary),
        {"type": "heading", "attrs": {"level": 3}, "content": [text_node("Failed assertions")]},
        assertion_list(failures),
    ]

    body = request_body(execution)
    if body != "(empty)":
        content.extend(
            [
                {"type": "heading", "attrs": {"level": 3}, "content": [text_node("Test data")]},
                {"type": "codeBlock", "attrs": {"language": "json"}, "content": [text_node(body)]},
            ]
        )

    content.extend(
        [
            {"type": "heading", "attrs": {"level": 3}, "content": [text_node("Response body")]},
            {"type": "codeBlock", "content": [text_node(response_body)]},
            {"type": "rule"},
            field_paragraph("Repository", args.repository),
            field_paragraph("Workflow", args.workflow),
            {
                "type": "paragraph",
                "content": [
                    text_node("GitHub Actions run: ", bold=True),
                    {
                        "type": "text",
                        "text": args.run_url,
                        "marks": [{"type": "link", "attrs": {"href": args.run_url}}],
                    },
                ],
            },
            field_paragraph("Artifact", "api-test-report"),
        ]
    )

    return {
        "fields": {
            "project": {"id": args.project_id},
            "summary": summary,
            "description": {"type": "doc", "version": 1, "content": content},
            "issuetype": {"name": args.issue_type},
        }
    }


def fallback_payload(args: argparse.Namespace, reason: str) -> dict[str, Any]:
    return {
        "fields": {
            "project": {"id": args.project_id},
            "summary": "[CI] API automation failed before test details were available",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    field_paragraph("Reason", reason),
                    field_paragraph("Repository", args.repository),
                    field_paragraph("Workflow", args.workflow),
                    field_paragraph("GitHub Actions run", args.run_url),
                    field_paragraph("Artifact", "api-test-report"),
                ],
            },
            "issuetype": {"name": args.issue_type},
        }
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payloads: list[dict[str, Any]] = []
    seen_summaries: set[str] = set()

    for newman_report in args.newman_report:
        if not newman_report.is_file():
            payload = fallback_payload(
                args,
                f"The Newman JSON report was not generated: {newman_report.name}.",
            )
            summary = payload["fields"]["summary"]
            if summary not in seen_summaries:
                seen_summaries.add(summary)
                payloads.append(payload)
            continue

        try:
            report = json.loads(newman_report.read_text(encoding="utf-8"))
            for execution in report.get("run", {}).get("executions", []):
                failures = failed_assertions(execution)
                if failures:
                    payload = build_payload(execution, failures, args)
                    summary = payload["fields"]["summary"]

                    if summary in seen_summaries:
                        continue

                    seen_summaries.add(summary)
                    payloads.append(payload)

        except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
            payload = fallback_payload(
                args,
                f"Could not parse {newman_report.name}: {error}",
            )
            summary = payload["fields"]["summary"]
            if summary not in seen_summaries:
                seen_summaries.add(summary)
                payloads.append(payload)

    if not payloads:
        payloads.append(
            fallback_payload(
                args,
                "The workflow failed, but the Newman report contained no failed assertion or request error.",
            )
        )

    for index, payload in enumerate(payloads, start=1):
        output_file = args.output_dir / f"issue-{index:03d}.json"
        output_file.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    print(f"Generated {len(payloads)} Jira issue payload(s).")


if __name__ == "__main__":
    main()
