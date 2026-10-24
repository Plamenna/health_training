"""Explore an Apple Health export (Health app > profile > Export All Health Data).

Usage:
    python explore_health_export.py export.zip              # since Monday of this week
    python explore_health_export.py export.zip --days 30    # the last 30 days

Prints what data types exist in the period and saves them as Parquet in --out.
"""
import argparse
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pandas as pd

DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"
PREFIXES = ("HKQuantityTypeIdentifier", "HKCategoryTypeIdentifier", "HKDataType",
            "HKWorkoutActivityType", "HKCategoryValue")


def short(name):
    for prefix in PREFIXES:
        if name and name.startswith(prefix):
            return name[len(prefix):]
    return name


def open_export(path):
    # Accept the zip straight from the phone, or an already unzipped export.xml
    if zipfile.is_zipfile(path):
        archive = zipfile.ZipFile(path)
        xml_name = next(n for n in archive.namelist() if n.endswith("/export.xml") or n == "export.xml")
        return archive.open(xml_name)
    return open(path, "rb")


def parse_export(path, since):
    records, workouts, activity = [], [], []
    # Cheap string check first, so millions of old records are skipped without date parsing
    since_prefix = (since - timedelta(days=1)).strftime("%Y-%m-%d")

    with open_export(path) as f:
        # Stream the file: exports are often hundreds of MB
        for _, elem in ET.iterparse(f, events=("end",)):
            tag = elem.tag
            if tag == "Record":
                start = elem.get("startDate", "")
                if start >= since_prefix and datetime.strptime(start, DATE_FORMAT) >= since:
                    records.append({
                        "type": short(elem.get("type")),
                        "value": short(elem.get("value")),
                        "unit": elem.get("unit"),
                        "start": datetime.strptime(start, DATE_FORMAT),
                        "end": datetime.strptime(elem.get("endDate"), DATE_FORMAT),
                        "source": elem.get("sourceName"),
                    })
                elem.clear()
            elif tag == "Workout":
                start = elem.get("startDate", "")
                if start >= since_prefix and datetime.strptime(start, DATE_FORMAT) >= since:
                    workouts.append(parse_workout(elem))
                elem.clear()
            elif tag == "ActivitySummary":
                day = elem.get("dateComponents", "")
                if day >= since.strftime("%Y-%m-%d"):
                    activity.append({k: v for k, v in elem.attrib.items()})
                elem.clear()

    return pd.DataFrame(records), pd.DataFrame(workouts), pd.DataFrame(activity)


def parse_workout(elem):
    workout = {
        "type": short(elem.get("workoutActivityType")),
        "start": datetime.strptime(elem.get("startDate"), DATE_FORMAT),
        "end": datetime.strptime(elem.get("endDate"), DATE_FORMAT),
        "duration": float(elem.get("duration", "nan")),
        "duration_unit": elem.get("durationUnit"),
        "source": elem.get("sourceName"),
    }
    # Older exports put totals on the Workout itself, newer ones in WorkoutStatistics
    for attr in ("totalDistance", "totalEnergyBurned"):
        if elem.get(attr):
            workout[attr] = float(elem.get(attr))
            workout[f"{attr}_unit"] = elem.get(f"{attr}Unit")
    for stat in elem.findall("WorkoutStatistics"):
        name = short(stat.get("type"))
        for key in ("sum", "average", "minimum", "maximum"):
            if stat.get(key):
                workout[f"{name}_{key}"] = float(stat.get(key))
        workout[f"{name}_unit"] = stat.get("unit")
    for meta in elem.findall("MetadataEntry"):
        workout[f"meta_{short(meta.get('key').replace('HKMetadataKey', ''))}"] = meta.get("value")
    workout["has_route"] = elem.find("WorkoutRoute") is not None
    return workout


def summarise_records(records):
    records = records.assign(value_num=pd.to_numeric(records["value"], errors="coerce"))
    rows = []
    for name, group in records.groupby("type"):
        numeric = group["value_num"].notna().all()
        rows.append({
            "type": name,
            "count": len(group),
            "unit": ", ".join(group["unit"].dropna().unique()) or "-",
            "first": group["start"].min().strftime("%a %d %b %H:%M"),
            "last": group["start"].max().strftime("%a %d %b %H:%M"),
            # Numbers get min/mean/max; categories (e.g. sleep stages) get their values
            "values": (f"min {group['value_num'].min():g}  mean {group['value_num'].mean():.4g}  "
                       f"max {group['value_num'].max():g}" if numeric
                       else ", ".join(f"{v} ({n})" for v, n in group["value"].value_counts().head(4).items())),
            "sources": ", ".join(group["source"].unique()),
        })
    return pd.DataFrame(rows).sort_values("count", ascending=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", help="export.zip or export.xml from the Health app")
    parser.add_argument("--days", type=int, help="look back this many days (default: since Monday)")
    parser.add_argument("--out", default="health_export_data", help="folder for the Parquet files")
    args = parser.parse_args()

    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=args.days) if args.days else today - timedelta(days=today.weekday())
    print(f"Reading {args.export} for data since {since:%A %d %B %Y}...\n")

    records, workouts, activity = parse_export(args.export, since)

    pd.set_option("display.width", 250, "display.max_columns", 50, "display.max_colwidth", 60)
    print(f"=== Health records: {len(records)} samples ===")
    if not records.empty:
        print(summarise_records(records).to_string(index=False))

    print(f"\n=== Workouts: {len(workouts)} ===")
    if not workouts.empty:
        # Only show columns that at least one workout has
        print(workouts.dropna(axis=1, how="all").to_string(index=False))

    print(f"\n=== Daily activity rings: {len(activity)} days ===")
    if not activity.empty:
        print(activity.to_string(index=False))

    os.makedirs(args.out, exist_ok=True)
    for name, df in (("records", records), ("workouts", workouts), ("activity", activity)):
        if not df.empty:
            df.to_parquet(os.path.join(args.out, f"{name}.parquet"), index=False)
    print(f"\nSaved Parquet files to {args.out}/")


if __name__ == "__main__":
    main()
