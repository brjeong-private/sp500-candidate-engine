from __future__ import annotations

import argparse
import io
import os
import tarfile
from pathlib import Path

import paramiko

EXCLUDES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv-1",
    "data",
    "logs",
}


def build_archive(root: Path) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(part in EXCLUDES for part in relative.parts):
                continue
            if path.name == ".env" or path.suffix == ".tmp":
                continue
            archive.add(path, arcname=relative.as_posix(), recursive=False)
    return stream.getvalue()


def remote_exec(client: paramiko.SSHClient, command: str) -> None:
    _, stdout, stderr = client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    if output:
        print(output, end="")
    if error:
        print(error, end="", file=os.sys.stderr)
    if exit_code:
        raise RuntimeError(f"Remote command failed with exit code {exit_code}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--bootstrap-script", type=Path, default=Path("scripts/azure/bootstrap-vm.sh")
    )
    args = parser.parse_args()

    password = args.password_file.read_text(encoding="utf-8").strip()
    archive = build_archive(args.repo_root.resolve())
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        username=args.username,
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    try:
        with client.open_sftp() as sftp:
            with sftp.file("/tmp/sp500-candidate-engine.tar.gz", "wb") as handle:
                handle.write(archive)
            sftp.put(str(args.env_file), "/tmp/sp500-candidate-engine.env")
            sftp.put(str(args.bootstrap_script), "/tmp/bootstrap-vm.sh")
            sftp.chmod("/tmp/sp500-candidate-engine.env", 0o600)
            sftp.chmod("/tmp/bootstrap-vm.sh", 0o700)
        remote_exec(
            client,
            "sudo mkdir -p /opt/sp500-candidate-engine && "
            "sudo mv /tmp/sp500-candidate-engine.env /opt/sp500-candidate-engine/.env && "
            "sudo chown $USER:$USER /opt/sp500-candidate-engine/.env && "
            "/tmp/bootstrap-vm.sh",
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
