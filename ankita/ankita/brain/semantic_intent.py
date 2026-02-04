from brain.semantic_intent import SemanticIntentMatcher, SemanticMatch, semantic_classify


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]).strip() or "open chrome please"
    out = semantic_classify(q)
    print(out)
