"""Hash pinned Git checkout files inside the Plane 2 guest.

The digest covers tracked file bytes, executable bits, symlink text and missing
paths. The helper never follows checkout symlinks or exports file contents.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
from contextlib import ExitStack

MAX_TREE_BYTES = 8 * 1024 * 1024
MAX_FILES = 25_000
MAX_FILE_BYTES = 128 * 1024 * 1024
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _tracked_paths(root: str, commit: str) -> list[bytes]:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("invalid pinned commit")
    # Disable replacement objects and network fetches for the pinned manifest.
    with subprocess.Popen(
        ["/usr/bin/git", "--no-replace-objects", "-C", root, "ls-tree", "-rz", commit],
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as git:
        assert git.stdout is not None
        listing = git.stdout.read(MAX_TREE_BYTES + 1)
        if len(listing) > MAX_TREE_BYTES:
            git.kill()
            raise ValueError("tracked manifest exceeds the byte limit")
        if git.wait() != 0:
            raise ValueError("pinned manifest unavailable")
    entries = listing.split(b"\0")[:-1]
    if len(entries) > MAX_FILES:
        raise ValueError("tracked manifest exceeds the file limit")
    # Gitlinks name other repositories. The existing clone does not fetch them.
    return [entry.split(b"\t", 1)[1] for entry in entries if not entry.startswith(b"160000 ")]


def _read_entry(root_fd: int, path: bytes, remaining: int) -> tuple[bytes, int]:
    """Return a framed kind/content signature and the number of bytes read."""
    parts = path.split(b"/")
    if any(part.lower() in (b"", b".", b"..", b".git") for part in parts):
        raise ValueError("invalid tracked path")
    with ExitStack() as stack:
        parent_fd = root_fd
        try:
            for part in parts[:-1]:
                parent_fd = os.open(part, DIR_FLAGS, dir_fd=parent_fd)
                stack.callback(os.close, parent_fd)
            name = parts[-1]
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError):
            return b"missing", 0

        if stat.S_ISLNK(info.st_mode):
            return b"link:" + hashlib.sha256(os.readlink(name, dir_fd=parent_fd)).digest(), 0
        if not stat.S_ISREG(info.st_mode):
            return b"other", 0
        # A concurrent replacement with a FIFO or symlink must not block or be read.
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        with os.fdopen(fd, "rb") as stream:
            start = os.fstat(stream.fileno())
            if not stat.S_ISREG(start.st_mode) or start.st_size > remaining:
                raise ValueError("tracked file unavailable within the read budget")
            digest = hashlib.sha256()
            read = 0
            while chunk := stream.read(min(65536, remaining - read + 1)):
                read += len(chunk)
                if read > remaining:
                    raise ValueError("checkout exceeds the read budget")
                digest.update(chunk)
            end = os.fstat(stream.fileno())
            if read != start.st_size or start.st_ctime_ns != end.st_ctime_ns:
                raise ValueError("tracked file changed during capture")
        kind = b"exec:" if start.st_mode & stat.S_IXUSR else b"file:"
        return kind + digest.digest(), read


def digest_checkout(root: str, commit: str) -> str:
    """Hash only pinned paths, so install-created tooling and canaries are excluded."""
    with ExitStack() as stack:
        root_fd = os.open(root, DIR_FLAGS)
        stack.callback(os.close, root_fd)
        paths = _tracked_paths(root, commit)
        if not paths:
            raise ValueError("pinned checkout has no tracked files")
        digest = hashlib.sha256(b"killhub-checkout-v1\0")
        remaining = MAX_FILE_BYTES
        for path in paths:
            signature, used = _read_entry(root_fd, path, remaining)
            remaining -= used
            digest.update(len(path).to_bytes(4, "big") + path)
            digest.update(len(signature).to_bytes(4, "big") + signature)
        return digest.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    parser.add_argument("commit")
    args = parser.parse_args()
    try:
        print(digest_checkout(args.root, args.commit))
    except (OSError, ValueError):
        # Do not emit repository-controlled paths or command output.
        raise SystemExit("checkout digest unavailable") from None
