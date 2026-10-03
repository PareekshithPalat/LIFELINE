import os
import sys
import tempfile

# Isolate every test run: ephemeral Qdrant Edge shards and a throw-away runtime dir.
# Must happen before any project module reads the settings.
_RUNTIME = tempfile.mkdtemp(prefix="lifeline_test_runtime_")
os.environ["QDRANT_MEMORY_MODE"] = "true"
os.environ["LIFELINE_RUNTIME_DIR"] = _RUNTIME
os.environ["LIFELINE_NODE_ID"] = "test_node"
for var in ("LIFELINE_API_KEY", "LIFELINE_ADMIN_KEY", "LIFELINE_SERVER_URL"):
    os.environ.pop(var, None)
os.environ.setdefault("FASTEMBED_CACHE_PATH",
                      os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "models")))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def indexed():
    from edge.bootstrap import ensure_indexed
    return ensure_indexed()


@pytest.fixture(scope="session")
def pipeline(indexed):
    from edge.runtime.pipeline import get_pipeline
    return get_pipeline()


@pytest.fixture()
def profile():
    from edge.stores import get_profile_store
    return get_profile_store().get()
