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
payload_dir="$(mktemp -d)"
response_file="$(mktemp)"
sprint_payload_file="$(mktemp)"
sprint_response_file="$(mktemp)"

cleanup() {
  rm -f \
    "$auth_response_file" \
    "$project_response_file" \
    "$permission_response_file" \
    "$project_search_response_file" \
    "$response_file" \
    "$sprint_payload_file" \
    "$sprint_response_file"
  rm -rf "$payload_dir"
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
shopt -s nullglob
newman_reports=(reports/*-newman-result.json)
newman_report_args=()

if [ "${#newman_reports[@]}" -eq 0 ]; then
  # Keep one missing path so the payload builder can explain that tests failed
  # before Newman produced a report.
  newman_report_args+=(--newman-report reports/newman-result.json)
else
  for newman_report in "${newman_reports[@]}"; do
    newman_report_args+=(--newman-report "$newman_report")
  done
fi

python3 scripts/build-jira-issues.py \
  "${newman_report_args[@]}" \
  --output-dir "$payload_dir" \
  --project-id "$project_id" \
  --issue-type "$jira_issue_type" \
  --run-url "$run_url" \
  --repository "${GITHUB_REPOSITORY:-unknown}" \
  --workflow "${GITHUB_WORKFLOW:-unknown}"

payload_files=("$payload_dir"/issue-*.json)
if [ "${#payload_files[@]}" -eq 0 ]; then
  fail "Jira payload generation failed" "No Jira issue payload was generated from the Newman report."
fi

echo "Creating ${#payload_files[@]} Jira issue(s) from failed test cases."
issue_keys=()

for issue_payload_file in "${payload_files[@]}"; do
  issue_summary="$(python3 - "$issue_payload_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f).get("fields", {}).get("summary", "API automation test failed"))
PY
)"
  echo "Creating Jira issue: ${issue_summary}"

  if ! http_code="$(
    curl -sS \
      -o "$response_file" \
      -w "%{http_code}" \
      -X POST "$jira_base_url/rest/api/3/issue" \
      -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
      -H "Accept: application/json" \
      -H "Content-Type: application/json" \
      --data @"$issue_payload_file"
  )"; then
    fail "Jira issue creation failed" "The request to create a Jira issue could not be completed."
  fi

  if [ "$http_code" -lt 200 ] || [ "$http_code" -ge 300 ]; then
    cat "$response_file"
    fail "Jira issue creation failed" "Jira returned HTTP ${http_code} for ${issue_summary}."
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

  issue_keys+=("$issue_key")
  echo "Jira issue ${issue_key} created successfully for ${issue_summary}."
done

if [ -z "${JIRA_SPRINT_ID:-}" ]; then
  echo "::notice::JIRA_SPRINT_ID is not configured; created issues were not added to a sprint."
  exit 0
fi

python3 - "${issue_keys[@]}" > "$sprint_payload_file" <<'PY'
import json
import sys

json.dump({"issues": sys.argv[1:]}, sys.stdout)
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
  echo "::warning::Jira issues were created, but the sprint request could not be completed."
  exit 0
fi

if [ "$sprint_http_code" -lt 200 ] || [ "$sprint_http_code" -ge 300 ]; then
  echo "::warning::Jira issues were created, but adding them to sprint ${JIRA_SPRINT_ID} failed with HTTP ${sprint_http_code}."
  cat "$sprint_response_file"
  exit 0
fi

echo "Jira issues added to sprint ${JIRA_SPRINT_ID} successfully."
