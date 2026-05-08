import argparse
from collections.abc import Sequence

import uvicorn

from app import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remote-coder")
    parser.add_argument("--version", action="version", version=f"remote-coder {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="Run the Remote AI Coder FastAPI server")
    serve.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    serve.add_argument("--port", default=8000, type=int, help="Port to bind")
    serve.add_argument("--reload", action="store_true", help="Enable Uvicorn reload mode")
    serve.add_argument("--log-level", default="info", help="Uvicorn log level")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["serve"])

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
