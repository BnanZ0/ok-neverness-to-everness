# ============================================================================
# Spectral-fingerprint dodge/counter detection.
#
# The algorithm (spectral peak constellation hashing + matched-filter
# verification) is ported from the NTE-Auto-Skill-Combo project's reference
# Python implementation (scripts/analyze_dodge_match.py and
# scripts/simulate_dodge_runtime.py), itself a faithful mirror of that
# project's Rust detector (src/dodge/fingerprint/*).
#
# Ported and adapted for streaming, callback-driven, multi-template detection
# inside ok-nte.
# ============================================================================
