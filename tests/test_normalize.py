from scoring.normalize import clamp01, inverse, normalize_count, normalize_distance_inverse, weighted_mean


def test_clamp01_bounds():
    assert clamp01(-1) == 0.0
    assert clamp01(2) == 1.0
    assert clamp01(0.5) == 0.5


def test_inverse():
    assert inverse(0.0) == 1.0
    assert inverse(1.0) == 0.0


def test_normalize_count_saturates():
    assert normalize_count(0, 3) == 0.0
    assert normalize_count(3, 3) == 1.0
    assert normalize_count(10, 3) == 1.0


def test_normalize_distance_inverse():
    assert normalize_distance_inverse(0, 100, 1000) == 1.0
    assert normalize_distance_inverse(1000, 100, 1000) == 0.0
    mid = normalize_distance_inverse(550, 100, 1000)
    assert 0.4 < mid < 0.6


def test_weighted_mean_missing_data_lowers_confidence():
    score, confidence = weighted_mean([(1.0, 1.0, True), (0.0, 1.0, False)])
    assert score == 1.0
    assert confidence == 0.5


def test_weighted_mean_all_missing_returns_neutral_zero_confidence():
    score, confidence = weighted_mean([(1.0, 1.0, False), (0.0, 1.0, False)])
    assert score == 0.5
    assert confidence == 0.0
