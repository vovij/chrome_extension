import os, json, math, random, time
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from collections import Counter, defaultdict
import re

# =========================
# Configuration - Using Original Files (Fair Comparison)
# =========================
CONFIG = {
    # Use original files from your out_wcep_posttrain directory (WITHOUT MiniLM preprocessing)
    "articles_test":  "backend/out_wcep_posttrain/articles.test.jsonl",
    "articles_train": "backend/out_wcep_posttrain/articles.train.jsonl", 
    "articles_val":   "backend/out_wcep_posttrain/articles.val.jsonl",
    "pairs_test":     "backend/out_wcep_posttrain/pairs.test.jsonl",
    "pairs_train":    "backend/out_wcep_posttrain/pairs.train.jsonl",
    "pairs_val":      "backend/out_wcep_posttrain/pairs.val.jsonl",
    
    "outdir": "fair_model_comparison_results",
    "seed": 2026,
    "max_text_len": 2000,
    
    # Testing parameters
    "use_sample_for_speed": False,  # Set True for faster testing with smaller sample
    "sample_size": 500,
}

# =========================
# Data Loading Functions
# =========================
def load_jsonl(path: str) -> List[dict]:
    """Load JSONL file"""
    data = []
    if not os.path.exists(path):
        print(f"[warn] file not found: {path}")
        return data
        
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    
    print(f"[load] {len(data)} items from {os.path.basename(path)}")
    return data

def prepare_clean_dataset():
    """Load original dataset without MiniLM preprocessing"""
    print("🔄 Loading ORIGINAL WCEP dataset (no MiniLM preprocessing)...")
    
    # Load articles
    articles_test = load_jsonl(CONFIG["articles_test"])
    articles_train = load_jsonl(CONFIG["articles_train"])
    articles_val = load_jsonl(CONFIG["articles_val"])
    
    # Create articles dict
    all_articles = {}
    for articles in [articles_test, articles_train, articles_val]:
        for art in articles:
            all_articles[art["id"]] = art
    
    # Load pairs WITHOUT E values (clean comparison)
    pairs_test = load_jsonl(CONFIG["pairs_test"])
    pairs_train = load_jsonl(CONFIG["pairs_train"]) 
    pairs_val = load_jsonl(CONFIG["pairs_val"])
    
    # Sample for speed if requested
    if CONFIG["use_sample_for_speed"]:
        sample_size = CONFIG["sample_size"]
        pairs_test = pairs_test[:sample_size]
        print(f"[sample] using {sample_size} pairs for quick testing")
    
    print(f"📊 Clean dataset summary:")
    print(f"   Articles: {len(all_articles)}")
    print(f"   Test pairs: {len(pairs_test)}")
    print(f"   Train pairs: {len(pairs_train)}")
    print(f"   Val pairs: {len(pairs_val)}")
    
    return all_articles, pairs_test, pairs_train, pairs_val

def create_text_pairs_from_articles(articles: Dict[str, dict], pairs: List[dict]) -> Tuple[List[Tuple[str, str]], List[int], List[dict]]:
    """Convert article pairs to text pairs for model testing"""
    text_pairs = []
    labels = []
    metadata = []
    
    missing_count = 0
    for pair in pairs:
        id1, id2 = pair["id1"], pair["id2"]
        
        if id1 in articles and id2 in articles:
            art1 = articles[id1]
            art2 = articles[id2]
            
            # Create full text (title + content) - same as your post-train_MiniLM.py
            title1 = art1.get('title', '')
            text1 = art1.get('text', '') or art1.get('content', '')
            merged1 = (title1 + "\n\n" + text1[:CONFIG['max_text_len']]).strip()
            
            title2 = art2.get('title', '')
            text2 = art2.get('text', '') or art2.get('content', '')
            merged2 = (title2 + "\n\n" + text2[:CONFIG['max_text_len']]).strip()
            
            text_pairs.append((merged1, merged2))
            labels.append(pair["label"])
            metadata.append(pair)  # Original metadata (U, T, Sh, etc.)
        else:
            missing_count += 1
    
    if missing_count > 0:
        print(f"[warn] {missing_count} pairs skipped due to missing articles")
    
    return text_pairs, labels, metadata

# =========================
# Model Implementations (Fair Comparison)
# =========================
def minilm_fresh_computation(text_pairs: List[Tuple[str, str]]) -> Tuple[List[float], str]:
    """Compute MiniLM embeddings from scratch (fair comparison)"""
    try:
        from sentence_transformers import SentenceTransformer
        import torch
        
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[minilm] loading model on {device}")
        
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device=device)
        
        similarities = []
        batch_size = 16 if device == "cuda" else 8
        
        print(f"[minilm] processing {len(text_pairs)} pairs in batches of {batch_size}")
        
        for i in range(0, len(text_pairs), batch_size):
            batch = text_pairs[i:i+batch_size]
            
            texts1 = [pair[0] for pair in batch]
            texts2 = [pair[1] for pair in batch]
            
            # Encode exactly like post-train_MiniLM.py
            emb1 = model.encode(texts1, convert_to_numpy=True, normalize_embeddings=True, 
                              show_progress_bar=False, batch_size=batch_size)
            emb2 = model.encode(texts2, convert_to_numpy=True, normalize_embeddings=True,
                              show_progress_bar=False, batch_size=batch_size)
            
            # Calculate cosine similarities
            for j in range(len(batch)):
                sim = np.dot(emb1[j], emb2[j]) / (np.linalg.norm(emb1[j]) * np.linalg.norm(emb2[j]))
                similarities.append(float(sim))
            
            if i % (batch_size * 10) == 0:
                print(f"[minilm] {i}/{len(text_pairs)} pairs processed")
        
        return similarities, "Fresh MiniLM-L6-v2 computation (sentence-transformers)"
        
    except ImportError:
        print("[warn] sentence-transformers not available, skipping MiniLM")
        return [0.5] * len(text_pairs), "MiniLM unavailable (install sentence-transformers)"
    except Exception as e:
        print(f"[error] MiniLM failed: {e}")
        return [0.5] * len(text_pairs), f"MiniLM error: {str(e)}"

def traditional_wcep_features(metadata: List[dict]) -> Tuple[List[float], str]:
    """Use original WCEP features (U, T, Sh) - your build_data_from_WCEP.py output"""
    similarities = []
    
    for pair in metadata:
        # Extract original features from your build_data_from_WCEP.py
        U = pair.get("U", 0.0)      # URL similarity 
        T = pair.get("T", 0.0)      # Title Jaccard
        Sh = pair.get("Sh", 0.0)    # SimHash similarity
        domain_same = pair.get("domain_same", 0.0)
        
        # Weighted combination (you can tune these)
        combined = 0.2 * U + 0.4 * T + 0.3 * Sh + 0.1 * domain_same
        similarities.append(combined)
    
    return similarities, "Traditional WCEP features (U + T + Sh + domain)"

def tfidf_full_comparison(text_pairs: List[Tuple[str, str]]) -> Tuple[List[float], str]:
    """Full TF-IDF comparison"""
    print("[tfidf] Processing full text comparison...")
    
    all_texts = []
    for text1, text2 in text_pairs:
        all_texts.extend([text1, text2])
    
    # High-quality TF-IDF parameters
    vectorizer = TfidfVectorizer(
        max_features=8000,
        stop_words='english',
        ngram_range=(1, 3),  # Include trigrams
        max_df=0.9,
        min_df=2,
        sublinear_tf=True  # Use sublinear TF scaling
    )
    
    print("[tfidf] Vectorizing...")
    tfidf_matrix = vectorizer.fit_transform(all_texts)
    
    print("[tfidf] Computing similarities...")
    similarities = []
    for i in range(0, len(all_texts), 2):
        sim = cosine_similarity(tfidf_matrix[i:i+1], tfidf_matrix[i+1:i+2])[0][0]
        similarities.append(float(sim))
        
        if (i // 2) % 500 == 0:
            print(f"[tfidf] {i//2}/{len(text_pairs)} completed")
    
    return similarities, f"TF-IDF with {len(vectorizer.get_feature_names_out())} features"

def jaccard_ngram_similarity(text_pairs: List[Tuple[str, str]]) -> Tuple[List[float], str]:
    """Jaccard similarity with n-grams (using your tokenization approach)"""
    
    def tokenize_text(text: str):
        # Same tokenization as your build_data_from_WCEP.py
        if not text: 
            return []
        text = text.lower()
        out = []
        buf = []
        for ch in text:
            if ch.isalnum() or ch.isspace():
                buf.append(ch)
            else:
                buf.append(" ")
        tokens = "".join(buf).split()
        return [tok for tok in tokens if len(tok) > 1]
    
    def get_ngrams(tokens, n=3):
        if len(tokens) < n:
            return set(tokens)
        return set([' '.join(tokens[i:i+n]) for i in range(len(tokens)-n+1)])
    
    similarities = []
    print(f"[jaccard] processing {len(text_pairs)} pairs...")
    
    for i, (text1, text2) in enumerate(text_pairs):
        tokens1 = tokenize_text(text1)
        tokens2 = tokenize_text(text2)
        
        # Combine word-level and trigram similarities
        words1, words2 = set(tokens1), set(tokens2)
        ngrams1 = get_ngrams(tokens1, 3)
        ngrams2 = get_ngrams(tokens2, 3)
        
        # Word Jaccard
        word_jaccard = len(words1 & words2) / len(words1 | words2) if words1 | words2 else 0.0
        
        # N-gram Jaccard  
        ngram_jaccard = len(ngrams1 & ngrams2) / len(ngrams1 | ngrams2) if ngrams1 | ngrams2 else 0.0
        
        # Combined similarity
        combined = 0.6 * word_jaccard + 0.4 * ngram_jaccard
        similarities.append(combined)
        
        if i % 500 == 0:
            print(f"[jaccard] {i}/{len(text_pairs)} completed")
    
    return similarities, "Jaccard similarity (words + 3-grams)"

def hybrid_traditional_tfidf(text_pairs: List[Tuple[str, str]], metadata: List[dict]) -> Tuple[List[float], str]:
    """Hybrid: Traditional features + TF-IDF"""
    
    # Get traditional features
    trad_sims, _ = traditional_wcep_features(metadata)
    
    # Get TF-IDF similarities (simplified for speed)
    print("[hybrid] computing TF-IDF component...")
    all_texts = []
    for text1, text2 in text_pairs:
        all_texts.extend([text1, text2])
    
    vectorizer = TfidfVectorizer(max_features=3000, stop_words='english', ngram_range=(1, 2))
    tfidf_matrix = vectorizer.fit_transform(all_texts)
    
    tfidf_sims = []
    for i in range(0, len(all_texts), 2):
        sim = cosine_similarity(tfidf_matrix[i:i+1], tfidf_matrix[i+1:i+2])[0][0]
        tfidf_sims.append(float(sim))
    
    # Combine both approaches
    hybrid_sims = []
    for trad, tfidf in zip(trad_sims, tfidf_sims):
        combined = 0.4 * trad + 0.6 * tfidf  # Weight towards TF-IDF
        hybrid_sims.append(combined)
    
    return hybrid_sims, "Hybrid: Traditional features + TF-IDF"

# =========================
# Evaluation Functions
# =========================
def evaluate_model_performance(similarities: List[float], labels: List[int], metadata: List[dict], model_name: str) -> dict:
    """Comprehensive evaluation"""
    
    # Find optimal threshold
    thresholds = np.linspace(0.0, 1.0, 101)
    best_metrics = {"f1": 0.0}
    
    for threshold in thresholds:
        predictions = [1 if s >= threshold else 0 for s in similarities]
        p, r, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
        
        if f1 > best_metrics["f1"]:
            best_metrics = {
                "threshold": float(threshold),
                "precision": float(p),
                "recall": float(r), 
                "f1": float(f1)
            }
    
    # Add AUC
    try:
        best_metrics["auc"] = float(roc_auc_score(labels, similarities))
    except:
        best_metrics["auc"] = 0.0
    
    # Cluster analysis
    same_cluster = [similarities[i] for i, m in enumerate(metadata) 
                   if m.get("cluster_id1") == m.get("cluster_id2")]
    diff_cluster = [similarities[i] for i, m in enumerate(metadata) 
                   if m.get("cluster_id1") != m.get("cluster_id2")]
    
    result = {
        "model_name": model_name,
        "test_pairs": len(similarities),
        "positive_pairs": sum(labels),
        "negative_pairs": len(labels) - sum(labels),
        **best_metrics,
        "same_cluster_avg": float(np.mean(same_cluster)) if same_cluster else 0.0,
        "diff_cluster_avg": float(np.mean(diff_cluster)) if diff_cluster else 0.0,
    }
    
    result["cluster_separation"] = result["same_cluster_avg"] - result["diff_cluster_avg"]
    
    return result

# =========================
# Main Comparison Function
# =========================
def run_fair_comparison():
    """Run fair model comparison without MiniLM preprocessing"""
    
    print("🔬 SeenIt FAIR Model Comparison (No Preprocessing)")
    print("=" * 60)
    
    # Create output directory
    Path(CONFIG["outdir"]).mkdir(parents=True, exist_ok=True)
    
    # Load clean dataset
    articles, pairs_test, pairs_train, pairs_val = prepare_clean_dataset()
    
    if not pairs_test:
        print("[error] No test data available")
        return
    
    # Prepare test data
    text_pairs, labels, metadata = create_text_pairs_from_articles(articles, pairs_test)
    
    print(f"\n🧪 Testing on {len(text_pairs)} pairs:")
    print(f"   Positive (similar): {sum(labels)} ({100*sum(labels)/len(labels):.1f}%)")
    print(f"   Negative (different): {len(labels) - sum(labels)} ({100*(len(labels)-sum(labels))/len(labels):.1f}%)")
    
    # Models to test (fair comparison)
    models = [
        ("MiniLM-Fresh", lambda: minilm_fresh_computation(text_pairs)),
        ("WCEP-Traditional", lambda: traditional_wcep_features(metadata)),
        ("TF-IDF-Full", lambda: tfidf_full_comparison(text_pairs)),
        ("Jaccard-NGrams", lambda: jaccard_ngram_similarity(text_pairs)),
        ("Hybrid-Trad+TFIDF", lambda: hybrid_traditional_tfidf(text_pairs, metadata)),
    ]
    
    results = []
    
    for model_name, model_func in models:
        print(f"\n🔍 Testing {model_name}...")
        
        start_time = time.time()
        try:
            similarities, description = model_func()
            inference_time = (time.time() - start_time) * 1000
            
            # Evaluate performance
            evaluation = evaluate_model_performance(similarities, labels, metadata, model_name)
            evaluation["inference_time_ms"] = inference_time
            evaluation["description"] = description
            
            results.append(evaluation)
            
            print(f"✅ {model_name} Results:")
            print(f"   F1: {evaluation['f1']:.3f}")
            print(f"   Precision: {evaluation['precision']:.3f}")
            print(f"   Recall: {evaluation['recall']:.3f}")
            print(f"   AUC: {evaluation['auc']:.3f}")
            print(f"   Cluster Sep: {evaluation['cluster_separation']:.3f}")
            print(f"   Time: {inference_time:.0f}ms")
            
        except Exception as e:
            print(f"❌ {model_name} failed: {e}")
            results.append({"model_name": model_name, "error": str(e), "f1": 0.0})
    
    # Save results
    output_file = os.path.join(CONFIG["outdir"], "fair_comparison_results.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    # Print final summary
    print_final_comparison_results(results)
    
    return results

def print_final_comparison_results(results: List[dict]):
    """Print comprehensive final results"""
    
    print("\n" + "=" * 80)
    print("🏆 FAIR MODEL COMPARISON RESULTS (No MiniLM Preprocessing)")
    print("=" * 80)
    
    valid_results = [r for r in results if "error" not in r]
    if not valid_results:
        print("❌ No valid results")
        return
    
    # Sort by F1 score
    valid_results.sort(key=lambda x: x.get("f1", 0), reverse=True)
    
    # Detailed results table
    print(f"{'Model':<20} {'F1':<6} {'Prec':<6} {'Rec':<6} {'AUC':<6} {'Sep':<6} {'Time(ms)':<10}")
    print("-" * 80)
    
    for r in valid_results:
        print(f"{r['model_name']:<20} {r['f1']:<6.3f} {r['precision']:<6.3f} "
              f"{r['recall']:<6.3f} {r['auc']:<6.3f} {r['cluster_separation']:<6.3f} "
              f"{r['inference_time_ms']:<10.0f}")
    
    print("=" * 80)
    
    # Winner and recommendations
    best = valid_results[0]
    print(f"\n🥇 WINNER: {best['model_name']}")
    print(f"   F1 Score: {best['f1']:.3f}")
    print(f"   Test Pairs: {best['test_pairs']:,}")
    
    # Deployment readiness
    if best['f1'] >= 0.85:
        status = "🚀 READY FOR PRODUCTION"
        advice = "Excellent performance, deploy immediately"
    elif best['f1'] >= 0.75:
        status = "✅ GOOD FOR MVP"  
        advice = "Solid performance, suitable for initial release"
    elif best['f1'] >= 0.65:
        status = "⚠️  NEEDS IMPROVEMENT"
        advice = "Acceptable but consider more training data"
    else:
        status = "❌ NOT READY"
        advice = "Requires significant improvement"
    
    print(f"\n{status}")
    print(f"💡 {advice}")
    
    # Speed analysis
    fast_models = [r for r in valid_results if r['inference_time_ms'] < 1000]
    if fast_models:
        fastest = min(fast_models, key=lambda x: x['inference_time_ms'])
        print(f"\n⚡ FASTEST GOOD MODEL: {fastest['model_name']} ({fastest['inference_time_ms']:.0f}ms)")

if __name__ == "__main__":
    run_fair_comparison()