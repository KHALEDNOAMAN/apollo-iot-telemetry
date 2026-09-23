# Dataset

The simulators replay a real energy dataset rather than random numbers, so
that the value ranges, the daily load curve and the gaps in the data all look
like something a meter would actually produce.

## Default: household electric power consumption

UCI "Individual household electric power consumption", also published on
Kaggle. About 2 million minute by minute samples from one house over roughly
four years.

Download `household_power_consumption.txt` and drop it in this folder:

- Kaggle: https://www.kaggle.com/datasets/uciml/electric-power-consumption-data-set
- UCI: https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption

Columns used:

| Column                 | Unit | Mapped to       |
|------------------------|------|-----------------|
| `Voltage`              | V    | `voltage_v`     |
| `Global_intensity`     | A    | `current_a`     |
| `Global_active_power`  | kW   | `power_w` (x1000) |

This dataset has no temperature channel, so `temperature_c` is stored as
NULL. That is intentional and the schema allows it, because a real fleet mixes
devices with different sensor sets.

Missing values appear in the file as `?` and are stored as NULL rather than
being silently turned into zero. A zero volt reading and an unknown reading
are not the same thing.

## Alternative: electric motor temperature

Kaggle "Electric Motor Temperature" (`measures_v2.csv`) carries both
electrical and thermal channels. Set `DATASET_PROFILE=motor`. Note that the
published version of that dataset is z-scored, so the numbers are unitless
until you denormalise them.

## No download

`DATASET_PROFILE=synthetic` generates a plausible load profile in memory.
Useful for a first run and for CI, where downloading 130 MB is not sensible.
