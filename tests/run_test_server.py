"""Starts the real app (no window) against the fake TMDB, for the browser-level test."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_tmdb  # noqa: E402

fake = fake_tmdb.start()
os.environ["TALLY_TMDB_BASE"] = "http://127.0.0.1:%d/3" % fake.server_address[1]
os.environ["TALLY_IMG_BASE"] = "http://127.0.0.1:%d/t/p" % fake.server_address[1]
os.environ["TALLY_HOME"] = os.environ.get("TALLY_HOME") or tempfile.mkdtemp()
os.environ.update(TALLY_HEADLESS="1", TALLY_NO_LOCK="1", TALLY_PRINT_URL="1", TALLY_LAN_BIND="127.0.0.1", TALLY_LAN_PORT="0", TALLY_LAN_IPS="127.0.0.1")

from tally_app.main import main  # noqa: E402

main()
