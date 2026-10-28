"""Explicit Unix benchmark for week-labelled operation reports."""

from dataclasses import dataclass

from .config_loader import ConfigurationError, _read_section


SECONDS_PER_WEEK = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class ShiftingPeriodSettings:
    benchmark_week: int
    benchmark_period_start: int

    def __post_init__(self):
        if type(self.benchmark_week) is not int or not 1 <= self.benchmark_week <= 53:
            raise ConfigurationError("shifting_period.benchmark_week must be an integer from 1 to 53.")
        if type(self.benchmark_period_start) is not int or self.benchmark_period_start < 0:
            raise ConfigurationError(
                "shifting_period.benchmark_period_start must be non-negative Unix seconds."
            )

    def boundaries(self, week):
        if type(week) is not int or not 1 <= week <= 53:
            raise ConfigurationError("The report week must be an integer from 1 to 53.")
        start = self.benchmark_period_start + (week - self.benchmark_week) * SECONDS_PER_WEEK
        if start < 0:
            raise ConfigurationError("The shifting benchmark produces a negative period start.")
        return start, start + SECONDS_PER_WEEK


def parse_shifting_period(document, *, required=False):
    if "shifting_period" not in document:
        if required:
            raise ConfigurationError("Configure [shifting_period] before recording weekly metrics.")
        return None
    section = _read_section(document, "shifting_period", {
        "benchmark_week", "benchmark_period_start",
    })
    return ShiftingPeriodSettings(
        section.get("benchmark_week"), section.get("benchmark_period_start"),
    )
