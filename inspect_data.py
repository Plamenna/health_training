import os

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

DATA_DIR = os.environ.get("DATA_DIR", "data")


def print_data_summary(path=DATA_DIR, sample_rows=5):
    """Print the variables, their types and some example values of the stored data."""
    # Hive partitioning turns the received_date=YYYY-MM-DD folders into a `received_date` column
    dataset = ds.dataset(path, format="parquet", partitioning="hive")
    files = dataset.files
    if not files:
        print(f"No Parquet files found in {path}")
        return

    # Files can have different columns, and nested ones (e.g. Health Auto Export's metrics
    # vs workouts) that Arrow can't merge directly, so rebuild one table from all rows
    rows = []
    for f in files:
        received_date = os.path.basename(os.path.dirname(f)).partition("=")[2]
        rows += [{**row, "received_date": received_date} for row in pq.read_table(f).to_pylist()]
    table = pa.Table.from_struct_array(pa.array(rows))
    print(f"Files: {len(files)}   Rows: {table.num_rows}   Columns: {table.num_columns}\n")

    print(f"{'variable':<20} {'type':<35} {'missing':>8}  examples")
    print("-" * 90)
    for name in table.column_names:
        column = table.column(name)
        examples = [str(v) for v in column.to_pylist() if v is not None][:3]
        print(f"{name:<20} {str(column.type):<35} {column.null_count:>8}  {examples}")

    print(f"\nFirst {min(sample_rows, table.num_rows)} rows:")
    for row in table.slice(0, sample_rows).to_pylist():
        print("  " + ", ".join(f"{k}={v}" for k, v in row.items()))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Show the variables and rows of the stored data")
    parser.add_argument("path", nargs="?", default=DATA_DIR, help="data folder (default: DATA_DIR)")
    parser.add_argument("--rows", type=int, default=5, help="how many rows to print (default: 5)")
    args = parser.parse_args()
    print_data_summary(args.path, sample_rows=args.rows)
