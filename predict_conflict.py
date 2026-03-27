import subprocess
import sys
import math
import re
import os
import joblib
import pandas as pd

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
# Clone repo once, reuse later
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
        return repo_input

# ---------------------------
# Check if branch exists
# ---------------------------
def ensure_branch(repo, branch):
    local_branches = run(["git", "branch", "--list", branch], repo)
    remote_branches = run(["git", "branch", "-r", "--list", f"origin/{branch}"], repo)

    if local_branches:
        return

    if remote_branches:
        print(f"🌿 Checking out remote branch: {branch}")
        run(["git", "checkout", "-b", branch, f"origin/{branch}"], repo)
    else:
        print(f"❌ Branch '{branch}' not found in repo.")
        sys.exit(1)

# ---------------------------
# Get merge base
# ---------------------------
def get_merge_base(repo, b1, b2):
    base = run(["git", "merge-base", b1, b2], repo)
    if not base:
        print("❌ Could not find merge base between branches.")
        sys.exit(1)
    return base

# ---------------------------
# Get changed files between two commits
# ---------------------------
def get_changed_files_between(repo, start_commit, end_commit):
    files = run(
        ["git", "diff", "--name-only", start_commit, end_commit],
        repo
    ).split("\n")
    return set(f for f in files if f.strip())

# ---------------------------
# Get line churn between two commits
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
# Parse changed line ranges between two commits for a file
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
def compute_line_overlap(ranges1, ranges2):
    overlap_count = 0
    overlap_lines = 0
    max_overlap = 0

    for s1, e1 in ranges1:
        for s2, e2 in ranges2:
            start = max(s1, s2)
            end = min(e1, e2)

            if start <= end:
                overlap_count += 1
                overlap_len = end - start + 1
                overlap_lines += overlap_len
                max_overlap = max(max_overlap, overlap_len)

    return overlap_count, overlap_lines, max_overlap

# ---------------------------
# Try real merge conflict detection
# ---------------------------
def detect_actual_conflicts(repo, base_branch, merge_branch):
    print("\n🧪 Checking actual Git merge conflict locations...")

    run(["git", "checkout", base_branch], repo)

    merge_result = run(
        ["git", "merge", "--no-commit", "--no-ff", merge_branch],
        repo
    )

    conflict_files = []

    if "CONFLICT" in merge_result:
        status = run(["git", "diff", "--name-only", "--diff-filter=U"], repo)
        conflict_files = [f.strip() for f in status.split("\n") if f.strip()]
        print("❌ Git reports real merge conflicts.")
        run(["git", "merge", "--abort"], repo)
    else:
        print("✅ Git merge test found no actual conflict.")
        run(["git", "merge", "--abort"], repo)

    return conflict_files

# ---------------------------
# Extract global features
# ---------------------------
def extract_features(repo, b1, b2):
    merge_base = get_merge_base(repo, b1, b2)

    print(f"\n🔗 Merge base: {merge_base}")

    files_1 = get_changed_files_between(repo, merge_base, b1)
    files_2 = get_changed_files_between(repo, merge_base, b2)

    overlap_files = files_1 & files_2
    overlap = len(overlap_files)
    total_files = len(files_1 | files_2)

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

        overlap_count, overlap_lines, max_overlap = compute_line_overlap(ranges1, ranges2)

        total_overlap_ranges += overlap_count
        total_overlap_lines += overlap_lines
        max_file_overlap = max(max_file_overlap, max_overlap)
        same_file_churn += len(ranges1) + len(ranges2)

        file_risk_details.append({
            "file": f,
            "overlap_ranges": overlap_count,
            "overlap_lines": overlap_lines,
            "max_overlap": max_overlap,
            "same_file_churn": len(ranges1) + len(ranges2),
            "branch1_ranges": ranges1,
            "branch2_ranges": ranges2
        })

    same_file_line_overlap_ratio = (
        total_overlap_lines / (total_changed_lines_A + total_changed_lines_B)
        if (total_changed_lines_A + total_changed_lines_B) > 0 else 0
    )

    churn = math.log1p(total_changed_lines_A + total_changed_lines_B)

    features = pd.DataFrame([[ 
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
    ]], columns=[
        "files_A",
        "files_B",
        "overlap",
        "overlap_ratio",
        "total_changed_lines_A",
        "total_changed_lines_B",
        "total_overlap_ranges",
        "total_overlap_lines",
        "same_file_line_overlap_ratio",
        "max_file_overlap",
        "same_file_churn",
        "churn"
    ])

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
# Safe auto merge
# ---------------------------
def auto_merge(repo, base, branch):
    print(f"\n🟢 Switching to {base}")
    run(["git", "checkout", base], repo)

    print(f"🔄 Merging {branch} into {base}")

    result = run(
        ["git", "merge", "--no-commit", "--no-ff", branch],
        repo
    )

    if "CONFLICT" in result:
        print("❌ Conflict occurred → aborting")
        run(["git", "merge", "--abort"], repo)
        return False

    commit_output = run(["git", "commit", "-m", "Auto merged by ML system"], repo)

    if "nothing to commit" in commit_output.lower():
        print("ℹ️ Merge completed, but nothing new to commit.")
    else:
        print("✅ Auto merge successful")

    return True

# ---------------------------
# Explain risk reason
# ---------------------------
def explain_risk(prob, threshold, structural_risk, actual_conflict_files):
    print("\n🧠 Risk Interpretation:")

    if actual_conflict_files:
        print("   → Git directly detected a real merge conflict.")
        return "real_conflict"

    if structural_risk["overlap_files"] == 0 and structural_risk["overlap_lines"] == 0:
        print("   → No overlapping files or overlapping lines were found.")
        print("   → Elevated ML score is caused by global branch churn only.")
        return "false_positive_churn"

    if structural_risk["overlap_files"] > 0 and structural_risk["overlap_lines"] == 0:
        print("   → Same files were changed, but not the same line regions.")
        print("   → This is moderate structural risk, not direct line conflict.")
        return "same_file_no_line_overlap"

    if structural_risk["overlap_lines"] > 0:
        if prob >= threshold:
            print("   → Same files and overlapping line regions were detected.")
            print("   → ML model also agrees this looks risky.")
        else:
            print("   → Structural overlap exists, even though ML score is below threshold.")
        return "real_structural_risk"

    return "unknown"

# ---------------------------
# MAIN
# ---------------------------
if len(sys.argv) != 4:
    print("Usage: python predict_conflict.py <repo_path_or_url> <base_branch> <merge_branch>")
    sys.exit(1)

repo_input = sys.argv[1]
base = sys.argv[2]
branch = sys.argv[3]

# ---------------------------
# Prepare repo
# ---------------------------
repo = prepare_repo(repo_input)

# ---------------------------
# Ensure branches exist
# ---------------------------
ensure_branch(repo, base)
ensure_branch(repo, branch)

# ---------------------------
# Load trained model + threshold
# ---------------------------
model = joblib.load("conflict_model.pkl")
best_threshold = joblib.load("conflict_threshold.pkl")

print(f"\n🎯 Loaded trained threshold: {best_threshold}")

# ---------------------------
# Extract features
# ---------------------------
X, file_risk_details, structural_risk = extract_features(repo, base, branch)

print("\n📊 Extracted Features:")
print(X.to_string(index=False))

# ---------------------------
# Predict conflict probability
# ---------------------------
prob = model.predict_proba(X)[0][1]
print(f"\n🔍 Conflict Probability: {prob:.4f}")

# ---------------------------
# Real Git conflict test
# ---------------------------
actual_conflict_files = detect_actual_conflicts(repo, base, branch)

# ---------------------------
# Explain result
# ---------------------------
risk_type = explain_risk(prob, best_threshold, structural_risk, actual_conflict_files)

# ---------------------------
# Final Decision Logic
# ---------------------------
if actual_conflict_files:
    print("\n🚨 FINAL RESULT: REAL GIT CONFLICT DETECTED")
    print("Conflicting files:")
    for f in actual_conflict_files:
        print(f"  - {f}")

elif risk_type == "false_positive_churn":
    print("\n🟢 FINAL RESULT: LOW STRUCTURAL RISK")
    print("   ML score is elevated, but there is no actual file/line overlap.")
    print("   This is likely a false positive caused by branch size/churn.")
    print("   ✅ Merge is likely safe.")

elif risk_type == "same_file_no_line_overlap":
    print("\n🟡 FINAL RESULT: MEDIUM STRUCTURAL RISK")
    print("   Same files were modified, but overlapping line edits were not found.")
    print("   Manual review is recommended.")

    if file_risk_details:
        print("\n⚠️ Same Files Modified:")
        ranked = sorted(
            file_risk_details,
            key=lambda x: (x["same_file_churn"], x["max_overlap"], x["overlap_lines"]),
            reverse=True
        )

        for item in ranked[:10]:
            print(
                f"  {item['file']} | "
                f"same_file_churn={item['same_file_churn']} | "
                f"overlap_lines={item['overlap_lines']} | "
                f"max_overlap={item['max_overlap']}"
            )

elif risk_type == "real_structural_risk":
    print("\n🔴 FINAL RESULT: HIGH STRUCTURAL RISK")
    print("   Overlapping files and overlapping line regions were found.")
    print("   Conflict is likely.")

    if file_risk_details:
        print("\n🔥 Potential Conflict Files:")
        ranked = sorted(
            file_risk_details,
            key=lambda x: (x["overlap_lines"], x["max_overlap"], x["same_file_churn"]),
            reverse=True
        )

        for item in ranked[:10]:
            print(
                f"  {item['file']} | "
                f"overlap_lines={item['overlap_lines']} | "
                f"max_overlap={item['max_overlap']} | "
                f"same_file_churn={item['same_file_churn']}"
            )

else:
    if prob >= best_threshold:
        print("\n🟡 FINAL RESULT: ML FLAGS THIS AS RISKY")
        print("   ML probability crossed the trained threshold.")
        print("   Manual review recommended.")
    else:
        print("\n🟢 FINAL RESULT: LOW RISK")
        print("   ML probability is below trained threshold.")
        print("   ✅ Merge is likely safe.")