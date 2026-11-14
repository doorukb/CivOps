import random
import simpy

from app.models import SimulationConfig, SimulationResult
from copy import deepcopy
from app.models import Incident
from app.services.rule_engine import evaluate_incident, load_rulebook
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def simulate_call(env, teams, duration, metrics):
    # If every team is occupied, record a missed call
    if teams.count >= teams.capacity:
        metrics["missed_busy"] += 1
        return

    # Otherwise, occupy a team
    with teams.request() as request:
        yield request

        metrics["handled_calls"] += 1

        # Time spent responding
        yield env.timeout(duration)

def run_simulation(
    config: SimulationConfig,
    call_times: list[float],
    durations: list[float]
) -> SimulationResult:

    env = simpy.Environment()
    teams = simpy.Resource(env, capacity=config.teams)

    metrics = {
        "handled_calls": 0,
        "missed_busy": 0,
        "busy_team_minutes": 0.0
    }

    def arrival_process():
        previous_time = 0.0

        for arrival_time, duration in zip(call_times, durations):
            yield env.timeout(arrival_time - previous_time)
            previous_time = arrival_time

            env.process(
                simulate_call(env, teams, duration, metrics)
            )

    env.process(arrival_process())
    env.run()

    total_calls = len(call_times)

    return SimulationResult(
        total_calls=total_calls,
        eligible_calls=total_calls,
        handled_calls=metrics["handled_calls"],
        missed_off_duty=0,
        missed_busy=metrics["missed_busy"],
        utilization=0.0
    )

def build_scenario_rulebook(config: SimulationConfig) -> dict:
    rulebook = deepcopy(load_rulebook())

    rulebook["schedule"]["start_hour"] = config.start_hour
    rulebook["schedule"]["end_hour"] = config.end_hour

    if config.include_weekends:
        rulebook["schedule"]["weekdays"] = list(range(7))

    return rulebook

def simulate_incidents(
    incidents: list[Incident],
    config: SimulationConfig
) -> SimulationResult:

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

    # Sort calls by arrival time
    sorted_incidents = sorted(
        incidents,
        key=lambda incident: incident.timestamp
    )

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

        for incident in sorted_incidents:
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
                    config.average_duration_minutes,
                    incident.timestamp
                )
            )

    env.process(arrival_process())
    env.run()

    # Calculate scheduled capacity across the simulation period
    timezone = ZoneInfo(rulebook["schedule"]["timezone"])

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