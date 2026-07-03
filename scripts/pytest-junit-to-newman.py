#!/usr/bin/env python3
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--service", default="auth-whitebox")
    return parser.parse_args()


def main():
    args = parse_args()
    junit_path = Path(args.junit)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    executions = []

    if junit_path.is_file():
        root = ET.parse(junit_path).getroot()

        for testcase in root.iter("testcase"):
            failure = testcase.find("failure")
            error = testcase.find("error")

            failed_node = failure if failure is not None else error
            if failed_node is None:
                continue

            classname = testcase.get("classname", "")
            name = testcase.get("name", "unknown_test")
            test_case = f"{classname}.{name}" if classname else name

            message = failed_node.get("message") or failed_node.text or "pytest failed"

            executions.append({
                "item": {
                    "name": test_case,
                    "request": {
                        "method": "PYTEST",
                        "url": {
                            "raw": f"auth-service/tests/test_auth_whitebox.py::{name}"
                        },
                        "body": {
                            "raw": json.dumps({
                                "service": args.service,
                                "test_case": test_case
                            }, ensure_ascii=False)
                        }
                    }
                },
                "request": {
                    "method": "PYTEST",
                    "url": {
                        "raw": f"auth-service/tests/test_auth_whitebox.py::{name}"
                    },
                    "body": {
                        "raw": json.dumps({
                            "service": args.service,
                            "test_case": test_case
                        }, ensure_ascii=False)
                    }
                },
                "response": {
                    "code": "FAILED",
                    "status": "Pytest failed",
                    "responseTime": 0,
                    "stream": message
                },
                "assertions": [
                    {
                        "assertion": "White-box test should pass",
                        "error": {
                            "message": message
                        }
                    }
                ]
            })

    if not executions:
        executions.append({
            "item": {
                "name": "Auth white-box test failed",
                "request": {
                    "method": "PYTEST",
                    "url": {
                        "raw": "auth-service/tests/test_auth_whitebox.py"
                    }
                }
            },
            "request": {
                "method": "PYTEST",
                "url": {
                    "raw": "auth-service/tests/test_auth_whitebox.py"
                }
            },
            "response": {
                "code": "FAILED",
                "status": "No pytest failure detail",
                "responseTime": 0,
                "stream": "Pytest failed before junit report was generated."
            },
            "assertions": [
                {
                    "assertion": "White-box test should pass",
                    "error": {
                        "message": "Pytest failed before junit report was generated."
                    }
                }
            ]
        })

    report = {
        "run": {
            "executions": executions
        }
    }

    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


if __name__ == "__main__":
    main()