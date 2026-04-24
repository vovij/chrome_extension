# post_train_calibrate.py
from pathlib import Path
import numpy as np
from utils import (
    set_seed, load_encoder, load_articles, load_pairs, encode_id_texts, fill_E,
    pick_tau_for_precision, eval_with_fixed_tau, train_logreg, eval_logreg, write_json, write_jsonl
)

CONFIG = {
    # Choose one of the two (hub vs local SFT)
    "model_name": 'sentence-transformers/all-MiniLM-L12-v2', #"sentence-transformers/all-MiniLM-L6-v2",
    "model_dir":   "out_sft_minilm_L12/encoder-sft-minilm", #"out_sft_minilm/encoder-sft-minilm"

    # Data
    "articles_train": "out_wcep_dataset_sft/articles.train.jsonl",
    "articles_val":   "out_wcep_dataset_sft/articles.val.jsonl",
    "articles_test":  "out_wcep_dataset_sft/articles.test.jsonl",
    # Fusion training split: "train" or "val" (often val is fine/stable)
    "fusion_train_split": "val",
    "pairs_train":    "out_wcep_dataset_sft/pairs.val.jsonl",
    "pairs_val":      "out_wcep_dataset_sft/pairs.val.jsonl",
    "pairs_test":     "out_wcep_dataset_sft/pairs.test.jsonl",

    # Text assembly used here must match inference
    "text_field": None,          # or a prebuilt field name; None => title + text[:clip]
    "text_clip_chars": 2000,

    # Calibration
    "target_precision": 0.98,
    "fix_tau_on_test": True,     # pick τ on val and apply to test

    # I/O
    "outdir": "out_posttrain_sft_minilm_L12", #"out_posttrain_sft_minilm"
    "save_pairs_with_E": True,
    "seed": 2026,
    "device": 'cuda',       
    "batch_size_encode": 64
}

def main():
    C = CONFIG
    set_seed(C["seed"])
    Path(C["outdir"]).mkdir(parents=True, exist_ok=True)

    # Load encoder
    model = load_encoder(model_name=C["model_name"], model_dir=C["model_dir"], device=C["device"])

    # Load articles
    arts_tr = load_articles(C["articles_train"], C["text_clip_chars"], C["text_field"])
    arts_va = load_articles(C["articles_val"],   C["text_clip_chars"], C["text_field"])
    arts_te = load_articles(C["articles_test"],  C["text_clip_chars"], C["text_field"])

    # Encode per split (avoid leakage)
    id2emb_tr = encode_id_texts(model, arts_tr, batch_size=C["batch_size_encode"])
    id2emb_va = encode_id_texts(model, arts_va, batch_size=C["batch_size_encode"])
    id2emb_te = encode_id_texts(model, arts_te, batch_size=C["batch_size_encode"])

    # Load pairs
    df_tr = load_pairs(C["pairs_train"])
    df_va = load_pairs(C["pairs_val"])
    df_te = load_pairs(C["pairs_test"])

    # Fill cosine E
    df_tr = fill_E(df_tr, id2emb_tr)
    df_va = fill_E(df_va, id2emb_va)
    df_te = fill_E(df_te, id2emb_te)

    # Embed-only τ: choose on val and (optionally) fix on test
    best_va = pick_tau_for_precision(df_va["label"].values, df_va["E"].values, C["target_precision"])
    tau_embed = float(best_va["tau"])
    if C["fix_tau_on_test"]:
        embed_test = eval_with_fixed_tau(df_te["label"].values, df_te["E"].values, tau_embed)
    else:
        # (Not recommended for unbiased eval) pick separate τ on test
        best_te = pick_tau_for_precision(df_te["label"].values, df_te["E"].values, C["target_precision"])
        embed_test = {"precision": best_te["precision"], "recall": best_te["recall"], "f1": best_te["f1"], "auc": None}

    # Fusion: choose training split
    feature_cols = [c for c in ["T","Sh","E","time_diff_days"] if c in df_tr.columns]
    if C["fusion_train_split"] == "train":
        clf, best_logreg_va = train_logreg(df_tr, df_va, feature_cols, C["target_precision"])
    else:  # "val": train on val, choose τ on val as well
        clf, best_logreg_va = train_logreg(df_va, df_va, feature_cols, C["target_precision"])  # small & stable
    logreg_test = eval_logreg(df_te, feature_cols, clf, float(best_logreg_va["tau"]))

    # Save config
    cfg = {
        "model": (C["model_dir"] or C["model_name"]),
        "text_clip_chars": C["text_clip_chars"],
        "post_train": {
            "feature_cols": feature_cols,
            "logreg": {
                "weights": clf.coef_[0].tolist(),
                "bias": float(clf.intercept_[0]),
                "tau_prob": float(best_logreg_va["tau"])
            },
            "tau_embed_only": tau_embed
        },
        "metrics": {
            "embed_only": {"val": best_va, "test": embed_test},
            "logreg":     {"val": best_logreg_va, "test": logreg_test}
        },
        "seed": C["seed"]
    }
    write_json(f"{C['outdir']}/post_train_config.json", cfg)

    if C["save_pairs_with_E"]:
        write_jsonl(f"{C['outdir']}/pairs.train.withE.jsonl", df_tr.to_dict(orient="records"))
        write_jsonl(f"{C['outdir']}/pairs.val.withE.jsonl",   df_va.to_dict(orient="records"))
        write_jsonl(f"{C['outdir']}/pairs.test.withE.jsonl",  df_te.to_dict(orient="records"))

    print("[done] saved:", f"{C['outdir']}/post_train_config.json")
    print("[embed-only] val:", best_va, " test:", embed_test)
    print("[logreg]      val:", best_logreg_va, " test:", logreg_test)

if __name__ == "__main__":
    main()