# SVIn–Perdix Matcher

Synchronizes an SVIn trajectory with a Perdix dive-computer export and calibrates
the SVIn depth measurements against the Perdix depth reference.

The script finds the time offset between the recordings, interpolates the SVIn
trajectories at the Perdix sample times, fits a linear depth correction, and
writes the corrected SVIn data and diagnostic plots to an output directory.

## Requirements

- Python 3.9 or newer
- NumPy
- pandas
- Matplotlib
- SciPy
- scikit-learn
## Installation
```
git clone https://github.com/AutonomousFieldRoboticsLab/Svin-Perdix-Matcher
```

Install the Python dependencies with:

```bash
sudo apt install python3.*-venv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Input files

### Perdix CSV

Use the CSV exported by the Perdix dive computer. The matcher expects the
export's metadata rows and these columns:

- `Dive Number` for elapsed time and its unit
- `GF Minimum` for depth samples
- `Start Date` and `End Date` for recording bounds

The depth unit must be supplied separately as either `m` or `ft`.

### SVIn text file

The SVIn file must be whitespace-delimited and contain:

- `#timestamp` with Unix timestamps in seconds
- `tz` with depth measurements

## Usage

```text
python3 svin_perdix_matcher.py PERDIX_CSV SVIN_TXT OUTPUT_DIRECTORY {m,ft}
```

For example, using the included sample data:

```bash
python3 svin_perdix_matcher.py \
  data/CatacombsPerdix.csv \
  data/svin_CenterSynced.txt \
  output \
  ft
```

The output directory is created automatically, including missing parent
directories.

## Example result

Running the command above against `svin_CenterSynced.txt` produced a
581.8-second time shift. Over the matching portion of the recordings, the
linear calibration had an RMSE of 0.119 m and an R² of 0.988.

| Original recordings | Time-aligned and depth-calibrated result |
| --- | --- |
| ![Original Perdix and SVIn depths](examples/original_data.png) | ![Example time-aligned and depth-calibrated Perdix and SVIn depths](examples/example_result.png) |

Generated run artifacts belong in `output/`, which is intentionally ignored by
Git. The representative before-and-after figures above are retained in
`examples/`.

## Outputs

The script creates:

| File | Description |
| --- | --- |
| `matched_svin.csv` | Corrected SVIn timestamps and depths in meters |
| `original_data.png` | Original Perdix and SVIn recordings |
| `shifted.png` | Recordings after applying the calculated time offset |
| `interpolate.png` | Overlapping data after SVIn interpolation |
| `regression.png` | Linear depth-calibration fit |
| `final.png` | Perdix data and the synchronized, calibrated SVIn result |

The CSV contains two columns:

- `time_stamp`: Unix timestamp in seconds
- `depth [m]`: calibrated depth in meters

## Notes

- Perdix timestamps are interpreted as UTC.
- The Perdix recording must be at least as long as the SVIn recording.
- The time offset is searched at 0.1-second resolution.
- Existing files with the output names above are overwritten.
