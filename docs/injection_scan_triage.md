# T37 triage of docs/injection_scan.md (hand-checked 2026-09-24)

Scanner: `scripts/scan_corpus_injection.py` (patterns fixed before the first run;
report regenerates byte-identically). 3237 chunks.

- override, system_marker, reveal, llm_address, encoded_blob, hidden_unicode: **0 hits**.
- role_change, 7 hits: all benign English ("act as a virtual bulletin board",
  "act as a cultural ambassador", "You are now assigned for next year", and similar).
- exfil_or_command, 30 hits: all ordinary contact instructions ("please email us at
  ...@maryvillecollege.edu"). 5 name a non-college address or an unrelated email
  mention (a choir contact on gmail, a library chat link, "Today@MC"); none tells a reader
  or a model to send anything anywhere beyond contacting the office.

**Result: 37 candidates, 0 real injection attempts.** Limits: the patterns are English
regexes over the crawled text only, so paraphrased, non-English, or image-borne
instructions would not be caught, and the crawl is a September 2026 snapshot
(a re-crawl can add text). This is evidence about this snapshot, not a guarantee.
