"""
01_data_cleaning.py

Cleans the raw Superstore dataset and loads it into a SQLite database.
Run this script first before opening the notebook or Power BI.

Input   : data/superstore_raw.csv
Outputs : data/superstore_clean.csv
          data/data_quality_report.csv
          data/superstore.db

Run: python 01_data_cleaning.py
"""

import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# File paths
DATA_DIR     = Path("data")
RAW_PATH     = DATA_DIR / "superstore_raw.csv"
CLEAN_PATH   = DATA_DIR / "superstore_clean.csv"
QUALITY_PATH = DATA_DIR / "data_quality_report.csv"
DB_PATH      = DATA_DIR / "superstore.db"

# Discount brackets — used to group orders by how heavily discounted they were.
# This is the core lens for the discount-profit analysis.
DISCOUNT_BINS: list[float] = [-0.01, 0, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0]
DISCOUNT_LABELS: list[str] = [
    "No discount", "1-10%", "11-20%", "21-30%", "31-40%", "41-50%", "51-80%"
]

# Orders with discounts above this threshold are almost always unprofitable.
# Used to flag high-risk orders throughout the analysis.
HIGH_DISCOUNT_THRESHOLD: float = 0.2


def log_step(msg: str) -> None:
    """Print a progress message so you can follow what the script is doing."""
    print(f"[ETL] {msg}")


def check_files_exist() -> None:
    """
    Check that the required input file exists before we start.
    Gives a clear error message if it is missing rather than letting
    pandas fail with something unhelpful later on.
    """
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"Required input file not found: {RAW_PATH}\n"
            f"Make sure the data/ folder is in the same directory as this script."
        )


def quality_report(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """
    Produces a data quality summary for a given dataframe.

    For each column it reports the dtype, null count, null percentage,
    and number of unique values.

    Args:
        df:   The dataframe to profile.
        name: A label for this dataset shown in the 'dataset' column.

    Returns:
        A dataframe with one row per column and quality metrics as columns.
    """
    return pd.DataFrame({
        "dataset"   : name,
        "column"    : df.columns,
        "dtype"     : df.dtypes.values,
        "null_count": df.isnull().sum().values,
        "null_pct"  : (df.isnull().mean() * 100).round(1).values,
        "unique"    : [df[c].apply(str).nunique() for c in df.columns],
    })


# Make sure everything is in place before we start
check_files_exist()
DATA_DIR.mkdir(exist_ok=True)


# Load the raw data
log_step("Loading raw data ...")

# encoding='latin-1' handles special characters in product names
df = pd.read_csv(str(RAW_PATH), encoding="latin-1")
log_step(f"  superstore_raw : {df.shape[0]:,} rows × {df.shape[1]} cols")


# Clean the data
log_step("Cleaning data ...")

# Parse dates explicitly so we can extract year, month, and quarter
df["Order Date"] = pd.to_datetime(df["Order Date"])
df["Ship Date"]  = pd.to_datetime(df["Ship Date"])

# Remove the 8 orders where the same product appears twice on the same order.
# These are likely data entry errors — we keep the first occurrence.
before = len(df)
df = df.drop_duplicates(subset=["Order ID", "Product ID"], keep="first")
log_step(f"  Removed {before - len(df)} duplicate order-product entries")

# Drop columns that add no analytical value
# Row ID is just a sequence number, Country is always United States
df = df.drop(columns=["Row ID", "Country"])

# Rename columns to remove spaces — makes SQL queries and pandas cleaner
df.columns = [c.replace(" ", "_").replace("-", "_") for c in df.columns]

# Derived columns used throughout the analysis
df["year"]             = df["Order_Date"].dt.year
df["month"]            = df["Order_Date"].dt.month
df["quarter"]          = df["Order_Date"].dt.quarter
df["profit_margin"]    = (df["Profit"] / df["Sales"] * 100).round(2)
df["is_profitable"]    = (df["Profit"] > 0).astype(int)
df["is_high_discount"] = (df["Discount"] > HIGH_DISCOUNT_THRESHOLD).astype(int)
df["revenue_per_unit"] = (df["Sales"] / df["Quantity"]).round(2)

# Group orders into discount brackets for the core analysis
df["discount_bracket"] = pd.cut(
    df["Discount"],
    bins=DISCOUNT_BINS,
    labels=DISCOUNT_LABELS,
)

log_step(f"  Clean shape: {df.shape}")
log_step(f"  Date range: {df['Order_Date'].min().date()} to {df['Order_Date'].max().date()}")
log_step(f"  Total revenue: ${df['Sales'].sum():,.0f}")
log_step(f"  Total profit:  ${df['Profit'].sum():,.0f}")
log_step(f"  Overall margin: {df['Profit'].sum()/df['Sales'].sum()*100:.1f}%")


# Generate a data quality report
log_step("Generating data quality report ...")
qr = quality_report(df, "superstore")
print("\nData Quality Report")
print(qr.to_string(index=False))


# Save the cleaned data
log_step("Saving cleaned data ...")
df.to_csv(str(CLEAN_PATH), index=False)
qr.to_csv(str(QUALITY_PATH), index=False)
log_step(f"  → {CLEAN_PATH}   ({len(df):,} rows)")
log_step(f"  → {QUALITY_PATH}")

print("\nSummary Stats")
print(df[["Sales", "Profit", "Discount", "profit_margin"]].describe().round(2))


# Load into SQLite database
log_step("Creating SQLite database ...")

with sqlite3.connect(str(DB_PATH)) as conn:
    df.to_sql("orders", conn, if_exists="replace", index=False)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM orders")
    row_count: int = cursor.fetchone()[0]

log_step(f"  → {DB_PATH}   ({row_count:,} rows in 'orders' table)")
log_step("Done ✓")
