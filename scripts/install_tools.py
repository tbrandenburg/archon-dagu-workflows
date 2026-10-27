"""Install pinned official DAGU/Task archives after SHA-256 verification."""

import hashlib
import io
import pathlib
import platform
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSIONS = {"dagu": "2.24.0", "task": "3.54.0"}


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "archon-dagu-workflows"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main():
    operating_system = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    architecture = {"x86_64": "amd64", "AMD64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine()
    )
    if not operating_system or not architecture:
        raise SystemExit("Installer supports Linux/macOS amd64/arm64. Use WSL on Windows.")
    directory = ROOT / ".tools/bin"
    directory.mkdir(parents=True, exist_ok=True)
    for tool, version in VERSIONS.items():
        if tool == "dagu":
            repo = "dagucloud/dagu"
            filename = f"dagu_{version}_{operating_system}_{architecture}.tar.gz"
            sums = "checksums.txt"
        else:
            repo = "go-task/task"
            filename = f"task_{operating_system}_{architecture}.tar.gz"
            sums = "task_checksums.txt"
        base = f"https://github.com/{repo}/releases/download/v{version}"
        checksums = download(base + "/" + sums).decode()
        expected = next(
            (
                line.split()[0]
                for line in checksums.splitlines()
                if line.split()[-1].lstrip("*") == filename
            ),
            None,
        )
        if not expected:
            raise SystemExit(f"No published checksum for {filename}")
        archive = download(base + "/" + filename)
        if hashlib.sha256(archive).hexdigest() != expected:
            raise SystemExit(f"Checksum mismatch for {filename}")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            member = next(
                x
                for x in tar.getmembers()
                if x.isfile() and pathlib.PurePosixPath(x.name).name == tool
            )
            data = tar.extractfile(member).read()
        temporary = directory / (tool + ".new")
        temporary.write_bytes(data)
        temporary.chmod(0o755)
        temporary.replace(directory / tool)
        print(f"Installed {tool} {version} (verified official archive)")


if __name__ == "__main__":
    main()
