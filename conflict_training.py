import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    precision_score,
    recall_score,
    f1_score
)

# ---------------------------
# Load dataset
# ---------------------------
df = pd.read_csv("enhanced_dataset.csv")

print("📊 Original Dataset:")
print(df["conflict"].value_counts())

# ---------------------------
# Balance dataset
# ---------------------------
conflict_df = df[df["conflict"] == 1]
no_conflict_df = df[df["conflict"] == 0]

# Undersample majority class
no_conflict_sampled = no_conflict_df.sample(
    n=len(conflict_df) * 2,  # 2:1 ratio
    random_state=42
)

df_balanced = pd.concat([conflict_df, no_conflict_sampled]).sample(frac=1, random_state=42)

print("\n📊 Balanced Dataset:")
print(df_balanced["conflict"].value_counts())

# ---------------------------
# Features & Target
# ---------------------------
X = df_balanced.drop("conflict", axis=1)
y = df_balanced["conflict"]

# ---------------------------
# Train/Test Split
# ---------------------------
X_train, X_test, y_train, y_test = train_test_split(
    X, y,
    test_size=0.2,
    random_state=42,
    stratify=y
)

# ---------------------------
# Model (no extreme weights)
# ---------------------------
model = RandomForestClassifier(
    n_estimators=300,
    max_depth=10,
    min_samples_split=10,
    min_samples_leaf=4,
    random_state=42
)

# ---------------------------
# Train
# ---------------------------
model.fit(X_train, y_train)

# ---------------------------
# Predict probabilities
# ---------------------------
y_probs = model.predict_proba(X_test)[:, 1]

# ---------------------------
# Threshold tuning
# ---------------------------
thresholds = [0.30, 0.40, 0.50, 0.60]

best_threshold = 0.50
best_f1 = -1

print("\n🎯 Threshold Tuning:")

for t in thresholds:
    y_pred_temp = (y_probs >= t).astype(int)

    precision = precision_score(y_test, y_pred_temp)
    recall = recall_score(y_test, y_pred_temp)
    f1 = f1_score(y_test, y_pred_temp)

    print(f"T={t} | Precision={precision:.3f} Recall={recall:.3f} F1={f1:.3f}")

    if f1 > best_f1:
        best_f1 = f1
        best_threshold = t

print(f"\n✅ Best Threshold: {best_threshold}")

# ---------------------------
# Final evaluation
# ---------------------------
y_pred = (y_probs >= best_threshold).astype(int)

print("\n📊 Classification Report:")
print(classification_report(y_test, y_pred))

print("\n📊 Confusion Matrix:")
print(confusion_matrix(y_test, y_pred))

# ---------------------------
# Feature importance
# ---------------------------
feature_importance = pd.DataFrame({
    "feature": X.columns,
    "importance": model.feature_importances_
}).sort_values(by="importance", ascending=False)

print("\n🔥 Feature Importance:")
print(feature_importance.to_string(index=False))

# ---------------------------
# Save model
# ---------------------------
joblib.dump(model, "conflict_model.pkl")
joblib.dump(best_threshold, "conflict_threshold.pkl")

print("\n✅ Model + threshold saved")