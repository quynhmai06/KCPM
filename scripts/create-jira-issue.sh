#!/usr/bin/env bash
set -uo pipefail

fail() {
  local title="$1"
  local message="$2"
  echo "::error title=${title}::${message}"
  exit 1
}

missing=0
for var_name in JIRA_BASE_URL JIRA_EMAIL JIRA_API_TOKEN JIRA_PROJECT_KEY; do
  if [ -z "${!var_name:-}" ]; then
    echo "::error title=Missing Jira secret::${var_name} is not configured."
    missing=1
  fi
done

if [ "$missing" -eq 1 ]; then
  exit 1
fi

jira_base_url="${JIRA_BASE_URL%/}"
jira_project_key="$(printf '%s' "$JIRA_PROJECT_KEY" | xargs | tr '[:lower:]' '[:upper:]')"
jira_issue_type="${JIRA_ISSUE_TYPE:-Bug}"

# Accept an issue key accidentally entered as the project key, e.g. KTPM-1.
if [[ "$jira_project_key" =~ ^([A-Z][A-Z0-9_]*)-[0-9]+$ ]]; then
  echo "::notice::JIRA_PROJECT_KEY contains an issue number; using project key ${BASH_REMATCH[1]}."
  jira_project_key="${BASH_REMATCH[1]}"
fi

if [[ ! "$jira_project_key" =~ ^[A-Z][A-Z0-9_]*$ ]]; then
  fail "Invalid Jira project key" "JIRA_PROJECT_KEY must be a project key such as KTPM, not a project name or URL."
fi

auth_response_file="$(mktemp)"
project_response_file="$(mktemp)"
permission_response_file="$(mktemp)"
project_search_response_file="$(mktemp)"
payload_file="$(mktemp)"
response_file="$(mktemp)"
sprint_payload_file="$(mktemp)"
sprint_response_file="$(mktemp)"

cleanup() {
  rm -f \
    "$auth_response_file" \
    "$project_response_file" \
    "$permission_response_file" \
    "$project_search_response_file" \
    "$payload_file" \
    "$response_file" \
    "$sprint_payload_file" \
    "$sprint_response_file"
}
trap cleanup EXIT

if ! auth_http_code="$(
  curl -sS \
    -o "$auth_response_file" \
    -w "%{http_code}" \
    -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
    -H "Accept: application/json" \
    "$jira_base_url/rest/api/3/myself"
)"; then
  fail "Jira connection failed" "Cannot connect to JIRA_BASE_URL. Check the URL and network access."
fi

if [ "$auth_http_code" -lt 200 ] || [ "$auth_http_code" -ge 300 ]; then
  cat "$auth_response_file"
  fail "Jira authentication failed" "Jira returned HTTP ${auth_http_code}. Check JIRA_EMAIL and JIRA_API_TOKEN."
fi

echo "Jira authentication succeeded."

if ! project_http_code="$(
  curl -sS \
    -o "$project_response_file" \
    -w "%{http_code}" \
    -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
    -H "Accept: application/json" \
    "$jira_base_url/rest/api/3/project/$jira_project_key"
)"; then
  fail "Jira project lookup failed" "Could not query project ${jira_project_key}."
fi

if [ "$project_http_code" -lt 200 ] || [ "$project_http_code" -ge 300 ]; then
  cat "$project_response_file"

  if project_search_http_code="$(
    curl -sS \
      -o "$project_search_response_file" \
      -w "%{http_code}" \
      -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
      -H "Accept: application/json" \
      "$jira_base_url/rest/api/3/project/search?maxResults=100"
  )" && [ "$project_search_http_code" -ge 200 ] && [ "$project_search_http_code" -lt 300 ]; then
    accessible_keys="$(python3 - "$project_search_response_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)

print(", ".join(project.get("key", "") for project in data.get("values", []) if project.get("key")))
PY
)"
    if [ -n "$accessible_keys" ]; then
      echo "::notice::Projects visible to JIRA_EMAIL: ${accessible_keys}"
    fi
  fi

  fail "Jira project is not accessible" "Project ${jira_project_key} does not exist on this Jira site, or JIRA_EMAIL lacks Browse Projects permission."
fi

project_id="$(python3 - "$project_response_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f).get("id", ""))
PY
)"

if [ -z "$project_id" ]; then
  fail "Invalid Jira project response" "Project ${jira_project_key} was found, but Jira did not return its ID."
fi

if ! permission_http_code="$(
  curl -sS \
    -o "$permission_response_file" \
    -w "%{http_code}" \
    -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
    -H "Accept: application/json" \
    "$jira_base_url/rest/api/3/mypermissions?projectKey=$jira_project_key&permissions=BROWSE_PROJECTS,CREATE_ISSUES"
)"; then
  fail "Jira permission check failed" "Could not check permissions for project ${jira_project_key}."
fi

if [ "$permission_http_code" -lt 200 ] || [ "$permission_http_code" -ge 300 ]; then
  cat "$permission_response_file"
  fail "Jira permission check failed" "Jira returned HTTP ${permission_http_code} while checking project permissions."
fi

missing_permissions="$(python3 - "$permission_response_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    permissions = json.load(f).get("permissions", {})

required = ("BROWSE_PROJECTS", "CREATE_ISSUES")
print(", ".join(name for name in required if not permissions.get(name, {}).get("havePermission", False)))
PY
)"

if [ -n "$missing_permissions" ]; then
  fail "Missing Jira project permission" "JIRA_EMAIL lacks ${missing_permissions} in project ${jira_project_key}. Add the account to a project role that has these permissions."
fi

echo "Project ${jira_project_key} and required permissions verified."

run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-unknown/repository}/actions/runs/${GITHUB_RUN_ID:-unknown}"
summary="API automation test failed"

python3 - "$summary" "$run_url" "$project_id" "$jira_issue_type" > "$payload_file" <<'PY'
import json
import os
import sys

summary = sys.argv[1]
run_url = sys.argv[2]
project_id = sys.argv[3]
issue_type = sys.argv[4]

description = (
    "Postman/Newman API test failed in GitHub Actions. "
    f"Repository: {os.getenv('GITHUB_REPOSITORY', 'unknown')}. "
    f"Workflow: {os.getenv('GITHUB_WORKFLOW', 'unknown')}. "
    f"Run: {run_url}. "
    "Please check the uploaded api-test-report artifact."
)

payload = {
    "fields": {
        "project": {"id": project_id},
        "summary": summary,
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ],
        },
        "issuetype": {"name": issue_type},
    }
}

json.dump(payload, sys.stdout)
PY

if ! http_code="$(
  curl -sS \
    -o "$response_file" \
    -w "%{http_code}" \
    -X POST "$jira_base_url/rest/api/3/issue" \
    -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    --data @"$payload_file"
)"; then
  fail "Jira issue creation failed" "The request to create a Jira issue could not be completed."
fi

if [ "$http_code" -lt 200 ] || [ "$http_code" -ge 300 ]; then
  cat "$response_file"
  fail "Jira issue creation failed" "Jira returned HTTP ${http_code}. Check that issue type ${jira_issue_type} exists and that all required fields have defaults."
fi

issue_key="$(python3 - "$response_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f).get("key", ""))
PY
)"

if [ -z "$issue_key" ]; then
  fail "Invalid Jira create response" "The issue may have been created, but Jira did not return its key."
fi

echo "Jira issue ${issue_key} created successfully."

if [ -z "${JIRA_SPRINT_ID:-}" ]; then
  echo "::notice::JIRA_SPRINT_ID is not configured; issue ${issue_key} was created without a sprint."
  exit 0
fi

python3 - "$issue_key" > "$sprint_payload_file" <<'PY'
import json
import sys

json.dump({"issues": [sys.argv[1]]}, sys.stdout)
PY

if ! sprint_http_code="$(
  curl -sS \
    -o "$sprint_response_file" \
    -w "%{http_code}" \
    -X POST "$jira_base_url/rest/agile/1.0/sprint/${JIRA_SPRINT_ID}/issue" \
    -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    --data @"$sprint_payload_file"
)"; then
  echo "::warning::Issue ${issue_key} was created, but the sprint request could not be completed."
  exit 0
fi

if [ "$sprint_http_code" -lt 200 ] || [ "$sprint_http_code" -ge 300 ]; then
  echo "::warning::Issue ${issue_key} was created, but adding it to sprint ${JIRA_SPRINT_ID} failed with HTTP ${sprint_http_code}."
  cat "$sprint_response_file"
  exit 0
fi

echo "Jira issue ${issue_key} added to sprint ${JIRA_SPRINT_ID} successfully."
