from datetime import timedelta


def business_days(start, end, holidays=()):
    """Number of business days (Mon-Fri, not in holidays) in the half-open range [start, end): start counts,
    end does not. A holiday counts once however often it is listed, and weekend holidays change nothing.
    If end < start the result is the negative of business_days(end, start)."""
    if end < start:
        return -business_days(end, start, holidays)
    hol = set(holidays)
    n, d = 0, start
    while d < end:
        if d.weekday() < 5 and d not in hol:
            n += 1
        d += timedelta(days=1)
    return n
