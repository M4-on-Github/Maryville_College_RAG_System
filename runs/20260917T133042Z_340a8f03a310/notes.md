# tau-calibration / arm: t21-ce-maxp-gate

Task 21, pre-registered in decisions/0009. Frozen retrieval (decisions/0007). Label: in scope and all_golds_retrieved@5. Signal: cross-encoder/ms-marco-MiniLM-L-6-v2 raw logits, MaxP over 1000-char windows; dense cosine as exploratory reference. Methods: raw (reference), normalized (z vs 20-pool), margin (s1-s2), percentile (vs 100 null passages, seed 42). 5-fold CV by slice, seed 42, floor 0.95. Zero generation quota.
