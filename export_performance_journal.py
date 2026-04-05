from __future__ import annotations

from auth import CapitalSessionManager
from capital_api import CapitalAPI
from config import load_config
from performance_journal import export_performance_journal


if __name__ == "__main__":
    app_config = load_config()
    api = CapitalAPI(CapitalSessionManager(app_config.capital))
    result = export_performance_journal(api, app_config)
    print(
        f"Exported {result['rows']} journal rows to "
        f"{result['json_path']} and {result['csv_path']}"
    )
