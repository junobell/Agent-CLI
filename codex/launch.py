import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def update_cli(codex):
    prefix = codex.parent.parent
    package = prefix / "lib/node_modules/@openai/codex/package.json"
    npm = codex.with_name("npm")
    if not npm.is_file():
        return

    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    state = cache / "codex-launcher" / prefix.name / "update-check"
    state.parent.mkdir(parents=True, exist_ok=True)
    with state.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not package.is_file() or not codex.resolve().is_relative_to(package.parent):
            return
        stat = os.fstat(lock.fileno())
        last_check = stat.st_mtime if stat.st_size else 0
        if time.time() - last_check < 86400:
            return
        lock.write("\n")
        lock.flush()

        current = json.loads(package.read_text())["version"]
        npm_command = [str(npm), "--fetch-retries=0", "--fetch-timeout=10000"]
        latest = json.loads(subprocess.check_output(
            [*npm_command, "view", "@openai/codex@latest", "version", "--json"],
            text=True, timeout=15,
        ))
        current_stable = current.split("-", 1)[0]
        if not all(re.fullmatch(r"\d+\.\d+\.\d+", version)
                   for version in (current_stable, latest)):
            raise ValueError("unexpected npm version")
        if tuple(map(int, latest.split("."))) > tuple(map(int, current_stable.split("."))) or (
            latest == current_stable and current != current_stable
        ):
            subprocess.run(
                [*npm_command, "install", "--global", "--prefix", str(prefix),
                 f"@openai/codex@{latest}"],
                check=True,
            )


def latest_sol(codex):
    catalog = json.loads(subprocess.check_output(
        [str(codex), "debug", "models"], text=True, timeout=8,
    ))
    candidates = {}
    for model in catalog["models"]:
        slug = model["slug"]
        version = re.fullmatch(r"gpt-(\d+(?:\.\d+)*)-sol", slug)
        efforts = {level["effort"] for level in model["supported_reasoning_levels"]}
        if version and model["visibility"] == "list" and {"medium", "high"} <= efforts:
            candidates[tuple(map(int, version[1].split(".")))] = slug
    return candidates[max(candidates)] if candidates else None


def main():
    if len(sys.argv) < 2 or not sys.argv[1]:
        sys.exit("codex: command not found")
    codex = Path(sys.argv[1])
    try:
        update_cli(codex)
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as error:
        print(f"Codex update check failed: {error}", file=sys.stderr)

    if not codex.is_file() and len(sys.argv) > 2 and sys.argv[2]:
        codex = Path(sys.argv[2])
    if not codex.is_file():
        sys.exit(f"codex: executable not found at {codex}")
    args = [str(codex)]
    try:
        model = latest_sol(codex)
        if model:
            args.extend(["-m", model])
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError):
        print("Codex model discovery failed. Using the configured model.", file=sys.stderr)
    os.execv(codex, args)


if __name__ == "__main__":
    main()
