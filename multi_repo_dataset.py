import subprocess
import pandas as pd
import os
import math

# ---------------------------
# Run git command safely
# ---------------------------
def run(cmd, cwd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        return result.stdout.strip()
    except:
        return ""

# ---------------------------
# Process each repo
# ---------------------------
def process_repo(path):
    print(f"\n🔍 Processing repo: {path}")

    merges_raw = run(["git", "log", "--merges", "--pretty=%H"], path)

    if not merges_raw:
        print("⚠️ No merge commits found")
        return []

    merges = merges_raw.split("\n")
    rows = []

    for merge in merges[:40]:

        parents = run(
            ["git", "rev-list", "--parents", "-n", "1", merge],
            path
        ).split()

        if len(parents) < 3:
            continue

        _, p1, p2 = parents

        # ---------------------------
        # File changes per branch
        # ---------------------------
        files_p1 = set(run(
            ["git", "diff", "--name-only", f"{p1}^", p1],
            path
        ).split("\n"))

        files_p2 = set(run(
            ["git", "diff", "--name-only", f"{p2}^", p2],
            path
        ).split("\n"))

        files_p1.discard('')
        files_p2.discard('')

        overlap = len(files_p1 & files_p2)
        total_files = len(files_p1 | files_p2)

        if total_files == 0:
            continue

        overlap_ratio = overlap / total_files

        # ---------------------------
        # Line stats of merge
        # ---------------------------
        stat = run(["git", "diff", "--shortstat", merge], path)

        added, deleted = 0, 0

        if "insertion" in stat:
            try:
                added = int(stat.split("insertion")[0].split()[-1])
            except:
                pass

        if "deletion" in stat:
            try:
                deleted = int(stat.split("deletion")[0].split()[-1])
            except:
                pass

        # ---------------------------
        # ✅ FIXED CHURN (LOG SCALE)
        # ---------------------------
        raw_churn = added + deleted
        churn = math.log1p(raw_churn)

        # ---------------------------
        # Label (heuristic)
        # ---------------------------
        if overlap_ratio > 0.4:
            conflict = 1
        elif overlap_ratio < 0.1:
            conflict = 0
        else:
            conflict = 1 if raw_churn > 1500 else 0

        # ---------------------------
        # Store row
        # ---------------------------
        rows.append([
            len(files_p1),
            len(files_p2),
            overlap,
            overlap_ratio,
            added,
            deleted,
            churn,
            conflict
        ])

    print(f"✅ Extracted {len(rows)} rows from {path}")
    return rows

# ---------------------------
# MAIN
# ---------------------------

repos = [
    "AutoGPT",
    "core",
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
    else:
        print(f"⚠️ Not a git repo: {repo}")

# ---------------------------
# Create DataFrame
# ---------------------------
df = pd.DataFrame(all_data, columns=[
    "files_A",
    "files_B",
    "overlap",
    "overlap_ratio",
    "lines_added",
    "lines_deleted",
    "churn",
    "conflict"
])

print("\n📊 Dataset Summary:")
print(df["conflict"].value_counts())
print(f"\n📈 Total rows: {len(df)}")

if len(df) == 0:
    print("❌ No data collected.")
    exit()

# ---------------------------
# Save dataset
# ---------------------------
df.to_csv("final_dataset.csv", index=False)

print("\n✅ Dataset created: final_dataset.csv")
