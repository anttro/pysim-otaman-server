# pysim-otaman-server — MOVED

This project has been merged into the [otaman](https://github.com/anttro/otaman) monorepo.

The server package (`pysim_otaman_server/`) now lives at the root of the
`otaman` repository, alongside the PWA (`frontend/`). The server also serves
the PWA itself, so one process serves UI + API on a single origin.

Please use:

```sh
git clone https://github.com/anttro/otaman.git
cd otaman
./setup.sh   # or setup.bat on Windows
./start.sh   # or start.bat
```

This repository is archived and no longer maintained.
