import collections

def tokenize_title(t):
    if not t: return []
    t = t.lower()
    buf = []
    for ch in t:
        buf.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    toks = [tok for tok in "".join(buf).split() if len(tok) > 1]
    return toks

def jaccard(a_tokens, b_tokens):
    A, B = set(a_tokens), set(b_tokens)
    if not A and not B:
        return 0.0
    return len(A & B) / max(1, len(A | B))

def hash32(s):
    h = 2166136261
    for c in s.encode("utf-8", errors="ignore"):
        h ^= c
        h = (h * 16777619) & 0xFFFFFFFF
    return h

def hash64(s):
    a = hash32(s)
    b = hash32(s + "#")
    return (a << 32) | b

def simhash64_from_text(text):
    toks = tokenize_title(text)
    if not toks:
        return 0
    weights = collections.Counter(toks)  # simple TF
    bits = [0] * 64
    for tok, w in weights.items():
        hv = hash64(tok)
        for i in range(64):
            if (hv >> i) & 1:
                bits[i] += w
            else:
                bits[i] -= w
    out = 0
    for i in range(64):
        if bits[i] > 0:
            out |= (1 << i)
    return out

def hamming64(a, b):
    x = a ^ b
    cnt = 0
    while x:
        cnt += x & 1
        x >>= 1
    return cnt