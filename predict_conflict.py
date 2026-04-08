import subprocess
import sys
import math
import re
import os
import joblib
import json
import shutil

# ---------------------------
# Run git command safely
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
        return result.stdout.strip()
    except Exception:
        return ""

# ---------------------------
# Clone repo fresh every time for URL input
# ---------------------------
def prepare_repo(repo_input):
    if repo_input.startswith("http://") or repo_input.startswith("https://"):
        repo_name = repo_input.split("/")[-1].replace(".git", "")
        repo_dir = os.path.join(os.getcwd(), "repos", repo_name)

       
        if os.path.exists(repo_dir):
            print(f"🧹 Removing old cloned repo: {repo_dir}")
            shutil.rmtree(repo_dir)

        os.makedirs(os.path.dirname(repo_dir), exist_ok=True)

        print(f" Cloning fresh repo into: {repo_dir}")
        subprocess.run(["git", "clone", repo_input, repo_dir], check=True)

        print("Fetching latest branches...")
        subprocess.run(["git", "fetch", "--all"], cwd=repo_dir, check=True)

        print("\n DEBUG INFO")
        print("Repo input:", repo_input)
        print("Cloned path:", repo_dir)
        print("Remote config:")
        print(run(["git", "remote", "-v"], repo_dir))

        return repo_dir

    else:
        if not os.path.exists(repo_input):
            print(" Repo path does not exist.")
            sys.exit(1)

        if not os.path.exists(os.path.join(repo_input, ".git")):
            print(" Provided path is not a Git repository.")
            sys.exit(1)

        print(f" Using local repo: {repo_input}")
        run(["git", "fetch", "--all"], repo_input)

        print("\n DEBUG INFO")
        print("Local repo path:", repo_input)
        print("Remote config:")
        print(run(["git", "remote", "-v"], repo_input))

        return repo_input

# ---------------------------
# Check if branch exists
# ---------------------------
def ensure_branch(repo, branch):
    local_branch = run(["git", "branch", "--list", branch], repo)
    remote_branch = run(["git", "branch", "-r", "--list", f"origin/{branch}"], repo)

    if local_branch:
        return

    if remote_branch:
        print(f" Checking out remote branch: {branch}")
        run(["git", "checkout", "-B", branch, f"origin/{branch}"], repo)
    else:
        print(f" Branch '{branch}' not found in repo.")
        sys.exit(1)

# ---------------------------
# Get merge base
# ---------------------------
def get_merge_base(repo, b1, b2):
    base = run(["git", "merge-base", b1, b2], repo)
    if not base:
        print(" Could not find merge base between branches.")
        sys.exit(1)
    return base

# ---------------------------
# Get changed files
# ---------------------------
def get_changed_files_between(repo, start_commit, end_commit):
    files = run(["git", "diff", "--name-only", start_commit, end_commit], repo).split("\n")
    return set(f.strip() for f in files if f.strip())

# ---------------------------
# Get line churn
# ---------------------------
def get_line_churn_between(repo, start_commit, end_commit):
    stat = run(["git", "diff", "--shortstat", start_commit, end_commit], repo)

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
def get_changed_line_ranges_between(repo, start_commit, end_commit, file):
    diff = run(["git", "diff", start_commit, end_commit, "--", file], repo)
    ranges = []

    for line in diff.split("\n"):
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                start = int(match.group(1))
                length = int(match.group(2)) if match.group(2) else 1
                end = start + max(length - 1, 0)
                ranges.append((start, end))

    return ranges

# ---------------------------
# Compute overlap between ranges
# ---------------------------
def compute_overlap_ranges(ranges1, ranges2):
    overlaps = []

    for s1, e1 in ranges1:
        for s2, e2 in ranges2:
            start = max(s1, s2)
            end = min(e1, e2)

            if start <= end:
                overlaps.append((start, end))

    return overlaps

# ---------------------------
# Extract features
# ---------------------------
def extract_features(repo, b1, b2):
    merge_base = get_merge_base(repo, b1, b2)
    print(f"\n🔗 Merge base: {merge_base}")

    files_1 = get_changed_files_between(repo, merge_base, b1)
    files_2 = get_changed_files_between(repo, merge_base, b2)

    overlap_files = files_1 & files_2
    total_files = len(files_1 | files_2)

    overlap = len(overlap_files)
    overlap_ratio = overlap / total_files if total_files > 0 else 0

    total_changed_lines_A = get_line_churn_between(repo, merge_base, b1)
    total_changed_lines_B = get_line_churn_between(repo, merge_base, b2)

    total_overlap_ranges = 0
    total_overlap_lines = 0
    max_file_overlap = 0
    same_file_churn = 0

    file_risk_details = []

    for f in overlap_files:
        ranges1 = get_changed_line_ranges_between(repo, merge_base, b1, f)
        ranges2 = get_changed_line_ranges_between(repo, merge_base, b2, f)
        overlaps = compute_overlap_ranges(ranges1, ranges2)

        overlap_lines = sum(end - start + 1 for start, end in overlaps)
        max_overlap = max((end - start + 1 for start, end in overlaps), default=0)

        total_overlap_ranges += len(overlaps)
        total_overlap_lines += overlap_lines
        max_file_overlap = max(max_file_overlap, max_overlap)
        same_file_churn += len(ranges1) + len(ranges2)

        file_risk_details.append({
            "file": f,
            "branch1_ranges": ranges1,
            "branch2_ranges": ranges2,
            "overlap_ranges": overlaps,
            "overlap_lines": overlap_lines,
            "max_overlap": max_overlap,
            "same_file_churn": len(ranges1) + len(ranges2)
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
# Detect actual git conflicts
# ---------------------------
def detect_actual_conflicts(repo, base_branch, merge_branch):
    print("\n Checking actual Git merge conflict locations...")

    run(["git", "checkout", base_branch], repo)

    merge_result = run(["git", "merge", "--no-commit", "--no-ff", merge_branch], repo)

    conflict_files = []

    if "CONFLICT" in merge_result:
        status = run(["git", "diff", "--name-only", "--diff-filter=U"], repo)
        conflict_files = [f.strip() for f in status.split("\n") if f.strip()]
        print(" Git reports real merge conflicts.")
        run(["git", "merge", "--abort"], repo)
    else:
        print(" Git merge test found no actual conflict.")
        run(["git", "merge", "--abort"], repo)

    return conflict_files

# ---------------------------
# Explain risk reason
# ---------------------------
def explain_risk(prob, threshold, structural_risk, actual_conflict_files):
    if actual_conflict_files:
        return "real_conflict"

    if structural_risk["overlap_files"] == 0 and structural_risk["overlap_lines"] == 0:
        return "false_positive_churn"

    if structural_risk["overlap_files"] > 0 and structural_risk["overlap_lines"] == 0:
        return "same_file_no_line_overlap"

    if structural_risk["overlap_lines"] > 0:
        return "real_structural_risk"

    return "unknown"

# ---------------------------
# Pretty print
# ---------------------------
def print_terminal_output(prob, threshold, risk_type, file_risk_details, git_conflicts):
    print("\n================ RESULT ================\n")
    print(f" Threshold: {threshold:.2f}")
    print(f"Probability: {prob:.4f}")

    if git_conflicts:
        print("\n FINAL RESULT: REAL GIT CONFLICT DETECTED")
    elif risk_type == "real_structural_risk":
        print("\n FINAL RESULT: HIGH STRUCTURAL RISK")
    elif risk_type == "same_file_no_line_overlap":
        print("\n FINAL RESULT: MEDIUM STRUCTURAL RISK")
    elif risk_type == "false_positive_churn":
        print("\n FINAL RESULT: LOW STRUCTURAL RISK")
    elif prob >= threshold:
        print("\n FINAL RESULT: ML FLAGS THIS AS RISKY")
    else:
        print("\n FINAL RESULT: LOW RISK")

    if file_risk_details:
        print("\n Potential Conflict Files:")
        ranked = sorted(
            file_risk_details,
            key=lambda x: (x["overlap_lines"], x["max_overlap"], x["same_file_churn"]),
            reverse=True
        )

        for item in ranked[:10]:
            print(f"\n {item['file']}")
            print(f"   Branch A changed: {item['branch1_ranges']}")
            print(f"   Branch B changed: {item['branch2_ranges']}")
            print(f"   Overlap region:   {item['overlap_ranges']}")
            print(f"   Overlap lines:    {item['overlap_lines']}")
            print(f"   Max overlap:      {item['max_overlap']}")
    else:
        print("\n No overlapping files detected.")

    if git_conflicts:
        print("\n Actual Git Conflict Files:")
        for f in git_conflicts:
            print(f"   - {f}")

# ---------------------------
# Save JSON output
# ---------------------------
def save_json(prob, threshold, risk_type, file_risk_details, git_conflicts):
    ranked = sorted(
        file_risk_details,
        key=lambda x: (x["overlap_lines"], x["max_overlap"], x["same_file_churn"]),
        reverse=True
    )

    result = {
        "probability": round(float(prob), 4),
        "threshold": round(float(threshold), 4),
        "risk_type": risk_type,
        "risk_label": (
            "REAL_GIT_CONFLICT" if git_conflicts else
            "HIGH" if risk_type == "real_structural_risk" else
            "MEDIUM" if risk_type == "same_file_no_line_overlap" else
            "LOW"
        ),
        "potential_conflict_files": ranked[:10],
        "actual_git_conflicts": git_conflicts
    }

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("\n JSON result saved to result.json")

# ---------------------------
# MAIN
# ---------------------------
if len(sys.argv) != 4:
    print("Usage: python predict_conflict.py <repo_path_or_url> <base_branch> <merge_branch>")
    sys.exit(1)

repo_input = sys.argv[1]
base = sys.argv[2]
branch = sys.argv[3]

repo = prepare_repo(repo_input)
ensure_branch(repo, base)
ensure_branch(repo, branch)

model = joblib.load("conflict_model.pkl")
threshold = joblib.load("conflict_threshold.pkl")

print(f"\n Loaded trained threshold: {threshold}")

X, file_risk_details, structural_risk = extract_features(repo, base, branch)

prob = model.predict_proba(X)[0][1]
print(f"\n Conflict Probability: {prob:.4f}")

git_conflicts = detect_actual_conflicts(repo, base, branch)

risk_type = explain_risk(prob, threshold, structural_risk, git_conflicts)

print_terminal_output(prob, threshold, risk_type, file_risk_details, git_conflicts)
save_json(prob, threshold, risk_type, file_risk_details, git_conflicts)
