import subprocess
import pandas as pd
import os
import math
import re

# ---------------------------
# Run command safely
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
# Detect REAL conflict using merge-tree
# ---------------------------
def has_conflict(repo, p1, p2):
    base = run(["git", "merge-base", p1, p2], repo)
    if not base:
        return 0

    output = run(["git", "merge-tree", base, p1, p2], repo)
    return 1 if "<<<<<<<" in output else 0

# ---------------------------
# Get changed files between two commits
# ---------------------------
def get_changed_files_between(repo, start_commit, end_commit):
    files = run(
        ["git", "diff", "--name-only", start_commit, end_commit],
        repo
    ).split("\n")
    return set(f.strip() for f in files if f.strip())

# ---------------------------
# Parse changed line ranges between two commits
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
# Count overlap between line ranges
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
# Process one repo
# ---------------------------
def process_repo(path):
    print(f"\nProcessing repo: {path}")

    merges_raw = run(["git", "log", "--merges", "--pretty=%H"], path)

    if not merges_raw:
        return []

    merges = merges_raw.split("\n")
    rows = []

    MAX_MERGES_PER_REPO = 300

    for merge in merges[:MAX_MERGES_PER_REPO]:
        parents = run(
            ["git", "rev-list", "--parents", "-n", "1", merge],
            path
        ).split()

        if len(parents) < 3:
            continue

        _, p1, p2 = parents

        merge_base = run(["git", "merge-base", p1, p2], path)
        if not merge_base:
            continue

        # Compare each parent branch against merge base
        files_p1 = get_changed_files_between(path, merge_base, p1)
        files_p2 = get_changed_files_between(path, merge_base, p2)

        total_files = len(files_p1 | files_p2)
        if total_files == 0:
            continue

        overlap_files = files_p1 & files_p2
        overlap = len(overlap_files)
        overlap_ratio = overlap / total_files if total_files > 0 else 0

        total_changed_lines_A = get_line_churn_between(path, merge_base, p1)
        total_changed_lines_B = get_line_churn_between(path, merge_base, p2)

        total_overlap_ranges = 0
        total_overlap_lines = 0
        max_file_overlap = 0
        same_file_churn = 0

        for f in overlap_files:
            ranges1 = get_changed_line_ranges_between(path, merge_base, p1, f)
            ranges2 = get_changed_line_ranges_between(path, merge_base, p2, f)

            overlap_count, overlap_lines, max_overlap = compute_line_overlap(ranges1, ranges2)

            total_overlap_ranges += overlap_count
            total_overlap_lines += overlap_lines
            max_file_overlap = max(max_file_overlap, max_overlap)

            same_file_churn += len(ranges1) + len(ranges2)

        same_file_line_overlap_ratio = (
            total_overlap_lines / (total_changed_lines_A + total_changed_lines_B)
            if (total_changed_lines_A + total_changed_lines_B) > 0 else 0
        )

        churn = math.log1p(total_changed_lines_A + total_changed_lines_B)

        conflict = has_conflict(path, p1, p2)

        rows.append([
            len(files_p1),
            len(files_p2),
            overlap,
            overlap_ratio,
            total_changed_lines_A,
            total_changed_lines_B,
            total_overlap_ranges,
            total_overlap_lines,
            same_file_line_overlap_ratio,
            max_file_overlap,
            same_file_churn,
            churn,
            conflict
        ])

    print(f"Extracted {len(rows)} rows from {path}")
    return rows

# ---------------------------
# MAIN
# ---------------------------
repos = [
    "AutoGPT",
    "langchain",
    "LLMs-from-scratch",
    "markitdown",
    "Python",
    "tensorflow",
    "pytorch",
    "transformers",
    "fastapi",
    "yt-dlp",
    "system-design-primer"
]

all_data = []

for repo in repos:
    if os.path.exists(os.path.join(repo, ".git")):
        all_data.extend(process_repo(repo))

df = pd.DataFrame(all_data, columns=[
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
    "churn",
    "conflict"
])

print("\nDataset Summary:")
print(df["conflict"].value_counts())

print("\nConflict Ratio:")
print(df["conflict"].value_counts(normalize=True))

df.to_csv("enhanced_dataset.csv", index=False)

print("\nEnhanced dataset created successfully!")
