#!/usr/bin/env python3
"""Import public release packages and publish a pacman repository. Stdlib only."""

import gzip
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO_NAME = "btwiusearch.net"
ARCHES = ("x86_64", "aarch64", "armv7h")
SOURCES = {
    "house-of-vanity/tsunagi": {"tsunagi", "tsunagi-gui"},
    "house-of-vanity/rexec": {"rexec"},
}
TSUNAGI = "house-of-vanity/tsunagi"


def api(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "arch-repo"}
    if token := os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(f"https://api.github.com/repos/{path}", headers=headers), timeout=60) as response:
        return json.load(response)


def assets_for(source, release):
    """Require the complete Arch build before importing a tsunagi release."""
    if release.get("draft"):
        raise ValueError(f"Draft releases cannot be published: {source} {release['tag_name']}")
    assets = [a for a in release["assets"] if a["name"].endswith(".pkg.tar.zst")]
    if not assets:
        raise ValueError(f"Release has no Arch packages: {source} {release['tag_name']}")
    if source == TSUNAGI:
        tag = release["tag_name"]
        if not re.fullmatch(r"v[0-9][A-Za-z0-9.+_-]*", tag):
            raise ValueError(f"Invalid tsunagi tag: {tag!r}")
        # Accept historical packages as well as the corrected epoch-1 scheme.
        expected_sets = []
        for version in (tag[1:].replace("-", "_"), tag[1:].replace("-", "")):
            expected = {f"tsunagi-{version}-1-{arch}.pkg.tar.zst" for arch in ARCHES}
            expected.add(f"tsunagi-gui-{version}-1-x86_64.pkg.tar.zst")
            expected_sets.append(expected)
        if {a["name"] for a in assets} not in expected_sets:
            raise ValueError(f"Incomplete or unexpected Arch assets for {tag}")
    return assets


def resolve_release(source, tag=None):
    if tag:
        release = api(f"{source}/releases/tags/{quote(tag, safe='')}")
        assets_for(source, release)
        return release
    # Upstreams also publish releases without Arch builds. Include tsunagi
    # prereleases while keeping rexec on its stable release channel.
    for page in range(1, 101):
        releases = api(f"{source}/releases?per_page=100&page={page}")
        for release in releases:
            if source != TSUNAGI and release["prerelease"]:
                continue
            try:
                assets_for(source, release)
            except ValueError:
                continue
            return release
        if len(releases) < 100:
            break
    raise ValueError(f"No release with eligible Arch packages found for {source}")


def metadata(path):
    output = subprocess.check_output(["bsdtar", "-xOf", str(path), ".PKGINFO"], text=True)
    fields = {}
    for line in output.splitlines():
        key, sep, value = line.partition(" = ")
        if sep and key in {"pkgname", "pkgver", "arch"}:
            if key in fields:
                raise ValueError(f"Duplicate {key} in {path}")
            fields[key] = value
    name, version, arch = (fields[k] for k in ("pkgname", "pkgver", "arch"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9@._+-]*", name):
        raise ValueError(f"Invalid package name: {name!r}")
    if not re.fullmatch(r"[A-Za-z0-9.+_:~-]+", version) or arch not in ARCHES:
        raise ValueError(f"Invalid version or unsupported architecture in {path}")
    filename_version = version.split(":", 1)[-1]
    if path.name != f"{name}-{filename_version}-{arch}.pkg.tar.zst":
        raise ValueError(f"Filename disagrees with .PKGINFO: {path.name}")
    return name, version, arch


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rebuild_file_contents(archive, member):
    with archive.extractfile(member) as stream:
        if member.name == ".PKGINFO":
            return re.sub(rb"(?m)^builddate = [0-9]+$", b"builddate = 0", stream.read())
        if member.name != ".MTREE":
            return hashlib.file_digest(stream, "sha256").digest()
        manifest = gzip.decompress(stream.read())

    # Only normalize .PKGINFO fields derived from this build's actual bytes.
    with archive.extractfile(".PKGINFO") as stream:
        info = stream.read()
    generated = {
        f"size={len(info)}".encode(): b"size=<pkginfo>",
        f"md5digest={hashlib.md5(info, usedforsecurity=False).hexdigest()}".encode(): b"md5digest=<pkginfo>",
        f"sha256digest={hashlib.sha256(info).hexdigest()}".encode(): b"sha256digest=<pkginfo>",
    }
    lines = re.sub(rb"(?m) time=[0-9]+(?:\.[0-9]+)?(?= |$)", b" time=0", manifest).splitlines()
    for i, line in enumerate(lines):
        if line.startswith(b"./.PKGINFO "):
            lines[i] = b" ".join(generated.get(field, field) for field in line.split(b" "))
    return lines


def tsunagi_build_contents(path):
    """Compare rebuilt packages using their actual files, including install scripts."""
    entries = {}
    with tempfile.TemporaryFile() as unpacked:
        subprocess.run(["zstd", "-dc", "--", str(path)], stdout=unpacked, check=True)
        unpacked.seek(0)
        with tarfile.open(fileobj=unpacked, mode="r:") as archive:
            for member in archive:
                if member.name in entries:
                    raise ValueError(f"Duplicate archive entry {member.name!r} in {path}")
                attrs = member.get_info()
                # The tar header checksum includes mtime. File contents below
                # account for size, including generated metadata of varying length.
                for key in ("mtime", "chksum", "size"):
                    del attrs[key]
                attrs["pax"] = {k: v for k, v in member.pax_headers.items()
                                if k not in {"mtime", "atime", "ctime"}}
                content = rebuild_file_contents(archive, member) if member.isfile() else None
                entries[member.name] = (attrs, content)
    return entries


def download(destination):
    event = os.environ.get("EVENT_NAME", "workflow_dispatch")
    tag = os.environ.get("RELEASE_TAG", "")
    source = os.environ.get("SOURCE_REPOSITORY", "")
    if event == "repository_dispatch":
        if source not in SOURCES or not tag:
            raise ValueError("new_package requires an allowed repository and exact release tag")
        requests = [(source, tag)]
    elif tag:
        requests = [(TSUNAGI, tag)]
    else:
        requests = [(source, None) for source in SOURCES]
    destination.mkdir(parents=True, exist_ok=True)
    for source, tag in requests:
        release = resolve_release(source, tag)
        print(f"Importing {source} {release['tag_name']}", flush=True)
        for asset in assets_for(source, release):
            name = asset["name"]
            if Path(name).name != name or not re.fullmatch(r"[A-Za-z0-9.+_~-]+\.pkg\.tar\.zst", name):
                raise ValueError(f"Invalid asset name: {name!r}")
            url = asset["browser_download_url"]
            if not url.startswith(f"https://github.com/{source}/releases/download/"):
                raise ValueError("Unexpected asset download URL")
            target = destination / name
            # Public release assets need no token; never forward API credentials.
            with urlopen(url, timeout=120) as response, target.open("wb") as output:
                shutil.copyfileobj(response, output)
            if target.stat().st_size != asset["size"]:
                raise ValueError(f"Truncated asset: {name}")
            if expected := asset.get("digest"):
                if expected != f"sha256:{digest(target)}":
                    raise ValueError(f"Checksum mismatch: {name}")
            pkgname, version, _ = metadata(target)
            if pkgname not in SOURCES[source]:
                raise ValueError(f"Unexpected package {pkgname} from {source}")
            if source == TSUNAGI:
                tag_version = release["tag_name"][1:]
                allowed = {tag_version.replace("-", "_") + "-1",
                           "1:" + tag_version.replace("-", "") + "-1"}
                if version not in allowed:
                    raise ValueError(f"Package version disagrees with release: {name}")


def compare(left, right):
    return int(subprocess.check_output(["vercmp", left, right], text=True).strip())


def index(directory):
    rows = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name == "index.html":
            continue
        label = html.escape(path.name)
        rows.append(f'<tr><td><a href="{quote(path.name)}">{label}</a></td>'
                    f'<td>{path.stat().st_size:,}</td></tr>')
    title = html.escape(f"{REPO_NAME} / {directory.name}")
    (directory / "index.html").write_text(
        f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title>'
        f'<h1>{title}</h1><table><tr><th>File</th><th>Bytes</th></tr>'
        + "\n".join(rows) + "</table></html>\n"
    )


def update(repository, incoming):
    # Validate all packages before changing the databases. Keep old archives so
    # clients with cached databases can still download their selected version.
    current = {}
    for arch in ARCHES:
        directory = repository / arch
        directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(directory.glob("*.pkg.tar.zst")):
            name, version, actual_arch = metadata(path)
            if actual_arch != arch:
                raise ValueError(f"Package in wrong architecture directory: {path}")
            key = (name, arch)
            if key not in current or compare(version, current[key][0]) > 0:
                current[key] = (version, path)
    pending = {}
    for path in sorted(incoming.glob("*.pkg.tar.zst")):
        name, version, arch = metadata(path)
        key = (name, arch)
        if key in current:
            old_version, old_path = current[key]
            order = compare(version, old_version)
            if order < 0:
                print(f"Skip older {path.name} (published {old_version})")
                continue
            if order == 0:
                if digest(path) == digest(old_path):
                    continue
                if name not in SOURCES[TSUNAGI] or tsunagi_build_contents(path) != tsunagi_build_contents(old_path):
                    raise ValueError(f"Changed bytes for existing version {path.name}; bump the version")
                print(f"Keep published {path.name} (equivalent rebuild)")
                continue
        current[key] = (version, path)
        pending[key] = path
    changed = set()
    for (name, arch), path in pending.items():
        target = repository / arch / path.name
        shutil.copy2(path, target)
        current[(name, arch)] = (current[(name, arch)][0], target)
        changed.add(arch)
    for arch in ARCHES:
        directory = repository / arch
        database = directory / f"{REPO_NAME}.db.tar.gz"
        packages = sorted(path for (name, pkgarch), (_, path) in current.items() if pkgarch == arch)
        if packages and (arch in changed or not database.exists()):
            subprocess.run(["repo-add", str(database), *(str(p) for p in packages)], check=True)
        # repo-add creates symlinks; Pages artifacts require regular files.
        for suffix in ("db", "files"):
            archive = directory / f"{REPO_NAME}.{suffix}.tar.gz"
            alias = directory / f"{REPO_NAME}.{suffix}"
            if archive.exists():
                if alias.is_symlink() or alias.exists():
                    alias.unlink()
                shutil.copyfile(archive, alias)
            for old in directory.glob(f"{REPO_NAME}.{suffix}*.old"):
                old.unlink()
        index(directory)
    links = "\n".join(f'<li><a href="{arch}/">{arch}</a></li>' for arch in ARCHES)
    (repository / "index.html").write_text(
        f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{REPO_NAME}</title>'
        f'<h1>Arch Linux packages</h1><ul>{links}</ul>\n'
        '<pre>[btwiusearch.net]\nSigLevel = Optional TrustAll\n'
        'Server = https://btwiusearch.net/arch_repo/$arch/</pre></html>\n'
    )
    (repository / ".nojekyll").touch()


def site(repository, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name in (*ARCHES, "index.html", ".nojekyll", "CNAME"):
        source = repository / name
        if source.is_dir():
            shutil.copytree(source, destination / name)
        elif source.is_file():
            shutil.copy2(source, destination / name)


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    {"download": download, "update": update, "site": site}[command](*(Path(a).resolve() for a in args))
