"""Import releases and publish a static WinGet source to OpenArtifact raw."""

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


SERVER = "https://repo.hexor.cy"
BASE = SERVER + "/repos/raw/hexor-winget/"
PACKAGES = Path(__file__).with_name("packages.json")
INDEXES = ("source.msix", "source2.msix")


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=120) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output)
        expected_size = response.headers.get("Content-Length")
    if expected_size is not None and path.stat().st_size != int(expected_size):
        raise ValueError(f"Incomplete download of {url}")


def inventory():
    with urlopen(BASE, timeout=30) as response:
        records = json.load(response)
    return {record["path"]: record["sha256"] for record in (records or [])}


def prepare(work, repository, tag):
    templates = json.loads(PACKAGES.read_text(encoding="utf-8"))
    if repository not in templates:
        raise ValueError(f"Unknown WinGet producer: {repository!r}")
    version = tag.removeprefix("v")
    if not re.fullmatch(r"[0-9][0-9A-Za-z._+-]{0,100}", version) or version.endswith("."):
        raise ValueError(f"Expected a version or v-prefixed version, got {tag!r}")
    manifest = templates[repository]
    package_id = manifest["PackageIdentifier"]
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", package_id):
        raise ValueError(f"Invalid package identifier: {package_id}")
    inputs = work / "manifests"
    inputs.mkdir(parents=True)
    for name, checksum in inventory().items():
        if "/" in name or not name.endswith(".yaml"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9._+-]+\.yaml", name):
            raise ValueError(f"Invalid catalog manifest name: {name}")
        download(BASE + quote(name), inputs / name)
        if digest(inputs / name) != checksum:
            raise ValueError(f"Catalog checksum mismatch: {name}")

    for installer in manifest["Installers"]:
        url = installer["InstallerUrl"].format(tag=tag, version=version)
        parts = urlsplit(url)
        filename = parts.path.rsplit("/", 1)[-1]
        if parts.scheme != "https" or not re.fullmatch(r"[A-Za-z0-9._+-]+", filename) or filename in (".", ".."):
            raise ValueError(f"Expected an HTTPS installer URL ending in a filename: {url}")
        temp = work / "download"
        download(url, temp)
        checksum = digest(temp)
        relative = Path("installers", checksum, filename)
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.replace(target)
        installer.update(InstallerSha256=checksum.upper(), InstallerUrl=BASE + quote(relative.as_posix()))
        print(f"{package_id} {version}: {filename} SHA-256 {checksum}", flush=True)

    manifest.update(PackageVersion=version, ManifestType="singleton", ManifestVersion="1.6.0")
    path = inputs / f"{package_id}_{version}.yaml"
    # JSON is valid YAML and lets us use only the Python standard library.
    if path.exists() and json.loads(path.read_bytes()) != manifest:
        raise ValueError(f"{package_id} {version} is already published with different metadata or bytes; use a new version")
    if not path.exists():
        path.write_bytes((json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode())
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            print(f"package={package_id}\nversion={version}", file=output)


def write_token():
    env = os.environ
    request = Request(env["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + quote(SERVER, safe=""),
                      headers={"Authorization": "Bearer " + env["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    with urlopen(request, timeout=30) as response:
        jwt = json.load(response)["value"]
    payload = json.dumps({"policy": "github-winget-publish", "token": jwt}).encode()
    exchange = Request(SERVER + "/api/v1/auth/oidc/exchange", payload, {"Content-Type": "application/json"})
    with urlopen(exchange, timeout=30) as response:
        return json.load(response)["access_token"]


def publish(work):
    cache = work / "cache"
    existing = inventory()
    token = write_token()

    def put(file, name, replace=False):
        checksum = digest(file)
        if existing.get(name) == checksum:
            return
        if name in existing and not replace:
            raise ValueError(f"Refusing to replace previously published {name}")
        headers = {"Authorization": "Bearer " + token, "Content-Length": str(file.stat().st_size),
                   "Content-Type": "application/msix" if name in INDEXES else "application/octet-stream"}
        with file.open("rb") as stream:
            request = Request(BASE + quote(name), data=stream, headers=headers, method="PUT")
            with urlopen(request, timeout=180) as response:
                if json.load(response)["sha256"] != checksum:
                    raise ValueError(f"Upload checksum mismatch: {name}")
        print(f"Published {name}", flush=True)

    for index in INDEXES:
        if not (cache / index).is_file():
            raise ValueError(f"Missing {index}")
    for installer in sorted((work / "installers").rglob("*")):
        if installer.is_file():
            put(installer, installer.relative_to(work).as_posix())
    # v1 loads individual manifests; v2 also loads generated packages/ metadata.
    for file in sorted(cache.rglob("*")):
        if file.is_file() and file.suffix in (".yaml", ".mszyml"):
            put(file, file.relative_to(cache).as_posix())
    put(work / "hexor-winget.cer", "hexor-winget.cer", replace=True)
    for index in INDEXES:
        put(cache / index, index, replace=True)


if __name__ == "__main__":
    command, directory, *arguments = sys.argv[1:]
    if command == "prepare":
        prepare(Path(directory), *arguments)
    elif command == "publish":
        publish(Path(directory))
    else:
        raise SystemExit("Expected prepare or publish")
