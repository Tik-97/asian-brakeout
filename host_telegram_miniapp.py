from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

from config import TelegramConfig, load_config
from telegram_bot import TelegramNotifier


BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3000
DEFAULT_TUNNEL_URL_FILE = DASHBOARD_DIR / "public" / "data" / "local_miniapp_url.json"
TRY_CLOUDFLARE_PATTERN = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com", re.IGNORECASE)


def dashboard_base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def dashboard_ready(host: str, port: int, timeout_seconds: float = 3.0) -> bool:
    try:
        response = requests.get(dashboard_base_url(host, port), timeout=timeout_seconds)
        return response.ok
    except requests.RequestException:
        return False


def ensure_dashboard_built() -> None:
    subprocess.run(
        ["npm", "run", "build"],
        cwd=DASHBOARD_DIR,
        check=True,
        text=True,
    )


def start_dashboard_server(host: str, port: int) -> subprocess.Popen[str]:
    stdout_path = DASHBOARD_DIR / "miniapp_dashboard.out.log"
    stderr_path = DASHBOARD_DIR / "miniapp_dashboard.err.log"
    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")
    return subprocess.Popen(
        ["npm", "run", "start", "--", "--hostname", host, "--port", str(port)],
        cwd=DASHBOARD_DIR,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )


def wait_for_dashboard(host: str, port: int, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if dashboard_ready(host, port):
            return
        time.sleep(1)
    raise RuntimeError(f"Dashboard did not become ready on {dashboard_base_url(host, port)}")


def start_quick_tunnel(local_url: str) -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", local_url, "--no-autoupdate"],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    deadline = time.time() + 90
    found_url: str | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("cloudflared exited before publishing a public URL")
        line = process.stdout.readline() if process.stdout is not None else ""
        if not line:
            time.sleep(0.2)
            continue
        print(line.rstrip())
        match = TRY_CLOUDFLARE_PATTERN.search(line)
        if match:
            found_url = match.group(0)
            break

    if not found_url:
        process.terminate()
        raise RuntimeError("Could not detect a public trycloudflare URL from cloudflared output")

    return process, found_url


def write_public_url_snapshot(public_url: str) -> None:
    DEFAULT_TUNNEL_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_TUNNEL_URL_FILE.write_text(
        "{\n"
        f'  "public_url": "{public_url}",\n'
        f'  "updated_at_utc": "{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}"\n'
        "}\n",
        encoding="utf-8",
    )


def configure_telegram_mini_app(env_file: str, public_url: str, announce: bool) -> bool:
    config = load_config(env_file)
    telegram_cfg = TelegramConfig(
        bot_token=config.telegram.bot_token,
        chat_id=config.telegram.chat_id,
        enabled=config.telegram.enabled,
        mini_app_url=public_url,
        mini_app_button_text=config.telegram.mini_app_button_text,
    )
    notifier = TelegramNotifier(telegram_cfg)
    if not notifier.enabled:
        print("Telegram Mini App update skipped: bot token/chat id is not configured")
        return False

    notifier.ensure_menu_button()
    if announce:
        notifier.send(f"Mini App tunnel is live.\n{public_url}")
    return True


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Host the dashboard from this computer for Telegram Mini App access via Cloudflare Tunnel."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--reuse-dashboard",
        action="store_true",
        help="Do not start a new dashboard server if localhost is already serving the dashboard.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip `npm run build` before starting a new local dashboard server.",
    )
    parser.add_argument(
        "--no-announce",
        action="store_true",
        help="Update Telegram menu button only, without sending a chat message.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    host = args.host
    port = args.port
    local_url = dashboard_base_url(host, port)

    dashboard_process: subprocess.Popen[str] | None = None
    tunnel_process: subprocess.Popen[str] | None = None

    try:
        if not dashboard_ready(host, port):
            if args.reuse_dashboard:
                raise RuntimeError(f"No dashboard is reachable at {local_url}")
            if not args.skip_build:
                print("Building dashboard for stable local hosting...")
                ensure_dashboard_built()
            print(f"Starting local dashboard on {local_url}...")
            dashboard_process = start_dashboard_server(host, port)
            wait_for_dashboard(host, port)
        else:
            print(f"Reusing existing local dashboard on {local_url}")

        print("Opening Cloudflare quick tunnel...")
        tunnel_process, public_url = start_quick_tunnel(local_url)
        write_public_url_snapshot(public_url)
        configure_telegram_mini_app(args.env_file, public_url, announce=not args.no_announce)

        print("")
        print(f"Mini App public URL: {public_url}")
        print("Telegram menu button was updated to the tunnel URL.")
        print("Keep this process running. If it stops, the tunnel URL stops working.")

        while tunnel_process.poll() is None:
            time.sleep(1)

        raise RuntimeError("Cloudflare tunnel stopped")
    except KeyboardInterrupt:
        print("\nStopping Mini App tunnel...")
    finally:
        stop_process(tunnel_process)
        stop_process(dashboard_process)


if __name__ == "__main__":
    main()
