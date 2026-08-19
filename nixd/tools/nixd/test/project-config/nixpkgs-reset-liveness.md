# RUN: python3 %S/nixpkgs-reset-liveness.py

This real-server test uses a transparent worker proxy to withhold an
old-generation nixpkgs response while resetting to an immutable base with no
nixpkgs expression. The reset and a subsequent inactive request must complete
before the response is released; after release, the old response must not
expose stale provider data.
