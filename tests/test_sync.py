import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync


def release(tag="v0.1.0-rc.10"):
    version = tag[1:].replace("-", "_")
    names = [f"tsunagi-{version}-1-{arch}.pkg.tar.zst" for arch in sync.ARCHES]
    names.append(f"tsunagi-gui-{version}-1-x86_64.pkg.tar.zst")
    return {"tag_name": tag, "draft": False, "prerelease": True,
            "assets": [{"name": name} for name in names]}


class ReleaseSelection(unittest.TestCase):
    def test_exact_tag_including_prerelease(self):
        expected = release()
        with patch.object(sync, "api", return_value=expected) as api:
            self.assertEqual(sync.resolve_release(sync.TSUNAGI, expected["tag_name"]), expected)
        api.assert_called_once_with("house-of-vanity/tsunagi/releases/tags/v0.1.0-rc.10")

    def test_corrected_prerelease_filenames_are_accepted(self):
        corrected = release()
        for asset in corrected["assets"]:
            asset["name"] = asset["name"].replace("0.1.0_rc.10", "0.1.0rc.10")
        self.assertEqual(len(sync.assets_for(sync.TSUNAGI, corrected)), 4)

    def test_reconciliation_skips_incomplete_and_draft_releases(self):
        incomplete = release("v0.1.0-rc.12")
        incomplete["assets"].pop()
        draft = release("v0.1.0-rc.11")
        draft["draft"] = True
        complete = release()
        with patch.object(sync, "api", return_value=[incomplete, draft, complete]):
            self.assertEqual(sync.resolve_release(sync.TSUNAGI), complete)
        with patch.object(sync, "api", return_value=incomplete):
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                sync.resolve_release(sync.TSUNAGI, incomplete["tag_name"])

    def test_dispatch_rejects_missing_tag_or_unknown_source_before_network(self):
        for source, tag in [(sync.TSUNAGI, ""), ("someone/else", "v1")]:
            with patch.dict(os.environ, {"EVENT_NAME": "repository_dispatch",
                                         "SOURCE_REPOSITORY": source, "RELEASE_TAG": tag}):
                with patch.object(sync, "api") as api:
                    with self.assertRaises(ValueError):
                        sync.download(Path("unused"))
                    api.assert_not_called()


@unittest.skipUnless(all(shutil.which(tool) for tool in ("repo-add", "vercmp", "bsdtar", "zstd", "pacman")),
                     "requires Arch Linux repository tools")
class RepositoryIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repository"
        self.incoming = self.root / "incoming"
        self.incoming.mkdir()

    def package(self, name="tsunagi", version="0.1.0_rc.10-1", arch="x86_64", payload=b"binary"):
        path = self.incoming / f"{name}-{version.split(':', 1)[-1]}-{arch}.pkg.tar.zst"
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            info = (f"pkgname = {name}\npkgver = {version}\narch = {arch}\n"
                    "pkgdesc = Test package\nsize = 6\nbuilddate = 1\nlicense = MIT\n").encode()
            for filename, content in [(".PKGINFO", info), (f"usr/bin/{name}", payload)]:
                entry = tarfile.TarInfo(filename)
                entry.size = len(content)
                entry.mode = 0o755
                archive.addfile(entry, io.BytesIO(content))
        with path.open("wb") as output:
            subprocess.run(["zstd", "-q", "-c"], input=data.getvalue(), stdout=output, check=True)
        return path

    def update(self):
        with contextlib.redirect_stdout(io.StringIO()):
            sync.update(self.repo, self.incoming)

    def snapshot(self):
        return {str(p.relative_to(self.repo)): p.read_bytes()
                for p in self.repo.rglob("*") if p.is_file()}

    def db_text(self, arch="x86_64"):
        with tarfile.open(self.repo / arch / f"{sync.REPO_NAME}.db.tar.gz") as archive:
            return "\n".join(archive.extractfile(p).read().decode()
                             for p in archive.getmembers() if p.isfile())

    def test_multiarch_gui_preserve_existing_and_pacman_reads_site(self):
        rexec = self.package("rexec", "1.1.0-1")
        self.update()
        rexec.unlink()
        for arch in sync.ARCHES:
            self.package(arch=arch)
        self.package(name="tsunagi-gui")
        self.update()
        site = self.root / "site"
        (self.repo / ".git").mkdir()
        sync.site(self.repo, site)
        self.assertFalse((site / ".git").exists())
        self.assertFalse(any(p.is_symlink() for p in site.rglob("*")))
        for arch in sync.ARCHES:
            self.assertIn("%NAME%\ntsunagi\n", self.db_text(arch))
            self.assertEqual((site / arch / f"{sync.REPO_NAME}.db").read_bytes(),
                             (site / arch / f"{sync.REPO_NAME}.db.tar.gz").read_bytes())
        self.assertIn("%NAME%\nrexec\n", self.db_text())
        self.assertIn("%NAME%\ntsunagi-gui\n", self.db_text())
        self.assertNotIn("%NAME%\ntsunagi-gui\n", self.db_text("aarch64"))
        dbpath = self.root / "pacman"
        dbpath.mkdir()
        config = self.root / "pacman.conf"
        config.write_text(f"[options]\nArchitecture = x86_64\nSigLevel = Optional TrustAll\n"
                          f"DBPath = {dbpath}\nLogFile = {self.root / 'pacman.log'}\n"
                          f"[{sync.REPO_NAME}]\nServer = file://{site}/$arch\n")
        subprocess.run(["pacman", "--config", str(config), "-Sy", "--noconfirm"], check=True)
        result = subprocess.check_output(["pacman", "--config", str(config), "-Sl"], text=True)
        self.assertIn("tsunagi 0.1.0_rc.10-1", result)
        self.assertIn("tsunagi-gui 0.1.0_rc.10-1", result)
        self.assertIn("rexec 1.1.0-1", result)

    def test_repeat_and_older_release_do_not_change_repository(self):
        package = self.package()
        self.update()
        before = self.snapshot()
        self.update()
        self.assertEqual(self.snapshot(), before)
        package.unlink()
        self.package(version="0.1.0_rc.9-1")
        self.update()
        self.assertEqual(self.snapshot(), before)

    def test_newer_version_replaces_database_entry_but_retains_old_archive(self):
        old = self.package(version="0.1.0_rc.9-1")
        self.update()
        old.unlink()
        self.package()
        self.update()
        self.assertIn("%VERSION%\n0.1.0_rc.10-1\n", self.db_text())
        self.assertNotIn("%VERSION%\n0.1.0_rc.9-1\n", self.db_text())
        self.assertTrue((self.repo / "x86_64" / old.name).exists())

    def test_changed_existing_version_is_rejected_without_mutation(self):
        self.package()
        self.update()
        before = self.snapshot()
        self.package(payload=b"different build")
        with self.assertRaisesRegex(ValueError, "Changed bytes"):
            self.update()
        self.assertEqual(self.snapshot(), before)

    def test_legacy_to_epoch_prerelease_to_stable(self):
        for version in ("0.1.0_rc.10-1", "1:0.1.0rc.11-1", "1:0.1.0-1"):
            package = self.package(version=version)
            self.update()
            self.assertIn(f"%VERSION%\n{version}\n", self.db_text())
            package.unlink()
        before = self.snapshot()
        self.package(version="0.1.0_rc.99-1")
        self.update()
        self.assertEqual(self.snapshot(), before)

    def test_mislabelled_package_is_rejected_without_mutation(self):
        package = self.package()
        self.update()
        before = self.snapshot()
        package.unlink()
        wrong = self.package(version="0.1.0_rc.11-1", arch="aarch64")
        wrong.rename(wrong.with_name(wrong.name.replace("aarch64", "x86_64")))
        with self.assertRaisesRegex(ValueError, "Filename disagrees"):
            self.update()
        self.assertEqual(self.snapshot(), before)

    def test_download_verifies_size_digest_and_package_identity(self):
        package = self.package(name="rexec", version="1.1.0-1")
        data = package.read_bytes()
        asset = {"name": package.name, "size": len(data),
                 "digest": "sha256:" + sync.digest(package),
                 "browser_download_url": f"https://github.com/house-of-vanity/rexec/releases/download/v1.1.0/{package.name}"}
        fixture = {"draft": False, "tag_name": "v1.1.0", "assets": [asset]}
        env = {"EVENT_NAME": "repository_dispatch", "SOURCE_REPOSITORY": "house-of-vanity/rexec",
               "RELEASE_TAG": "v1.1.0"}
        for overrides, expected in [({}, None), ({"size": len(data) + 1}, "Truncated"),
                                    ({"digest": "sha256:" + "0" * 64}, "Checksum mismatch")]:
            with self.subTest(overrides=overrides):
                changed = dict(fixture, assets=[dict(asset, **overrides)])
                with patch.dict(os.environ, env), patch.object(sync, "api", return_value=changed), \
                     patch.object(sync, "urlopen", return_value=io.BytesIO(data)):
                    if expected:
                        with self.assertRaisesRegex(ValueError, expected):
                            sync.download(self.root / "download")
                    else:
                        sync.download(self.root / "download")
                        self.assertEqual((self.root / "download" / package.name).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
