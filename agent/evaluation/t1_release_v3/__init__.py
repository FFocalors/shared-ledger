"""T1 release-v3: explicit conversion of the frozen v2 candidate to the
frozen offline protocol v1.1.0 canonical profile.

The v2 candidate and every v2 receipt stay byte-identical.  This package
produces a *new* versioned preparation, as required by the dataset
applicability policy entry ``legacy-t1-release-v2`` (conversion_candidate,
explicit_conversion + new_source_freeze + new_split + replay_and_review).
"""
