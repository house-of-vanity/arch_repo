# Private Arch Linux Repo

It's Arch Linux repository for my own packages.
---

[x86_64 list](x86_64/)

# Run you own

Using *GitHub Pages* for hosting is nice. Just enable it in repo settings and optionally set up your own domain.

--Change btwiusearch.net to your host name--

Copy *.zst* package to `x86_64` and run `repo-add  btwiusearch.net.db.tar.gz *.zst  -s` for updating DB and signing GPG.

Commit to repo and enable gitlab pages to main branch.

Enable new repo `/etc/pacman.conf`

```ini
[btwiusearch.net]
SigLevel = Optional TrustAll
Server = https://btwiusearch.net/arch_repo/x86_64/
```
