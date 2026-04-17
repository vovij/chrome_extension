"""
Benchmark SeenIt novelty/similarity detector on URL pair datasets.

Expected CSV format:
- Two URL columns (article pair)
- One label column indicating if pair is similar (>= 70%)

Example:
    poetry run python benchmark_novelty_detector.py \
      --input-csv ../backend/my_pairs.csv \
      --output-dir ../backend/out_novelty_benchmark
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)

from engine import EmbeddingEngine
from extract_content import extract_article_content


DEFAULT_SIMILARITY_THRESHOLD = 0.70

URL1_CANDIDATES = ("url1", "link1", "article1_url", "left_url", "source_url")
URL2_CANDIDATES = ("url2", "link2", "article2_url", "right_url", "target_url")
LABEL_CANDIDATES = ("label", "similar", "is_similar", "same_topic", "resemble")


def _normalize_label(value) -> Optional[int]:
    if pd.isna(value):
        return None

    if isinstance(value, (int, np.integer)):
        return int(value != 0)
    if isinstance(value, (float, np.floating)):
        return int(value >= 0.5)
    if isinstance(value, bool):
        return int(value)

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "similar"}:
        return 1
    if text in {"0", "false", "no", "n", "different", "dissimilar"}:
        return 0

    return None


def _pick_column(
    df: pd.DataFrame,
    explicit: Optional[str],
    candidates: Iterable[str],
    name_for_errors: str,
) -> str:
    if explicit:
        if explicit not in df.columns:
            raise ValueError(f"Column '{explicit}' was not found for {name_for_errors}.")
        return explicit

    lowered = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lowered:
            return lowered[cand.lower()]

    raise ValueError(
        f"Could not auto-detect {name_for_errors} column. "
        f"Available columns: {list(df.columns)}. "
        f"Use --{name_for_errors}-col to specify it explicitly."
    )


def _safe_text(title: str, content: str) -> Tuple[str, str]:
    title = (title or "").strip()
    content = (content or "").strip()
    return title, content


def _embed_url(url: str, engine: EmbeddingEngine) -> Dict:
    extracted = extract_article_content(url)
    title, text = _safe_text(extracted.get("title", ""), extracted.get("text", ""))

    if not title and not text:
        return {
            "ok": False,
            "url": url,
            "title": "",
            "content_chars": 0,
            "error": "content_extraction_failed",
            "embedding": None,
        }

    emb = engine.embed(title, text)
    return {
        "ok": True,
        "url": url,
        "title": title,
        "content_chars": len(text),
        "error": "",
        "embedding": emb,
    }


def run_benchmark(
    input_csv: Path,
    output_dir: Path,
    similarity_threshold: float,
    url1_col: Optional[str],
    url2_col: Optional[str],
    label_col: Optional[str],
) -> Dict:
    df = pd.read_csv(input_csv)
    if df.empty:
        raise ValueError("Input CSV is empty.")

    c_url1 = _pick_column(df, url1_col, URL1_CANDIDATES, "url1")
    c_url2 = _pick_column(df, url2_col, URL2_CANDIDATES, "url2")
    c_label = _pick_column(df, label_col, LABEL_CANDIDATES, "label")

    work = df[[c_url1, c_url2, c_label]].copy()
    work.columns = ["url1", "url2", "label_raw"]
    work["label"] = work["label_raw"].apply(_normalize_label)
    work = work.dropna(subset=["label"]).copy()
    work["label"] = work["label"].astype(int)

    if work.empty:
        raise ValueError("No valid labels after normalization. Check label values.")

    output_dir.mkdir(parents=True, exist_ok=True)

    engine = EmbeddingEngine()
    unique_urls = sorted(set(work["url1"].tolist() + work["url2"].tolist()))

    url_cache: Dict[str, Dict] = {}
    for idx, url in enumerate(unique_urls, start=1):
        print(f"[{idx}/{len(unique_urls)}] extracting+embedding: {url}")
        url_cache[url] = _embed_url(url, engine)

    rows: List[Dict] = []
    for _, row in work.iterrows():
        url1 = row["url1"]
        url2 = row["url2"]
        y_true = int(row["label"])

        left = url_cache[url1]
        right = url_cache[url2]

        if left["ok"] and right["ok"]:
            sim = float(engine.cosine(left["embedding"], right["embedding"]))
            novelty = float(max(0.0, min(1.0, 1.0 - sim)))
            y_pred = int(sim >= similarity_threshold)
            pair_ok = True
            error = ""
        else:
            sim = np.nan
            novelty = np.nan
            y_pred = -1
            pair_ok = False
            error = "left_failed" if not left["ok"] else "right_failed"

        rows.append(
            {
                "url1": url1,
                "url2": url2,
                "label": y_true,
                "prediction": y_pred,
                "pair_ok": pair_ok,
                "similarity": sim,
                "novelty_score": novelty,
                "threshold_similarity": similarity_threshold,
                "title1": left["title"],
                "title2": right["title"],
                "content_chars1": left["content_chars"],
                "content_chars2": right["content_chars"],
                "error": error,
            }
        )

    result_df = pd.DataFrame(rows)
    valid = result_df[result_df["pair_ok"]].copy()

    if valid.empty:
        raise ValueError("All pairs failed extraction/embedding. No benchmark metrics computed.")

    y_true = valid["label"].to_numpy()
    y_pred = valid["prediction"].to_numpy()
    y_score = valid["similarity"].to_numpy()

    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    acc = accuracy_score(y_true, y_pred)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    auc = None
    if len(np.unique(y_true)) > 1:
        auc = float(roc_auc_score(y_true, y_score))

    metrics = {
        "input_csv": str(input_csv),
        "total_rows": int(len(df)),
        "rows_with_valid_labels": int(len(work)),
        "pairs_evaluated": int(len(valid)),
        "pairs_failed": int(len(result_df) - len(valid)),
        "similarity_threshold": float(similarity_threshold),
        "novelty_threshold_equivalent": float(1.0 - similarity_threshold),
        "accuracy": float(acc),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "roc_auc": auc,
        "confusion_matrix": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp),
        },
    }

    detailed_path = output_dir / "pair_scores.csv"
    metrics_path = output_dir / "metrics.json"
    result_df.to_csv(detailed_path, index=False)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark SeenIt novelty detector on URL pairs CSV.")
    parser.add_argument("--input-csv", required=True, type=Path, help="Path to CSV file with URL pairs.")
    parser.add_argument("--output-dir", type=Path, default=Path("./out_novelty_benchmark"))
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        help="Predict 'similar' when similarity >= threshold (default: 0.70).",
    )
    parser.add_argument("--url1-col", type=str, default=None, help="Override first URL column name.")
    parser.add_argument("--url2-col", type=str, default=None, help="Override second URL column name.")
    parser.add_argument("--label-col", type=str, default=None, help="Override label column name.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    metrics = run_benchmark(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        similarity_threshold=args.similarity_threshold,
        url1_col=args.url1_col,
        url2_col=args.url2_col,
        label_col=args.label_col,
    )

    print("\n=== Benchmark complete ===")
    for k, v in metrics.items():
        if isinstance(v, dict):
            print(f"{k}: {json.dumps(v)}")
        else:
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
