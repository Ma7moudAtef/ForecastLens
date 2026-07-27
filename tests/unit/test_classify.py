import numpy as np

from core.analyze.classify import PatternClass, adi_cv2, classify


def test_smooth():
    y = np.array([10.0, 11, 9, 10, 10, 11, 9, 10])
    cls, adi, cv2 = classify(y)
    assert cls is PatternClass.SMOOTH
    assert adi == 1.0 and cv2 < 0.49


def test_erratic():
    y = np.array([1.0, 30, 2, 40, 1, 35, 2, 38])  # every period, wild sizes
    cls, adi, cv2 = classify(y)
    assert cls is PatternClass.ERRATIC
    assert adi < 1.32 and cv2 >= 0.49


def test_intermittent():
    y = np.array([10.0, 0, 0, 10, 0, 0, 10, 0, 0, 10])  # regular gaps, stable size
    cls, adi, cv2 = classify(y)
    assert cls is PatternClass.INTERMITTENT
    assert adi >= 1.32 and cv2 < 0.49


def test_lumpy():
    y = np.array([1.0, 0, 0, 50, 0, 0, 2, 0, 0, 60])
    cls, adi, cv2 = classify(y)
    assert cls is PatternClass.LUMPY
    assert adi >= 1.32 and cv2 >= 0.49


def test_too_short():
    assert classify(np.array([1.0, 2, 3]))[0] is PatternClass.TOO_SHORT


def test_all_zero_is_too_short():
    assert classify(np.zeros(12))[0] is PatternClass.TOO_SHORT


def test_adi_counts_gap_zeros():
    adi, _ = adi_cv2(np.array([5.0, 0, 5, 0, 5, 0]))
    assert adi == 2.0


def test_boundary_values():
    # ADI exactly 1.32 is intermittent (>= threshold); CV2 exactly 0.49 erratic
    y = np.array([1.0] * 25 + [0.0] * 8)  # 33/25 = 1.32
    cls, adi, _ = classify(y)
    assert abs(adi - 1.32) < 1e-9
    assert cls is PatternClass.INTERMITTENT
