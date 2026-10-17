"""Command line for the P.IGE server.

    python -m pige.server serve [--host 127.0.0.1] [--port 8765]
    python -m pige.server hash-password      # prompts, prints PIGE_PASSWORD_HASH
    python -m pige.server new-token          # prints a token and its hash
    python -m pige.server new-secret         # prints a PIGE_SESSION_SECRET value
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from pige.server.auth import hash_password, new_api_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pige.server")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("hash-password", help="hash a password for PIGE_PASSWORD_HASH")
    sub.add_parser("new-token", help="create an API token (Thunderbird extension)")
    sub.add_parser("new-secret", help="create a random PIGE_SESSION_SECRET")
    args = parser.parse_args(argv)

    if args.command == "hash-password":
        first = getpass.getpass("Mot de passe : ")
        if len(first) < 12:
            print("Au moins 12 caractères.", file=sys.stderr)
            return 1
        if getpass.getpass("Confirmer : ") != first:
            print("Les deux saisies diffèrent.", file=sys.stderr)
            return 1
        print(hash_password(first))
        return 0
    if args.command == "new-token":
        token, token_hash = new_api_token()
        print("Jeton (à coller dans l'extension, affiché une seule fois) :")
        print(f"  {token}")
        print("Empreinte (à ajouter à PIGE_API_TOKEN_HASHES sur le serveur) :")
        print(f"  {token_hash}")
        return 0
    if args.command == "new-secret":
        print(secrets.token_urlsafe(48))
        return 0

    import uvicorn

    from pige.server.app import create_app
    from pige.server.config import Settings

    app = create_app(Settings.from_env())
    # Behind Nginx on the same machine: trust X-Forwarded-For from localhost only,
    # so login throttling sees the real client address.
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
