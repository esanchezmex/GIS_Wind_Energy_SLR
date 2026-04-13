# Filter wind farms from raw data and save the result.
from pathlib import Path

import pandas as pd

INPUT_CSV = Path("raw_data/renewable_power_plants_UK.csv")
OUTPUT_CSV = Path("processed_data/land_wind_farms.csv")

# The source file includes at least one malformed row with an embedded newline.
# Use the Python parser and skip bad rows so processing can continue.
df = pd.read_csv(INPUT_CSV, engine="python", on_bad_lines="skip")
df = df[df["energy_source_level_2"] == "Wind"]
df = df[df["technology"] == "Onshore"]

OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT_CSV, index=False)

print(f"Saved {len(df)} wind records to {OUTPUT_CSV}")