from scoring.route_scoring import _resolve_contradictions


def test_contradictory_cctv_factors_are_merged():
    positives = ["Strong CCTV coverage", "Police station nearby"]
    negatives = ["Limited CCTV coverage", "Road classified as isolated"]
    pos, neg = _resolve_contradictions(positives, negatives)

    assert "Strong CCTV coverage" not in pos
    assert "Limited CCTV coverage" not in neg
    assert any("CCTV coverage varies" in n for n in neg)
    assert "Police station nearby" in pos
    assert "Road classified as isolated" in neg


def test_no_overlap_leaves_factors_untouched():
    positives = ["Well-lit segment", "Police station nearby"]
    negatives = ["Road classified as isolated"]
    pos, neg = _resolve_contradictions(positives, negatives)
    assert pos == positives
    assert neg == negatives


def test_multiple_overlapping_topics_all_resolved():
    positives = ["Strong CCTV coverage", "Well-lit segment"]
    negatives = ["Limited CCTV coverage", "Poor street lighting"]
    pos, neg = _resolve_contradictions(positives, negatives)
    assert pos == []
    assert len(neg) == 2
    joined = " ".join(neg)
    assert "CCTV coverage varies" in joined
    assert "Street lighting varies" in joined


def test_empty_lists_dont_crash():
    pos, neg = _resolve_contradictions([], [])
    assert pos == [] and neg == []
