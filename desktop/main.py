"""Entry point for launching the SentinelOps Windows Control Center."""

import argparse
import sys
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from desktop.api.client import SentinelOpsClient
from desktop.config import DesktopConfig
from desktop.ui.main_window import MainWindow


def main() -> int:
    """Initialize configuration, Qt event loop, and display main window."""
    parser = argparse.ArgumentParser(description="SentinelOps Windows Control Center")
    parser.add_argument("--url", dest="backend_url", default=None, help="Backend API URL")
    parser.add_argument("--config", dest="config_path", default=None, help="Custom configuration JSON path")
    args = parser.parse_args()

    cfg_path = Path(args.config_path) if args.config_path else None
    config = DesktopConfig.load(config_path=cfg_path)
    if args.backend_url:
        config.backend_url = args.backend_url.rstrip("/")

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("SentinelOps Control Center")
    app.setOrganizationName("SentinelOps")

    client = SentinelOpsClient(
        base_url=config.backend_url,
        timeout=config.request_timeout_seconds,
        reindex_timeout=config.reindex_timeout_seconds,
    )

    window = MainWindow(config=config, client=client)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
