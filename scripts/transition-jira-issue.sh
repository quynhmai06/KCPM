#!/usr/bin/env bash
set -u

missing=0
for var_name in JIRA_BASE_URL JIRA_EMAIL JIRA_API_TOKEN JIRA_PROJECT_KEY; do
  if [ -z "${!var_name:-}" ]; then
    echo "::warning::Missing ${var_name}; skip Jira transition."
    missing=1
  fi
done

if [ "$missing" -eq 1 ]; then
  exit 0
fi

commit_message="$(git log -1 --pretty=%B 2>/dev/null || true)"
issue_text="${JIRA_ISSUE_KEY:-} ${JIRA_ISSUE_TEXT:-} ${commit_message} ${GITHUB_HEAD_REF:-} ${GITHUB_REF_NAME:-}"
transition_path="${JIRA_TRANSITION_PATH:-In Progress,Testing,Done}"

python3 - "$issue_text" "$transition_path" <<'PY'
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

issue_text = sys.argv[1]
transition_path = [x.strip() for x in sys.argv[2].split(",") if x.strip()]

base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
email = os.environ["JIRA_EMAIL"]
api_token = os.environ["JIRA_API_TOKEN"]
project_key = os.environ["JIRA_PROJECT_KEY"]

match = re.search(rf"\b{re.escape(project_key)}-\d+\b", issue_text, re.IGNORECASE)
if not match:
    print(f"::warning::No Jira issue key like {project_key}-1 was found in commit message or branch name; skip transition.")
    sys.exit(0)

issue_key = match.group(0).upper()
auth = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")

def request(method, path, payload=None):
    data = None
    headers = {
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {"raw": raw}
        return exc.code, body

def norm(value):
    return re.sub(r"\s+", " ", str(value).strip()).lower()

def get_issue_status():
    status, body = request("GET", f"/rest/api/3/issue/{issue_key}?fields=status")
    if status < 200 or status >= 300:
        print(f"::warning::Cannot read Jira issue {issue_key}; HTTP {status}: {json.dumps(body)}")
        sys.exit(0)
    return body["fields"]["status"]["name"]

def get_transitions():
    status, body = request("GET", f"/rest/api/3/issue/{issue_key}/transitions")
    if status < 200 or status >= 300:
        print(f"::warning::Cannot read Jira transitions for {issue_key}; HTTP {status}: {json.dumps(body)}")
        sys.exit(0)
    return body.get("transitions", [])

transitioned = False

for target in transition_path:
    current_status = get_issue_status()
    if norm(current_status) == norm(target):
        print(f"Jira issue {issue_key} is already in status {current_status}.")
        continue

    transitions = get_transitions()
    selected = None
    for transition in transitions:
        transition_name = transition.get("name", "")
        target_status = (transition.get("to") or {}).get("name", "")
        if norm(target_status) == norm(target) or norm(transition_name) == norm(target):
            selected = transition
            break

    if selected is None:
        available = [
            f"{t.get('id')}:{t.get('name')}->{(t.get('to') or {}).get('name')}"
            for t in transitions
        ]
        print(f"No direct Jira transition from {current_status} to {target}. Available: {available}")
        continue

    comment = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": f"GitHub Actions passed API automation tests and moved this issue to {target}.",
                    }
                ],
            }
        ],
    }
    payload = {
        "transition": {"id": selected["id"]},
        "update": {"comment": [{"add": {"body": comment}}]},
    }
    status, body = request("POST", f"/rest/api/3/issue/{issue_key}/transitions", payload)
    if status < 200 or status >= 300:
        print(f"::warning::Cannot transition Jira issue {issue_key} to {target}; HTTP {status}: {json.dumps(body)}")
        sys.exit(0)

    print(f"Jira issue {issue_key} transitioned from {current_status} to {target}.")
    transitioned = True

final_status = get_issue_status()
print(f"Jira issue {issue_key} final status: {final_status}.")

if not transitioned and norm(final_status) != norm(transition_path[-1]):
    print(f"::warning::Jira issue {issue_key} was not moved to {transition_path[-1]}. Check Jira workflow transitions.")
PY
