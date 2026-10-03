import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from edge.bootstrap import ensure_indexed
from edge.qdrant.client import get_qdrant_manager, reset_qdrant_manager


def seed_database():
    """Indexes trusted protocols, the personal profile and incident log into Qdrant Edge."""
    print("--- Indexing Lifeline edge memory (Qdrant Edge) ---")
    report = ensure_indexed()
    print(f"  {report}")
    for tier, stats in get_qdrant_manager().get_stats().items():
        if isinstance(stats, dict):
            print(f"  {tier}: {stats.get('documents', 0)} documents / {stats.get('points_count', 0)} points")


if __name__ == "__main__":
    seed_database()
    reset_qdrant_manager()
