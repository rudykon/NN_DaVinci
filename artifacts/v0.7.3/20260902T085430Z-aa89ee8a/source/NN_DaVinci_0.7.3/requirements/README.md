# Rebuilding the 0.2.2 verification environment

The library dependency ranges remain in `pyproject.toml`.  This directory pins
the exact environment used for the 2026-08-25 release evidence.

```bash
python3.13 -m venv ../envs/python-tools
../envs/python-tools/bin/python -m pip install \
  -c requirements/verification-linux-x86_64-py313-0.2.2.lock '.[all]'
../envs/python-tools/bin/python -m pip install --target .devtools \
  coverage==7.10.6 mypy==1.17.1 ruff==0.12.11 build==1.3.0
npm ci --ignore-scripts
```

The `verification-linux-x86_64-py313-0.2.2.lock` file is an exact transitive
lock for the recorded Linux x86_64 / CPython 3.13 verification host, not a
universal cross-platform lock. `verification/verification-lock-metadata-0.2.2.json`
records its roots, index source and the fact that installed distributions did
not retain reusable wheel files; newly built project wheel/sdist hashes are in
each sealed packaging report.

Chrome, Poppler (`pdffonts`) and TeX Live are system executables recorded with
their versions and are not installed by this project.
