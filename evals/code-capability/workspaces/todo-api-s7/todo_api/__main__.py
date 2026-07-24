"""CLI entry point: python -m todo_api --host 127.0.0.1 --port 8765"""
import argparse

from .server import create_server


def main():
    parser = argparse.ArgumentParser(description="Minimal in-memory Todo API")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    args = parser.parse_args()

    server = create_server(args.host, args.port)
    print(f"Serving on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
