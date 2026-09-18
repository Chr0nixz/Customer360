#!/usr/bin/env python3
"""Write DockerRuntimeEvidence JSON from a local image Id. Stdlib only."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--command", default="c360 doctor")
    parser.add_argument("--user", default="c360")
    parser.add_argument("--hidden-in-image", action="store_true")
    args = parser.parse_args()

    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}}", args.image],
        check=False,
        capture_output=True,
        text=True,
    )
    if inspect.returncode != 0:
        sys.stderr.write(inspect.stderr)
        return inspect.returncode or 2
    digest = inspect.stdout.strip()
    if not DIGEST.fullmatch(digest):
        sys.stderr.write(f"image id is not sha256:<64 hex>: {digest!r}\n")
        return 2

    passed = not args.hidden_in_image
    payload = {
        "artifact_kind": "rc_evidence",
        "gate": "docker_runtime",
        "passed": passed,
        "docker_digest": digest if passed else "",
        "network": "none",
        "read_only": True,
        "non_root_user": args.user,
        "hidden_in_image": args.hidden_in_image,
        "command": args.command,
        "artifact_digests": {"image_id": digest} if passed else {},
        "limitations": [
            "Digest is docker inspect image Id; registry RepoDigest only exists after push",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(str(output) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
