"""Maintenance and monitoring: decay detection and append-only audit logs.

Four alert checks run after each re-crawl to detect data degradation:
extraction regression, corpus shape drift, volume anomaly, and stale gold.
Silence is the success condition.
"""

from __future__ import annotations
