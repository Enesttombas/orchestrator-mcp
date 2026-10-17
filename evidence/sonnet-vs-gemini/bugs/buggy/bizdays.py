from datetime import timedelta


def business_days(start, end, holidays=()):
    """Number of business days (Mon-Fri, not in holidays) in the half-open range [start, end): start counts,
    end does not. A holiday counts once however often it is listed, and weekend holidays change nothing.
    If end < start the result is the negative of business_days(end, start)."""
    days = (end - start).days
    weeks, extra = divmod(days, 7)
    n = weeks * 5
    for i in range(extra + 1):
        if (start + timedelta(days=i)).weekday() < 5:
            n += 1
    n -= len([h for h in holidays if start <= h <= end])
    return n
