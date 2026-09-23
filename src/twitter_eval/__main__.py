"""Entry point: pick a free port, launch uvicorn and open the browser."""

from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn

from .config import load_settings


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(preferred: int, host: str = "127.0.0.1") -> int:
    """The preferred port if free, else the next free one, else an ephemeral port."""
    for port in range(preferred, preferred + 50):
        if _port_free(host, port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser(
        prog="twitter-eval",
        description="Live tweet-sentiment evaluation against the SemIf decision API.",
    )
    parser.add_argument("--host", default=settings.host, help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="fixed port (default: first free)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    args = parser.parse_args()

    port = args.port or find_free_port(settings.preferred_port, args.host)
    url = f"http://{args.host}:{port}"

    print(f"Twitter Eval  ->  {url}")
    print(f"SemIf API     ->  {settings.semif_api_url}")
    print(f"Dataset       ->  {settings.csv_file}  (limit={settings.limit}, sample={settings.sample})")

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    uvicorn.run("twitter_eval.server:app", host=args.host, port=port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
