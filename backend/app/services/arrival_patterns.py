import calendar
import random
from datetime import datetime
from zoneinfo import ZoneInfo

# ASSUMPTION, NOT LEAP DATA: illustrative relative call volume by hour of
# day (index 0-23, local time) and day of week (0 = Monday). Shaped to look
# like public-safety demand (quiet overnight, busiest late afternoon and
# evening). Replace with LEAP's tables when transcribed; the synthetic
# audit and the simulator should both read from here.
HOUR_WEIGHTS = [
    3, 2, 1.5, 1, 1, 1.5, 2, 2.5,          # 00-07
    3, 3.5, 4, 4.5, 5, 5, 5.5, 5.5,        # 08-15
    6, 7, 7.5, 8, 8, 7, 6, 4.5,            # 16-23
]
DAY_WEIGHTS = [1.0, 1.0, 1.0, 1.0, 1.0, 1.2, 1.1]  # Mon..Sun

TIMEZONE = ZoneInfo("America/New_York")


def random_timestamp(rng: random.Random, year: int, month: int) -> datetime:
    """Draw a local timestamp in the month using the hour/day weights."""
    days = [
        day for day in range(1, calendar.monthrange(year, month)[1] + 1)
    ]
    day = rng.choices(
        days,
        weights=[
            DAY_WEIGHTS[datetime(year, month, d).weekday()] for d in days
        ],
    )[0]
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]

    return datetime(
        year, month, day, hour, rng.randrange(60), tzinfo=TIMEZONE
    )
