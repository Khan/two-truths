import math
from scipy.stats import norm


def ci_bounds(correct, n, ci=0.90):
    # https://www.evanmiller.org/how-not-to-sort-by-average-rating.html
    z = norm.ppf(1 - (1 - ci) / 2)  # two-sided
    correct = float(correct)
    n = float(n)
    p = correct / n
    denom = 1 + (z * z) / n
    center = p + (z * z) / (2 * n)
    err = z * math.sqrt(
        (p * (1 - p) + (z * z) / (4 * n)) / n)

    return (center - err) / denom, (center + err) / denom


def pvalue(correct, n):
    return norm.cdf(correct, loc=n/3., scale=math.sqrt(n * 2/9.))
