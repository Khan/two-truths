import math


def ci_bounds(correct, n):
    # https://www.evanmiller.org/how-not-to-sort-by-average-rating.html
    z = 1.96  # 95% confidence interval
    correct = float(correct)
    n = float(n)
    p = correct / n
    denom = 1 + (z * z) / n
    center = p + (z * z) / (2 * n)
    err = z * math.sqrt(
        (p * (1 - p) + (z * z) / (4 * n)) / n)

    return (center - err) / denom, (center + err) / denom
