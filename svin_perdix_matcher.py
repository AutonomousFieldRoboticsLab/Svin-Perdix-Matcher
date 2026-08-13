"""Synchronize SVIn depth data with a Perdix dive-computer export."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from sklearn.linear_model import LinearRegression

SAMPLE_STEP_SECONDS = 0.1
FEET_TO_METERS = 0.3048


@dataclass(frozen=True)
class DepthSeries:
    """A depth series whose time values are seconds from its first sample."""

    time: np.ndarray
    depth: np.ndarray
    initial_timestamp: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match SVIn depth measurements to a Perdix dive-computer export."
    )
    parser.add_argument("perdix_csv", type=Path, help="Path to the Perdix CSV file")
    parser.add_argument("svin_txt", type=Path, help="Path to the SVIn text file")
    parser.add_argument("output_path", type=Path, help="Directory for generated files")
    parser.add_argument(
        "perdix_unit",
        choices=("m", "ft"),
        help="Depth unit used by the Perdix export",
    )
    return parser.parse_args()


def require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{description} does not exist or is not a file: {path}")


def parse_utc_timestamp(value: str) -> float:
    parsed = datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p")
    return parsed.replace(tzinfo=timezone.utc).timestamp()


def load_perdix(path: Path, unit: str) -> DepthSeries:
    frame = pd.read_csv(path)
    time_unit = str(frame["Dive Number"].iloc[1]).lower()
    elapsed = frame["Dive Number"].iloc[2:].to_numpy(dtype=float)

    if "ms" in time_unit:
        elapsed /= 1_000.0
    elif "sec" not in time_unit:
        raise ValueError(f"Unsupported Perdix time unit: {time_unit!r}")

    start_timestamp = parse_utc_timestamp(frame["Start Date"].iloc[0])
    end_timestamp = parse_utc_timestamp(frame["End Date"].iloc[0])
    absolute_time = start_timestamp + elapsed
    depth = -frame["GF Minimum"].iloc[2:].to_numpy(dtype=float)
    if unit == "ft":
        depth *= FEET_TO_METERS

    valid = absolute_time < end_timestamp
    if not np.any(valid):
        raise ValueError("The Perdix export has no samples before its end time")

    absolute_time = absolute_time[valid]
    return DepthSeries(absolute_time - absolute_time[0], depth[valid], absolute_time[0])


def load_svin(path: Path) -> DepthSeries:
    frame = pd.read_csv(path, sep=r"\s+")
    timestamps = frame["#timestamp"].to_numpy(dtype=float)
    depth = frame["tz"].to_numpy(dtype=float)
    if timestamps.size < 2:
        raise ValueError("The SVIn file must contain at least two samples")
    return DepthSeries(timestamps - timestamps[0], depth, timestamps[0])


def save_comparison_plot(
    first: DepthSeries,
    second: DepthSeries,
    path: Path,
    title: str,
) -> None:
    fig, first_axis = plt.subplots()
    first_axis.plot(first.time / 60, first.depth, "b-", label="Perdix")
    first_axis.set_xlabel("Time [min]")
    first_axis.set_ylabel("Depth (Perdix) [m]", color="b")
    first_axis.tick_params(axis="y", labelcolor="b")

    second_axis = first_axis.twinx()
    second_axis.plot(second.time / 60, second.depth, "r-", label="SVIn2")
    second_axis.set_ylabel("Depth (SVIn2) [m]", color="r")
    second_axis.tick_params(axis="y", labelcolor="r")

    lines = first_axis.lines + second_axis.lines
    first_axis.legend(lines, [line.get_label() for line in lines], loc="upper left")
    first_axis.set_title(title)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def find_time_shift(
    perdix: DepthSeries,
    svin: DepthSeries,
    step: float = SAMPLE_STEP_SECONDS,
) -> float:
    perdix_end = float(perdix.time[-1])
    svin_end = float(svin.time[-1])
    if perdix_end < svin_end:
        raise ValueError("The Perdix recording must be at least as long as the SVIn recording")

    # Exclude the upper bound so floating-point rounding cannot place the final
    # grid value just beyond the interpolation domain.
    perdix_grid = np.arange(0.0, perdix_end, step)
    svin_grid = np.arange(0.0, svin_end, step)
    perdix_depth = interp1d(perdix.time, perdix.depth)(perdix_grid)
    svin_depth = interp1d(svin.time, svin.depth)(svin_grid)

    candidate_count = perdix_depth.size - svin_depth.size + 1
    errors = np.empty(candidate_count)
    for index in range(candidate_count):
        residual = perdix_depth[index : index + svin_depth.size] - svin_depth
        errors[index] = np.var(np.abs(residual))
    return float(np.argmin(errors) * step)


def match_depths(
    perdix: DepthSeries, svin: DepthSeries, shift: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    shifted_time = svin.time + shift
    overlap = (perdix.time >= shifted_time[0]) & (perdix.time <= shifted_time[-1])
    matched_time = perdix.time[overlap]
    if matched_time.size < 2:
        raise ValueError("The shifted recordings do not have enough overlapping samples")

    svin_interpolator = interp1d(shifted_time, svin.depth, bounds_error=True)
    return matched_time, perdix.depth[overlap], svin_interpolator(matched_time)


def save_matched_plot(
    time: np.ndarray,
    perdix_depth: np.ndarray,
    svin_depth: np.ndarray,
    path: Path,
) -> None:
    matched_perdix = DepthSeries(time, perdix_depth, 0.0)
    matched_svin = DepthSeries(time, svin_depth, 0.0)
    save_comparison_plot(matched_perdix, matched_svin, path, "Time-shifted Result")


def fit_depth_regression(
    perdix_depth: np.ndarray, svin_depth: np.ndarray
) -> tuple[LinearRegression, np.ndarray]:
    features = svin_depth.reshape(-1, 1)
    model = LinearRegression().fit(features, perdix_depth)
    return model, model.predict(features)


def save_regression_plot(
    svin_depth: np.ndarray,
    perdix_depth: np.ndarray,
    prediction: np.ndarray,
    model: LinearRegression,
    path: Path,
) -> None:
    coefficient = float(model.coef_[0])
    intercept = float(model.intercept_)
    fig, axis = plt.subplots()
    axis.scatter(svin_depth, perdix_depth, color="blue", marker="+", label="data")
    order = np.argsort(svin_depth)
    axis.plot(svin_depth[order], prediction[order], color="red", label="regression")
    axis.set(title=f"y = {coefficient:.4f}x + {intercept:.4f}", xlabel="SVIn", ylabel="Perdix")
    axis.legend(loc="upper left")
    axis.grid(True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def save_final_plot(perdix: DepthSeries, svin: DepthSeries, path: Path) -> None:
    fig, axis = plt.subplots()
    axis.plot(perdix.time / 60, perdix.depth, "b-", label="Perdix")
    axis.plot(svin.time / 60, svin.depth, "r-", label="regressed_SVIn2")
    axis.set(
        title="Depth vs. Time for Perdix and Regressed SVIn2",
        xlabel="Time [min]",
        ylabel="Depth [m]",
    )
    axis.legend(loc="upper left")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def run(perdix_path: Path, svin_path: Path, output_path: Path, unit: str) -> None:
    require_file(perdix_path, "Perdix CSV")
    require_file(svin_path, "SVIn file")
    output_path.mkdir(parents=True, exist_ok=True)

    perdix = load_perdix(perdix_path, unit)
    svin = load_svin(svin_path)
    save_comparison_plot(perdix, svin, output_path / "original_data.png", "Original Data: Perdix vs. SVIn2")

    shift = find_time_shift(perdix, svin)
    shifted_svin = DepthSeries(svin.time + shift, svin.depth, svin.initial_timestamp)
    save_comparison_plot(
        perdix,
        shifted_svin,
        output_path / "shifted.png",
        f"Shifted Data: Perdix vs. SVIn2 [{shift:+.2f} s]",
    )

    matched_time, matched_perdix, matched_svin = match_depths(perdix, svin, shift)
    save_matched_plot(matched_time, matched_perdix, matched_svin, output_path / "interpolate.png")

    model, prediction = fit_depth_regression(matched_perdix, matched_svin)
    save_regression_plot(matched_svin, matched_perdix, prediction, model, output_path / "regression.png")

    calibrated_depth = model.predict(svin.depth.reshape(-1, 1))
    calibrated_svin = DepthSeries(shifted_svin.time, calibrated_depth, svin.initial_timestamp)
    save_final_plot(perdix, calibrated_svin, output_path / "final.png")

    result = pd.DataFrame(
        {
            "time_stamp": shifted_svin.time + perdix.initial_timestamp,
            "depth [m]": calibrated_depth,
        }
    )
    result.to_csv(output_path / "matched_svin.csv", index=False, float_format="%.5f")


def main() -> None:
    args = parse_args()
    try:
        run(args.perdix_csv, args.svin_txt, args.output_path, args.perdix_unit)
    except (FileNotFoundError, KeyError, ValueError) as error:
        raise SystemExit(f"Error: {error}") from error


if __name__ == "__main__":
    main()
