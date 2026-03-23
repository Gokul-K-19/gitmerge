import subprocess
import pandas as pd
import os
import random

# ---------------------------
# Run git command
# ---------------------------
def run(cmd, cwd):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.stdout.strip()

# ---------------------------
# Process each repo
# ---------------------------
def process_repo(path):
    print(f"\n🔍 Processing repo: {path}")

    merges = run(["git", "log", "--merges", "--pretty=%H"], path).split("\n")

    rows = []

    for merge in merges[:40]:  # limit per repo

        parents = run(["git", "rev-list", "--parents", "-n", "1", merge], path).split()

        if len(parents) < 3:
            continue

        _, p1, p2 = parents

        # ---------------------------
        # Files changed
        # ---------------------------
        files_A = set(run(["git", "diff", "--name-only", p1], path).split("\n"))
        files_B = set(run(["git", "diff", "--name-only", p2], path).split("\n"))

        files_A.discard('')
        files_B.discard('')

        overlap = len(files_A & files_B)
        total_files = len(files_A | files_B)

        if total_files == 0:
            continue

        overlap_ratio = overlap / total_files

        # ---------------------------
        # Line stats
        # ---------------------------
        stat = run(["git", "diff", "--shortstat", merge], path)

        added, deleted = 0, 0

        if "insertion" in stat:
            try:
                added = int(stat.split("insertion")[0].split()[-1])
            except:
                added = 0

        if "deletion" in stat:
            try:
                deleted = int(stat.split("deletion")[0].split()[-1])
            except:
                deleted = 0

        churn = added + deleted

        # ---------------------------
        # IMPROVED LABELING LOGIC
        # ---------------------------
        if overlap_ratio > 0.4:
            conflict = 1
        elif overlap_ratio < 0.1:
            conflict = 0
        else:
            # borderline → use churn
            if churn > 1500:
                conflict = 1
            else:
                conflict = 0

        # ---------------------------
        # Store row
        # ---------------------------
        rows.append([
            len(files_A),
            len(files_B),
            overlap,
            overlap_ratio,
            added,
            deleted,
            churn,
            conflict
        ])

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
    if os.path.exists(repo):
        all_data.extend(process_repo(repo))
    else:
        print(f"⚠️ Repo not found: {repo}")

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

print("\n📊 Before Balancing:")
print(df["conflict"].value_counts())

# ---------------------------
# BALANCE DATASET
# ---------------------------
df_conflict = df[df.conflict == 1]
df_no_conflict = df[df.conflict == 0]

min_size = min(len(df_conflict), len(df_no_conflict))

df_conflict = df_conflict.sample(min_size, random_state=42)
df_no_conflict = df_no_conflict.sample(min_size, random_state=42)

df_balanced = pd.concat([df_conflict, df_no_conflict])

# Shuffle
df_balanced = df_balanced.sample(frac=1, random_state=42)

print("\n📊 After Balancing:")
print(df_balanced["conflict"].value_counts())

# ---------------------------
# Save dataset
# ---------------------------
df_balanced.to_csv("final_dataset.csv", index=False)

print("\n✅ Dataset created: final_dataset.csv")
print(f"📈 Total rows: {len(df_balanced)}")