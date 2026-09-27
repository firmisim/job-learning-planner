from __future__ import annotations

import argparse

import uvicorn


DEFAULT_PORT = 8080


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local Job Learning Planner UI.")
    parser.add_argument(
        "--port",
        type=_port,
        default=DEFAULT_PORT,
        help=f"localhost port to bind (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args(argv)
    uvicorn.run(
        "ui.app:create_app",
        host="127.0.0.1",
        port=args.port,
        reload=False,
        factory=True,
    )


if __name__ == "__main__":
    main()
