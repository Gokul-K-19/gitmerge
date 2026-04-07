import json
import os
import requests

# ---------------------------
# Load result.json
# ---------------------------
with open("result.json", "r", encoding="utf-8") as f:
    result = json.load(f)

risk_label = result.get("risk_label", "UNKNOWN")
probability = result.get("probability", 0)
threshold = result.get("threshold", 0)
potential_files = result.get("potential_conflict_files", [])
actual_conflicts = result.get("actual_git_conflicts", [])

# ---------------------------
# Build PR comment body
# ---------------------------
comment = f"""## 🤖 ML Merge Conflict Analysis

**Risk Label:** `{risk_label}`  
**Conflict Probability:** `{probability}`  
**Threshold:** `{threshold}`

"""

if potential_files:
    comment += "### 🔥 Potential Conflict Files\n\n"
    for item in potential_files[:10]:
        file_name = item.get("file", "unknown")
        overlap_ranges = item.get("overlap_ranges", [])
        overlap_lines = item.get("overlap_lines", 0)

        comment += f"- **{file_name}**\n"
        comment += f"  - Overlap Ranges: `{overlap_ranges}`\n"
        comment += f"  - Overlap Lines: `{overlap_lines}`\n"
else:
    comment += "### ✅ No overlapping files detected\n\n"

if actual_conflicts:
    comment += "\n### 🚨 Actual Git Conflict Files\n\n"
    for f in actual_conflicts:
        comment += f"- `{f}`\n"
else:
    comment += "\n### ✅ No actual Git merge conflicts detected\n"

comment += "\n---\nGenerated automatically by ML Merge Conflict Predictor."

# ---------------------------
# GitHub API details
# ---------------------------
repo = os.environ["GITHUB_REPOSITORY"]
pr_number = os.environ["PR_NUMBER"]
token = os.environ["GITHUB_TOKEN"]

url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"

headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github+json"
}

response = requests.post(url, headers=headers, json={"body": comment})

print("GitHub API response:", response.status_code)
print(response.text)

if response.status_code >= 300:
    raise Exception("Failed to post PR comment")
