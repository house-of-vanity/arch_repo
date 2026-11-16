# Arch Linux repository

Packages are hosted by GitHub Pages. Package archives and pacman databases live
in the `repo` branch; automation lives in `main`.

## Install

Add this to `/etc/pacman.conf`:

```ini
[btwiusearch.net]
SigLevel = Optional TrustAll
Server = https://btwiusearch.net/arch_repo/$arch/
```

```sh
sudo pacman -Syu tsunagi
# Or install the desktop/tray variant (x86_64 only):
sudo pacman -Syu tsunagi-gui
```

`tsunagi` is available for `x86_64`, `aarch64`, and `armv7h`. The GUI package
replaces/conflicts with the headless package. Existing users receive upgrades
with `sudo pacman -Syu`. Packages currently retain the repository's existing
unsigned-package policy.

## GitHub setup

1. In **arch_repo → Settings → Pages → Build and deployment**, set **Source**
   to **GitHub Actions**. Keep the existing domain configuration.
2. If the `github-pages` environment has deployment branch restrictions, allow
   `main` in **Settings → Environments → github-pages**. Remove required reviewers
   for this environment if fully automatic publication is wanted.
3. Create a **fine-grained personal access token**: choose resource owner
   `house-of-vanity`, select only `arch_repo`, and grant repository permission
   **Contents: Read and write**. Approve it in the organization if required.
4. Store it in **tsunagi → Settings → Secrets and variables → Actions** as the
   repository secret **`ARCH_REPO_TOKEN`**. Renew this secret when the token expires.
5. Ensure Actions are enabled in both repositories and organization policy allows
   the `actions/*` actions and the workflow's declared token permissions. The
   `repo` branch must permit pushes by this repository's workflow.

No custom secret is required in `arch_repo`: its own `GITHUB_TOKEN` updates the
`repo` branch and deploys Pages with the permissions declared in the workflow.

## Publication

After all assets for a `v*` tag have been uploaded, `tsunagi` sends a
`repository_dispatch` event to this repository:

```json
{
  "event_type": "new_package",
  "client_payload": {
    "repository": "house-of-vanity/tsunagi",
    "tag": "v0.1.0-rc.33"
  }
}
```

The updater downloads that exact release, including prereleases, validates its
complete set of Arch assets, size, SHA-256 when provided by GitHub, and `.PKGINFO`.
It updates each architecture's database with `repo-add`, commits the result to
`repo`, and explicitly deploys a Pages artifact containing packages and databases.
The `.db` and `.files` aliases are regular files because Pages artifacts cannot
contain symlinks. Existing `rexec` packages remain available.

Updates and deployments are serialized. `vercmp` prevents older releases from
replacing newer packages. An identical rerun does not change the repository;
changed bytes for the same package version fail with an instruction to bump the
version. Old archives remain downloadable for clients with cached databases.

New tsunagi packages use epoch `1` and the prerelease spelling `0.1.0rc.33`.
This makes RC → stable upgrades work with pacman and upgrades installations using
the old `0.1.0_rc.33` spelling. Historical release assets remain importable.

The nightly job and pushes to `main` reconcile the newest complete `tsunagi`
release (including prereleases) and the latest `rexec` release. This also recovers
missed dispatches. To retry a particular tag without rebuilding, use **Actions →
Publish Arch repository → Run workflow**, select `main`, and enter its tag. Leave
it empty to reconcile both projects. If Pages deployment alone fails, rerun its
failed job. A release dispatch acknowledges scheduling, not successful deployment;
check the `arch_repo` workflow for the final publication status.

## Validation

Run inside Arch Linux with `python`, `pacman`, `libarchive`, and `zstd` installed:

```sh
python -m unittest discover -s tests -v
```

Tests build real package fixtures, update databases using `repo-add`, and load the
published repository using `pacman`. They also cover prereleases, incomplete
releases, repeat runs, rollback prevention, metadata mismatch, and changed bytes.
