"""Write the Session 4 Silver extract and the Gold change feed.

The sales, customers, and products are the Session 3 publish, rebuilt from
Session 3 Bronze. The change feed is the governed sample for this hour.
Re-running this file rewrites the same bytes. It does not modify Session 2
or Session 3, and it does not call a model or the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.gold.bronze_silver import derive_silver  # noqa: E402
from src.gold.silver import CHANGE_DEFAULTS, CHANGE_FILES, SILVER_FILES, frame_to_records, write_jsonl  # noqa: E402


def main() -> None:
    silver = derive_silver(ROOT)
    silver_root = ROOT / "data" / "session_04" / "silver"
    write_jsonl(silver_root / SILVER_FILES["sales"], frame_to_records(silver["sales"]))
    write_jsonl(silver_root / SILVER_FILES["customers"], frame_to_records(silver["customers"]))
    write_jsonl(silver_root / SILVER_FILES["products"], frame_to_records(silver["products"]))

    change_root = ROOT / "data" / "session_04" / "changes"
    for key, filename in CHANGE_FILES.items():
        write_jsonl(change_root / filename, [dict(row) for row in CHANGE_DEFAULTS[key]])

    print(f"sales {len(silver['sales'])}")
    print(f"customers {len(silver['customers'])}")
    print(f"products {len(silver['products'])}")
    print(silver_root)
    print(change_root)


if __name__ == "__main__":
    main()
