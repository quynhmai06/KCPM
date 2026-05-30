#!/usr/bin/env bash
set -u

missing=0
for var_name in JIRA_BASE_URL JIRA_EMAIL JIRA_API_TOKEN JIRA_PROJECT_KEY; do
  if [ -z "${!var_name:-}" ]; then
    echo "::warning::Missing ${var_name}; skip Jira issue creation."
    missing=1
  fi
done

if [ "$missing" -eq 1 ]; then
  exit 0
fi

run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-unknown/repository}/actions/runs/${GITHUB_RUN_ID:-unknown}"
summary="API automation test failed"
payload_file="$(mktemp)"
response_file="$(mktemp)"

python3 - "$summary" "$run_url" > "$payload_file" <<'PY'
import json
import os
import sys

summary = sys.argv[1]
run_url = sys.argv[2]

description = (
    "Postman/Newman API test failed in GitHub Actions. "
    f"Repository: {os.getenv('GITHUB_REPOSITORY', 'unknown')}. "
    f"Workflow: {os.getenv('GITHUB_WORKFLOW', 'unknown')}. "
    f"Run: {run_url}. "
    "Please check the uploaded api-test-report artifact."
)

payload = {
    "fields": {
        "project": {
            "key": os.environ["JIRA_PROJECT_KEY"]
        },
        "summary": summary,
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": description
                        }
                    ]
                }
            ]
        },
        "issuetype": {
            "name": "Bug"
        }
    }
}

json.dump(payload, sys.stdout)
PY

http_code="$(
  curl -sS \
    -o "$response_file" \
    -w "%{http_code}" \
    -X POST "${JIRA_BASE_URL%/}/rest/api/3/issue" \
    -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data @"$payload_file"
)"

if [ "$http_code" -lt 200 ] || [ "$http_code" -ge 300 ]; then
  echo "::warning::Jira issue creation failed with HTTP status ${http_code}."
  cat "$response_file"
  exit 0
fi

echo "Jira issue created successfully."
cat "$response_file"
