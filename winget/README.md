# Hexor WinGet

OpenArtifact serves a preindexed WinGet source at `https://repo.hexor.cy/repos/raw/hexor-winget`. The GitHub release job for Tsunagi already dispatches `new_package` here after uploading every installer. The WinGet workflow imports the release identified by that event, including prereleases with a Windows installer.

## Signing setup

Run once in a local checkout, on macOS or Linux with OpenSSL. Choose a new private directory outside Git for the backup.

```sh
bash winget/create-signing-key.sh "$HOME/hexor-winget-signing"
cd "$HOME/hexor-winget-signing"
openssl base64 -A -in hexor-winget.pfx | gh secret set WINGET_PFX_BASE64 -R house-of-vanity/arch_repo
gh secret set WINGET_PFX_PASSWORD -R house-of-vanity/arch_repo < pfx-password
gh workflow run publish-winget.yml -R house-of-vanity/arch_repo -f repository=house-of-vanity/tsunagi -f tag=v1.0.3
```

Keep the password and encrypted PFX in your private backup. The five-year RSA certificate has the Code Signing EKU and subject `CN=Hexor WinGet`, matching the source MSIX publisher. Record the printed SHA-256 of the public DER certificate for client enrollment. Preserve the same publisher on renewal and distribute the replacement certificate before using it to sign. The job exports the public certificate to OpenArtifact. Its upload identity comes from GitHub OIDC and the `github-winget-publish` policy on OpenArtifact.

## Add a Windows client

Copy `hexor-winget.cer` from the administrator, or download it from the source and compare its SHA-256 with the value supplied separately by the administrator. In elevated PowerShell, run:

```powershell
Get-FileHash .\hexor-winget.cer -Algorithm SHA256
Import-Certificate -FilePath .\hexor-winget.cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople
winget source add --name hexor --type Microsoft.PreIndexed.Package --arg https://repo.hexor.cy/repos/raw/hexor-winget
winget install --source hexor --id Hexor.Tsunagi --exact
winget upgrade --source hexor --id Hexor.Tsunagi --exact
```

## Publish from another CI

Register the project once in `winget/packages.json` with its standard WinGet fields and one HTTPS installer URL template per architecture. Use `{tag}` for the build tag and `{version}` for the version after removing a leading `v`. The Tsunagi entry is a working example. Any CI that serves built installers at those URLs can send the same HTTP request. Give it a fine-grained GitHub token scoped to `house-of-vanity/arch_repo` with **Actions: write**. Send the event after all release assets are downloadable.

```sh
curl --fail-with-body -X POST \
  -H "Authorization: Bearer $DISPATCH_TOKEN" \
  -H 'X-GitHub-Api-Version: 2026-03-10' \
  --json '{"ref":"main","inputs":{"repository":"house-of-vanity/tsunagi","tag":"v1.0.3"}}' \
  https://api.github.com/repos/house-of-vanity/arch_repo/actions/workflows/publish-winget.yml/dispatches
```

The response contains a run ID and link. **Actions → Publish WinGet repository** reports publication and verifies the exact version using the Windows client. You can retry a tag there without rebuilding the installer. The catalog mirrors each installer by SHA-256, retains prior versions, and rejects different bytes under a published version. One serialized publisher uploads manifests and WinGet v2 metadata before switching the signed indexes. The OpenArtifact raw repository must allow replacing `source.msix` and `source2.msix` at their fixed URLs. [GitHub workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)

The publisher uses Python's standard library, PowerShell and the Windows SDK on a GitHub-hosted Windows runner. The Microsoft index generator comes from a SHA-256-pinned build of winget-cli. [Index generator source](https://github.com/microsoft/winget-cli/blob/v1.29.240/src/WinGetSourceCreator/WinGetLocalSource.cs) · [Pinned tool release](https://github.com/pl4nty/winget-pkgs-selfhost/releases/tag/v1.29.240)
