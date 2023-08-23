# arch_repo

Change me.hexor.ru to your host name.

Copy *.zst* package to `x86_64` and run `repo-add  me.hexor.ru.db.tar.gz *.zst  -s` for updating DB and signing GPG.

Commit to repo and enable gitlab pages to main branch.

Enable new repo `/etc/pacman.conf`

```ini
[me.hexor.ru]
SigLevel = Optional TrustAll
Server = https://me.hexor.ru/arch_repo/x86_64/
```
