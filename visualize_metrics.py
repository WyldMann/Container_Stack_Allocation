"""Plot yard JSONL metrics against period_end (Unix seconds).

Usage:
    python visualize_metrics.py
    python visualize_metrics.py output/existing_yard_metrics_JKT64.jsonl --show
    python visualize_metrics.py metrics.jsonl --output output/trends.png

Install the plotting dependency with:
    python -m pip install -r requirements-visualization.txt
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import warnings


WIB = timezone(timedelta(hours=7), "WIB")
DEFAULT_INPUT = Path(__file__).resolve().parent / "output" / "existing_yard_metrics_JKT74.jsonl"


def load_records(path):
    """Read records in time order, retaining repeated period_end timestamps."""
    records = []
    with Path(path).open(encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            timestamp = record.get("period_end")
            if timestamp is None:
                warnings.warn(f"{path}:{line_number}: skipped record without period_end")
                continue
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise ValueError(f"{path}:{line_number}: period_end must be Unix seconds")
            try:
                datetime.fromtimestamp(timestamp, WIB)
            except (ValueError, OverflowError, OSError) as error:
                raise ValueError(f"{path}:{line_number}: invalid period_end") from error
            observations = record.get("shifting_observations", [])
            if not isinstance(observations, list) or any(
                not isinstance(row, dict) for row in observations
            ):
                raise ValueError(f"{path}:{line_number}: shifting_observations must be a list of objects")
            records.append(record)
    if not records:
        raise ValueError(f"{path}: no records with a valid period_end")
    return sorted(records, key=lambda record: record["period_end"])


def percentage(value):
    """Missing metrics remain gaps; stored percentages are already scaled."""
    if value is None:
        return math.nan
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Expected a finite percentage or null, got {value!r}")
    return value


def plot_metrics(records):
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    records = sorted(records, key=lambda record: record["period_end"])
    times = [datetime.fromtimestamp(record["period_end"], WIB) for record in records]
    # Keep equipment series distinct while grouping charts by CY and block.
    observations = [
        {(record.get("cy_name", row.get("cy_name", "")),
          record.get("branch_code", row.get("branch_code", "")),
          row.get("block_code", ""), row.get("shifting_code", "")): row
         for row in record.get("shifting_observations", [])}
        for record in records
    ]
    keys = sorted({key for rows in observations for key in rows}, key=str)
    blocks = sorted({key[:3] for key in keys}, key=str)
    chart_count = 1 + len(blocks)
    figure, axes = plt.subplots(
        chart_count, 1, figsize=(12, 3.3 * chart_count), sharex=True,
        layout="constrained", squeeze=False,
    )
    axes = axes[:, 0]
    figure.suptitle("Yard metrics over time", fontsize=16)

    for field, label in (
        ("avg_shifting_percentage", "Average shifting"),
        ("avg_parameter_compliance", "Average parameter compliance"),
    ):
        axes[0].plot(times, [percentage(record.get(field)) for record in records],
                     marker="o", label=label)
    axes[0].set_title("Overall averages")

    for axis, block in zip(axes[1:], blocks):
        block_keys = [key for key in keys if key[:3] == block]
        for index, key in enumerate(block_keys):
            for field, label, color in (
                ("shifting_percentage", "Shifting", "tab:blue"),
                ("parameter_compliance", "Parameter compliance", "tab:orange"),
            ):
                values = [percentage(rows.get(key, {}).get(field)) for rows in observations]
                equipment = f" ({key[3]})" if key[3] else ""
                axis.plot(times, values, marker="o", color=color,
                          linestyle=("-", "--", ":", "-.")[index % 4],
                          label=label + equipment)
        branch = f" / {block[1]}" if block[1] else ""
        axis.set_title(f"{block[0]}{branch} / Block {block[2]}")

    for axis in axes:
        axis.set_ylim(0, 100)
        axis.yaxis.set_major_formatter(PercentFormatter(xmax=100))
        axis.grid(alpha=0.25)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9)
    locator = mdates.AutoDateLocator(tz=WIB)
    axes[-1].xaxis.set_major_locator(locator)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d\n%H:%M", tz=WIB))
    axes[-1].set_xlabel("Period end — WIB (UTC+7)")
    return figure


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, help="Image destination (default: input filename with .png)")
    parser.add_argument("--show", action="store_true", help="Also open the plot window")
    args = parser.parse_args()
    try:
        import matplotlib
        if not args.show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        parser.error("Install matplotlib: python -m pip install -r requirements-visualization.txt")
    output = args.output or args.input.with_suffix(".png")
    if output.resolve() == args.input.resolve():
        parser.error("Output must differ from the input JSONL file")
    try:
        records = load_records(args.input)
        figure = plot_metrics(records)
        output.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output, dpi=160, bbox_inches="tight")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Plotted {len(records)} records: {output.resolve()}")
    if args.show:
        plt.show()
    plt.close(figure)


if __name__ == "__main__":
    main()
