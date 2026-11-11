"""Generate the sample e-commerce SQLite database.

Run:  python data/create_db.py            (writes data/sample.db)
      python data/create_db.py --out x.db (custom path)

The data is deterministic (fixed random seed), so every clone of the repo gets
identical rows and eval answers stay reproducible.

The schema is deliberately a little messy, because an agent is only interesting
on a database that is not trivial:

* `status` exists in customers, products, orders and returns with different
  meanings ("active" customer vs "completed" order vs "approved" return).
* `orders.total` and `order_items.amount` look similar but are different
  (total is net of discount, amount is quantity * unit_price).
* Some customer emails are NULL, some customers are duplicated (same email,
  different customer_id), and `orders.discount` is NULL for most rows.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SEED = 42  # fixed seed -> identical data on every run
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "sample.db"

# Size of the generated dataset and the date range orders are spread over.
N_CUSTOMERS = 200
N_ORDERS = 1500
ORDER_START = date(2025, 1, 1)
ORDER_END = date(2026, 9, 30)

# Table definitions. Inline `--` comments document allowed values and quirks.
SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL
);

CREATE TABLE products (
    product_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    price       REAL NOT NULL,
    status      TEXT NOT NULL            -- 'active' | 'discontinued'
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,                    -- NULL for some customers
    country     TEXT NOT NULL,
    signup_date TEXT NOT NULL,           -- ISO date
    status      TEXT NOT NULL            -- 'active' | 'inactive'
);

CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date  TEXT NOT NULL,           -- ISO date
    status      TEXT NOT NULL,           -- 'completed' | 'cancelled' | 'pending' | 'refunded'
    discount    REAL,                    -- NULL when no discount was applied
    total       REAL NOT NULL            -- sum of item amounts minus discount
);

CREATE TABLE order_items (
    item_id    INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    amount     REAL NOT NULL             -- quantity * unit_price
);

CREATE TABLE returns (
    return_id     INTEGER PRIMARY KEY,
    item_id       INTEGER NOT NULL REFERENCES order_items(item_id),
    return_date   TEXT NOT NULL,         -- ISO date
    reason        TEXT NOT NULL,         -- 'defective' | 'wrong_item' | 'changed_mind' | 'late_delivery'
    status        TEXT NOT NULL,         -- 'approved' | 'rejected' | 'pending'
    refund_amount REAL NOT NULL          -- 0 unless approved
);
"""

CATEGORIES = [
    "Electronics",
    "Home & Kitchen",
    "Books",
    "Clothing",
    "Sports",
    "Toys",
    "Beauty",
    "Garden",
]

# (product name, category name, price)
PRODUCTS = [
    ("Wireless Earbuds", "Electronics", 59.99),
    ("Smartphone Case", "Electronics", 14.99),
    ("USB-C Charger", "Electronics", 24.99),
    ("Bluetooth Speaker", "Electronics", 79.00),
    ("Laptop Stand", "Electronics", 39.50),
    ("Air Fryer", "Home & Kitchen", 119.00),
    ("Chef Knife", "Home & Kitchen", 45.00),
    ("Coffee Grinder", "Home & Kitchen", 34.99),
    ("Cast Iron Pan", "Home & Kitchen", 52.00),
    ("Blender", "Home & Kitchen", 69.99),
    ("Python Crash Course", "Books", 29.99),
    ("Data Science Handbook", "Books", 44.99),
    ("Mystery Novel", "Books", 12.99),
    ("Cookbook Classics", "Books", 24.50),
    ("Rain Jacket", "Clothing", 89.00),
    ("Running Shoes", "Clothing", 99.00),
    ("Wool Socks", "Clothing", 11.99),
    ("Denim Jeans", "Clothing", 64.00),
    ("Yoga Mat", "Sports", 27.99),
    ("Dumbbell Set", "Sports", 84.00),
    ("Tennis Racket", "Sports", 109.00),
    ("Water Bottle", "Sports", 18.99),
    ("Building Blocks", "Toys", 34.00),
    ("Puzzle 1000pc", "Toys", 19.99),
    ("Remote Car", "Toys", 42.50),
    ("Board Game", "Toys", 31.99),
    ("Face Cream", "Beauty", 28.00),
    ("Shampoo", "Beauty", 9.99),
    ("Perfume", "Beauty", 74.00),
    ("Lip Balm", "Beauty", 4.99),
    ("Garden Hose", "Garden", 32.00),
    ("Flower Seeds Pack", "Garden", 6.99),
    ("Pruning Shears", "Garden", 21.50),
    ("Plant Pots (3)", "Garden", 26.00),
    ("Old Model Phone", "Electronics", 149.00),
    ("Vintage Lamp", "Home & Kitchen", 58.00),
    ("Last Year Planner", "Books", 15.00),
    ("Retro Sneakers", "Clothing", 72.00),
]
# These products stop selling after 2025 (see the order generation loop below).
DISCONTINUED = {"Old Model Phone", "Vintage Lamp", "Last Year Planner", "Retro Sneakers"}

FIRST_NAMES = [
    "Ava", "Liam", "Noah", "Emma", "Olivia", "Mason", "Sophia", "Lucas",
    "Mia", "Ethan", "Amelia", "Logan", "Harper", "Aria", "Priya", "Arjun",
    "Mei", "Chen", "Sofia", "Mateo", "Fatima", "Omar", "Yuki", "Hiro",
]
LAST_NAMES = [
    "Smith", "Johnson", "Brown", "Garcia", "Miller", "Davis", "Patel",
    "Kumar", "Nguyen", "Wang", "Kim", "Silva", "Rossi", "Muller", "Khan",
    "Ivanov", "Sato", "Lopez", "Martin", "Clark",
]
COUNTRIES = ["USA", "India", "UK", "Germany", "Canada", "Australia", "Brazil", "Japan"]
RETURN_REASONS = ["defective", "wrong_item", "changed_mind", "late_delivery"]


def _random_date(rng: random.Random, start: date, end: date) -> date:
    """Pick a uniformly random date between `start` and `end` (inclusive)."""
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _make_customers(rng: random.Random) -> list[tuple]:
    """Build customer rows, including NULL emails and a few duplicate customers."""
    rows: list[tuple] = []
    for cid in range(1, N_CUSTOMERS + 1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        email = f"{first}.{last}{cid}@example.com".lower()
        if rng.random() < 0.08:  # messy data: missing email
            email = None
        signup = _random_date(rng, date(2024, 1, 1), date(2025, 12, 31))
        status = "active" if rng.random() < 0.85 else "inactive"
        rows.append((cid, f"{first} {last}", email, rng.choice(COUNTRIES), signup.isoformat(), status))

    # messy data: a handful of duplicate customers (same person, same email, new id)
    next_id = N_CUSTOMERS + 1
    for original in rng.sample([r for r in rows if r[2] is not None], 6):
        _, name, email, country, _, _ = original
        signup = _random_date(rng, date(2025, 1, 1), date(2025, 12, 31))
        rows.append((next_id, name, email, country, signup.isoformat(), "active"))
        next_id += 1
    return rows


def build_database(path: Path | str = DEFAULT_DB_PATH) -> Path:
    """Create (or replace) the sample database at `path` and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    rng = random.Random(SEED)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)

        # categories + products
        conn.executemany(
            "INSERT INTO categories (category_id, name) VALUES (?, ?)",
            list(enumerate(CATEGORIES, start=1)),
        )
        category_ids = {name: i for i, name in enumerate(CATEGORIES, start=1)}
        products = []
        for pid, (name, category, price) in enumerate(PRODUCTS, start=1):
            status = "discontinued" if name in DISCONTINUED else "active"
            products.append((pid, name, category_ids[category], price, status))
        conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", products)

        # customers
        customers = _make_customers(rng)
        conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", customers)
        customer_ids = [c[0] for c in customers]

        # popularity weights so some products/categories clearly dominate
        weights = [rng.choice([1, 1, 2, 3, 5, 8]) for _ in products]
        product_ids = [p[0] for p in products]
        price_of = {p[0]: p[3] for p in products}
        discontinued_ids = {p[0] for p in products if p[4] == "discontinued"}

        orders, items, returns = [], [], []
        item_id = 0
        return_id = 0
        for order_id in range(1, N_ORDERS + 1):
            order_date = _random_date(rng, ORDER_START, ORDER_END)
            roll = rng.random()
            # Order status mix: 78% completed, 10% cancelled, 5% refunded, 7% pending.
            status = (
                "completed" if roll < 0.78
                else "cancelled" if roll < 0.88
                else "refunded" if roll < 0.93
                else "pending"
            )

            # 1-4 line items per order (small orders are most common).
            order_items = []
            for _ in range(rng.choice([1, 1, 1, 2, 2, 3, 4])):
                pid = rng.choices(product_ids, weights=weights)[0]
                # discontinued products only sold in the first half of the range
                if pid in discontinued_ids and order_date > date(2025, 12, 31):
                    pid = rng.choice([p for p in product_ids if p not in discontinued_ids])
                qty = rng.choice([1, 1, 1, 2, 2, 3])
                unit_price = price_of[pid]
                item_id += 1
                order_items.append((item_id, order_id, pid, qty, unit_price, round(qty * unit_price, 2)))

            # ~20% of orders get a 5/10/15% discount; the rest keep discount = NULL.
            # orders.total is net of discount, unlike order_items.amount.
            subtotal = sum(i[5] for i in order_items)
            discount = round(subtotal * rng.choice([0.05, 0.10, 0.15]), 2) if rng.random() < 0.2 else None
            total = round(subtotal - (discount or 0), 2)

            orders.append((order_id, rng.choice(customer_ids), order_date.isoformat(), status, discount, total))
            items.extend(order_items)

            # returns: only for completed/refunded orders, ~12% of items
            if status in ("completed", "refunded"):
                for it in order_items:
                    if rng.random() < 0.12:
                        return_id += 1
                        r_status = rng.choices(["approved", "rejected", "pending"], weights=[6, 2, 2])[0]
                        refund = it[5] if r_status == "approved" else 0.0
                        r_date = order_date + timedelta(days=rng.randint(2, 30))
                        returns.append(
                            (return_id, it[0], r_date.isoformat(), rng.choice(RETURN_REASONS), r_status, refund)
                        )

        # Insert children after parents so foreign keys always point at real rows.
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", orders)
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?)", items)
        conn.executemany("INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?)", returns)
        conn.commit()
    finally:
        conn.close()
    return path


def main() -> None:
    """CLI entry point: build the database and print a row count per table."""
    parser = argparse.ArgumentParser(description="Generate the sample e-commerce SQLite database.")
    parser.add_argument("--out", default=str(DEFAULT_DB_PATH), help="output .db path")
    args = parser.parse_args()
    out = build_database(args.out)

    conn = sqlite3.connect(out)
    try:
        print(f"Created {out}")
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            print(f"  {table:<12} {count:>6} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
