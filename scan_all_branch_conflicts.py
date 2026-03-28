import subprocess
import sys
import os
import re
import math
import joblib
import json
from itertools import combinations

# ---------------------------
# Run git command safely + debug
# ---------------------------
def run(cmd, cwd):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            cwd=cwd
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except:
        return ""

# ---------------------------
# Prepare repo
# ---------------------------
def prepare_repo(repo_input):
    if repo_input.startswith("http://") or repo_input.startswith("https://"):
        repo_name = repo_input.split("/")[-1].replace(".git", "")
        repo_dir = os.path.join(os.getcwd(), "repos", repo_name)

        os.makedirs(os.path.dirname(repo_dir), exist_ok=True)

        if not os.path.exists(repo_dir):
            print(f"📥 Cloning repo into: {repo_dir}")
            subprocess.run(["git", "clone", repo_input, repo_dir], check=True)
        else:
            print(f"📂 Using existing cloned repo: {repo_dir}")

        print("🔄 Fetching latest branches...")
        subprocess.run(["git", "fetch", "--all"], cwd=repo_dir, check=True)

        return repo_dir
    else:
        if not os.path.exists(repo_input):
            print("❌ Repo path does not exist.")
            sys.exit(1)

        if not os.path.exists(os.path.join(repo_input, ".git")):
            print("❌ Provided path is not a Git repository.")
            sys.exit(1)

        print(f"📂 Using local repo: {repo_input}")
        run(["git", "fetch", "--all"], repo_input)
        return repo_input

# ---------------------------
# Get all remote branches
# ---------------------------
def get_branches(repo):
    remote = run(["git", "branch", "-r", "--format=%(refname:short)"], repo).split("\n")

    branches = set()

    for b in remote:
        b = b.strip()
        if b.startswith("origin/"):
            name = b.replace("origin/", "")
            if name != "HEAD":
                branches.add(name)

    if not branches:
        local = run(["git", "branch", "--format=%(refname:short)"], repo).split("\n")
        for b in local:
            b = b.strip()
            if b and b != "HEAD":
                branches.add(b)

    return sorted(list(branches))

# ---------------------------
# Resolve remote ref safely
# ---------------------------
def ref(branch):
    return f"origin/{branch}"

# ---------------------------
# Get merge base
# ---------------------------
def get_merge_base(repo, b1, b2):
    return run(["git", "merge-base", ref(b1), ref(b2)], repo)

# ---------------------------
# Changed files
# ---------------------------
def get_changed_files_between(repo, start, end):
    files = run(["git", "diff", "--name-only", start, end], repo).split("\n")
    return set(f.strip() for f in files if f.strip())

# ---------------------------
# Line churn
# ---------------------------
def get_line_churn_between(repo, start, end):
    stat = run(["git", "diff", "--shortstat", start, end], repo)

    added, deleted = 0, 0

    insert_match = re.search(r"(\d+)\s+insertion", stat)
    delete_match = re.search(r"(\d+)\s+deletion", stat)

    if insert_match:
        added = int(insert_match.group(1))
    if delete_match:
        deleted = int(delete_match.group(1))

    return added + deleted

# ---------------------------
# Parse changed line ranges
# ---------------------------
def get_changed_line_ranges_between(repo, start, end, file):
    diff = run(["git", "diff", start, end, "--", file], repo)
    ranges = []

    for line in diff.split("\n"):
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                s = int(match.group(1))
                l = int(match.group(2)) if match.group(2) else 1
                e = s + max(l - 1, 0)
                ranges.append((s, e))
    return ranges

# ---------------------------
# Overlap calculation
# ---------------------------
def compute_overlap_ranges(r1, r2):
    overlaps = []
    for s1, e1 in r1:
        for s2, e2 in r2:
            s = max(s1, s2)
            e = min(e1, e2)
            if s <= e:
                overlaps.append((s, e))
    return overlaps

# ---------------------------
# Extract features
# ---------------------------
def extract_features(repo, b1, b2):
    print(f"\n[DEBUG] Extracting features for {b1} ↔ {b2}")

    merge_base = get_merge_base(repo, b1, b2)
    if not merge_base:
        print("[DEBUG] No merge base found")
        return None, [], {}

    print(f"[DEBUG] Merge base: {merge_base}")

    files_1 = get_changed_files_between(repo, merge_base, ref(b1))
    files_2 = get_changed_files_between(repo, merge_base, ref(b2))

    overlap_files = files_1 & files_2
    total_files = len(files_1 | files_2)

    overlap = len(overlap_files)
    overlap_ratio = overlap / total_files if total_files > 0 else 0

    total_changed_lines_A = get_line_churn_between(repo, merge_base, ref(b1))
    total_changed_lines_B = get_line_churn_between(repo, merge_base, ref(b2))

    total_overlap_ranges = 0
    total_overlap_lines = 0
    max_file_overlap = 0
    same_file_churn = 0

    file_risk_details = []

    for f in overlap_files:
        r1 = get_changed_line_ranges_between(repo, merge_base, ref(b1), f)
        r2 = get_changed_line_ranges_between(repo, merge_base, ref(b2), f)
        overlaps = compute_overlap_ranges(r1, r2)

        overlap_lines = sum(e - s + 1 for s, e in overlaps)
        max_overlap = max((e - s + 1 for s, e in overlaps), default=0)

        total_overlap_ranges += len(overlaps)
        total_overlap_lines += overlap_lines
        max_file_overlap = max(max_file_overlap, max_overlap)
        same_file_churn += len(r1) + len(r2)

        file_risk_details.append({
            "file": f,
            "branch1_ranges": r1,
            "branch2_ranges": r2,
            "overlap_ranges": overlaps,
            "overlap_lines": overlap_lines,
            "max_overlap": max_overlap,
            "same_file_churn": len(r1) + len(r2)
        })

    same_file_line_overlap_ratio = (
        total_overlap_lines / (total_changed_lines_A + total_changed_lines_B)
        if (total_changed_lines_A + total_changed_lines_B) > 0 else 0
    )

    churn = math.log1p(total_changed_lines_A + total_changed_lines_B)

    features = [[
        len(files_1),
        len(files_2),
        overlap,
        overlap_ratio,
        total_changed_lines_A,
        total_changed_lines_B,
        total_overlap_ranges,
        total_overlap_lines,
        same_file_line_overlap_ratio,
        max_file_overlap,
        same_file_churn,
        churn
    ]]

    structural_risk = {
        "merge_base": merge_base,
        "files_A": len(files_1),
        "files_B": len(files_2),
        "overlap_files": len(overlap_files),
        "overlap_lines": total_overlap_lines,
        "same_file_overlap_ratio": same_file_line_overlap_ratio
    }

    return features, file_risk_details, structural_risk

# ---------------------------
# Explain risk
# ---------------------------
def explain_risk(prob, threshold, structural_risk):
    if structural_risk.get("overlap_files", 0) == 0 and structural_risk.get("overlap_lines", 0) == 0:
        return "LOW"

    if structural_risk.get("overlap_files", 0) > 0 and structural_risk.get("overlap_lines", 0) == 0:
        return "MEDIUM"

    if structural_risk.get("overlap_lines", 0) > 0:
        return "HIGH" if prob >= threshold else "MEDIUM"

    return "LOW"

# ---------------------------
# MAIN
# ---------------------------
if len(sys.argv) != 2:
    print("Usage: python scan_all_branch_conflicts.py <repo_path_or_url>")
    sys.exit(1)

repo_input = sys.argv[1]
repo = prepare_repo(repo_input)

print("\n[DEBUG] Loading model...")
model = joblib.load("conflict_model.pkl")
threshold = joblib.load("conflict_threshold.pkl")

branches = get_branches(repo)

print("\n🌿 Branches found:")
for b in branches:
    print(f"  - {b}")

pairs = list(combinations(branches, 2))

print(f"\n🔍 Scanning {len(pairs)} branch pairs...\n")

results = []

for b1, b2 in pairs:
    print(f"Checking: {b1} ↔ {b2}")

    X, file_details, structural_risk = extract_features(repo, b1, b2)

    if X is None:
        print("   ⚠️ Skipped (no merge base found)\n")
        continue

    prob = model.predict_proba(X)[0][1]
    risk_label = explain_risk(prob, threshold, structural_risk)

    top_files = sorted(
        file_details,
        key=lambda x: (x["overlap_lines"], x["max_overlap"], x["same_file_churn"]),
        reverse=True
    )[:5]

    results.append({
        "branch1": b1,
        "branch2": b2,
        "probability": round(float(prob), 4),
        "risk_label": risk_label,
        "overlap_files": [f["file"] for f in top_files],
        "structural_risk": structural_risk
    })

risk_order = {
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1
}

results = sorted(
    results,
    key=lambda x: (risk_order.get(x["risk_label"], 0), x["probability"]),
    reverse=True
)

print("\n================ TOP RISKY BRANCH PAIRS ================\n")

if not results:
    print("No valid branch pairs found.\n")

for i, item in enumerate(results[:20], start=1):
    print(f"{i}. {item['branch1']} ↔ {item['branch2']}")
    print(f"   Risk: {item['risk_label']}")
    print(f"   Probability: {item['probability']}")
    print(f"   Potential files: {item['overlap_files']}\n")

with open("branch_pair_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("✅ Saved branch pair scan results to branch_pair_results.json")