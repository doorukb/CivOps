import random
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import simpy

from app.models import Incident, SimulationConfig, SimulationResult
from app.services.leap_arrivals import duration_multiplier, generate_calls
from app.services.rule_engine import evaluate_incident, load_rulebook


def build_scenario_rulebook(config: SimulationConfig) -> dict:
    rulebook = deepcopy(load_rulebook())

    rulebook["schedule"]["start_hour"] = config.start_hour
    rulebook["schedule"]["end_hour"] = config.end_hour

    if config.include_weekends:
        rulebook["schedule"]["weekdays"] = list(range(7))

    if config.include_noise_complaints:
        rulebook["eligible_call_types"].append("noise_complaint")

    return rulebook

def simulate_incidents(
    incidents: list[Incident],
    config: SimulationConfig,
    horizon_start: date | None = None,
    horizon_end: date | None = None,
    duration_multipliers: list[float] | None = None
) -> SimulationResult:
    """
    horizon_start/horizon_end are local dates, end exclusive. When given they fix
    the utilization denominator; otherwise it spans the first to last call.
    duration_multipliers[i] scales the duration of incidents[i].
    """

    rulebook = build_scenario_rulebook(config)
    env = simpy.Environment()
    teams = simpy.Resource(env, capacity=config.teams)

    metrics = {
        "eligible_calls": 0,
        "handled_calls": 0,
        "missed_off_duty": 0,
        "missed_busy": 0,
        "busy_team_minutes": 0.0
    }

    if duration_multipliers is None:
        duration_multipliers = [1.0] * len(incidents)
    elif len(duration_multipliers) != len(incidents):
        raise ValueError("duration_multipliers must match incidents")

    # Sort calls by arrival time, each with its own duration multiplier
    sorted_pairs = sorted(
        zip(incidents, duration_multipliers, strict=True),
        key=lambda pair: pair[0].timestamp
    )
    sorted_incidents = [incident for incident, _ in sorted_pairs]

    if not sorted_incidents:
        return SimulationResult(
            total_calls=0,
            eligible_calls=0,
            handled_calls=0,
            missed_off_duty=0,
            missed_busy=0,
            utilization=0.0
        )

    start_time = sorted_incidents[0].timestamp

    def handle_call(request, duration, arrival_timestamp):
        try:
            yield request

            metrics["handled_calls"] += 1

            # Calculate minutes remaining in this work shift
            timezone = ZoneInfo(rulebook["schedule"]["timezone"])
            local_arrival = arrival_timestamp.astimezone(timezone)

            shift_end = (
                datetime.combine(
                    local_arrival.date(),
                    time.min,
                    tzinfo=timezone
                )
                + timedelta(hours=config.end_hour)
            )

            remaining_shift_minutes = max(
                0,
                (shift_end - local_arrival).total_seconds() / 60
            )

            # Count only busy time within scheduled hours
            metrics["busy_team_minutes"] += min(
                duration,
                remaining_shift_minutes
            )

            yield env.timeout(duration)

        finally:
            teams.release(request)

    def arrival_process():
        previous_minutes = 0.0

        for incident, multiplier in sorted_pairs:
            minutes = (
                incident.timestamp - start_time
            ).total_seconds() / 60

            yield env.timeout(minutes - previous_minutes)
            previous_minutes = minutes

            decision = evaluate_incident(
                incident,
                rulebook=rulebook
            )

            if decision.eligible is not True:
                continue

            metrics["eligible_calls"] += 1

            if decision.on_duty is False:
                metrics["missed_off_duty"] += 1
                continue

            # Reserve capacity immediately at arrival time
            if teams.count >= teams.capacity:
                metrics["missed_busy"] += 1
                continue

            request = teams.request()

            env.process(
                handle_call(
                    request,
                    config.average_duration_minutes * multiplier,
                    incident.timestamp
                )
            )

    env.process(arrival_process())
    env.run()

    # Calculate scheduled capacity across the simulation period
    timezone = ZoneInfo(rulebook["schedule"]["timezone"])

    if horizon_start is not None and horizon_end is not None:
        first_day = horizon_start
        last_day = horizon_end - timedelta(days=1)
    else:
        first_day = sorted_incidents[0].timestamp.astimezone(timezone).date()
        last_day = sorted_incidents[-1].timestamp.astimezone(timezone).date()

    scheduled_days = 0
    current_day = first_day

    while current_day <= last_day:
        if current_day.weekday() in rulebook["schedule"]["weekdays"]:
            scheduled_days += 1

        current_day += timedelta(days=1)

    hours_per_day = config.end_hour - config.start_hour

    capacity_minutes = (
        scheduled_days
        * hours_per_day
        * 60
        * config.teams
    )

    utilization = (
        metrics["busy_team_minutes"] / capacity_minutes
        if capacity_minutes > 0 else 0.0
    )

    return SimulationResult(
        total_calls=len(incidents),
        eligible_calls=metrics["eligible_calls"],
        handled_calls=metrics["handled_calls"],
        missed_off_duty=metrics["missed_off_duty"],
        missed_busy=metrics["missed_busy"],
        utilization=utilization
    )

ASSUMPTIONS = [
    "Call arrival times are fitted to coverage totals, not copied from LEAP's tables, and volume is about 47 calls per week.",
    "Every eligible on-duty call goes to CRESS, so results are a ceiling on what CRESS could take, not what dispatch sends today (public testimony says roughly half a dozen a month).",
    "There is no queue or travel time: a call that arrives when every team is busy is missed, not held.",
    "Utilization counts only dispatch-sent calls; CRESS's direct work is not modeled.",
    "Each handled call counts as one police call avoided.",
    "Call length is the configured average times a random multiplier with mean about 1 and spread set by duration_cv.",
]

METRICS = (
    "calls_per_week", "share_handled", "missed_off_duty", "missed_busy", "utilization"
)


def _summarize(values) -> dict[str, float]:
    return {
        "mean": float(np.mean(values)),
        "p10": float(np.percentile(values, 10)),
        "p90": float(np.percentile(values, 90)),
    }


def run_comparison(
    baseline: SimulationConfig,
    scenario: SimulationConfig,
    replications: int = 50,
    seed: int = 42,
    calls_per_week: float = 47,
    horizon_weeks: int = 4,
    duration_cv: float = 0.5
) -> dict:
    """
    Run both configs on the same generated calls, once per replication.

    calls_per_week is handled calls per week (police calls avoided); missed and
    share_handled are per horizon. share_handled is handled / eligible, and
    "difference" is scenario minus baseline within each replication.
    """
    start = date(2026, 1, 5)  # a Monday
    end = start + timedelta(weeks=horizon_weeks)
    samples = {name: {m: [] for m in METRICS} for name in ("baseline", "scenario")}

    for replication in range(replications):
        rng = random.Random(seed + replication)
        calls = generate_calls(rng, start, horizon_weeks, calls_per_week)
        multipliers = [duration_multiplier(rng, duration_cv) for _ in calls]

        for name, config in (("baseline", baseline), ("scenario", scenario)):
            result = simulate_incidents(
                calls, config, start, end, multipliers
            )
            row = samples[name]
            row["calls_per_week"].append(result.handled_calls / horizon_weeks)
            row["share_handled"].append(
                result.handled_calls / result.eligible_calls
                if result.eligible_calls else 0.0
            )
            row["missed_off_duty"].append(result.missed_off_duty)
            row["missed_busy"].append(result.missed_busy)
            row["utilization"].append(result.utilization)

    return {
        "replications": replications,
        "horizon_weeks": horizon_weeks,
        "baseline": {m: _summarize(samples["baseline"][m]) for m in METRICS},
        "scenario": {m: _summarize(samples["scenario"][m]) for m in METRICS},
        "difference": {
            m: _summarize(
                np.array(samples["scenario"][m]) - np.array(samples["baseline"][m])
            )
            for m in METRICS
        },
        "assumptions": ASSUMPTIONS,
    }
