import os
from typing import List, Optional

import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM


SUMMARY_MODEL_NAME = os.getenv("SEENIT_SUMMARY_MODEL", "google/flan-t5-small")

_tokenizer = None
_model = None


def _load_model():
    """
    Lazy-load FLAN-T5 model and tokenizer.
    Runs locally, no API key required.
    """
    global _tokenizer, _model

    if _tokenizer is None or _model is None:
        print(f"[SeenIt] loading summary model: {SUMMARY_MODEL_NAME}")
        _tokenizer = AutoTokenizer.from_pretrained(SUMMARY_MODEL_NAME)
        _model = AutoModelForSeq2SeqLM.from_pretrained(SUMMARY_MODEL_NAME)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model.to(device)

    return _tokenizer, _model


def summarize_whats_new(sentences: List[str]) -> Optional[str]:
    """
    Use FLAN-T5 to turn the most informative 'new' sentences
    into a short, readable paragraph.
    """
    print(f"[SeenIt] summarize_whats_new called with {len(sentences)} sentences")
    # Join sentences into a single short context
    text_parts = [s.strip() for s in sentences if s and s.strip()]
    if not text_parts:
        print("[SeenIt] summarize_whats_new: no text parts, returning None")
        return None

    # Limit total input length a bit to keep generation fast
    joined = " ".join(text_parts)
    if len(joined) > 1200:
        joined = joined[:1200]

    tokenizer, model = _load_model()
    device = next(model.parameters()).device

    prompt = (
        "You are helping a reader understand what is NEW in a news article "
        "compared to earlier articles they have already read. "
        "Only describe the new information, in 2–3 concise sentences.\n\n"
        f"{joined}"
    )

    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=512,
    ).to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=96,
            num_beams=4,
            early_stopping=True,
        )

    summary = tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
    return summary or None

