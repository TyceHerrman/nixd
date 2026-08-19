# RUN: python3 %S/completion-overflow.py

This real-server test preserves capped completion items and independent
incomplete flags for inactive static completion, current nixpkgs completion,
and an oversized nixpkgs response that becomes stale while withheld by the
transparent worker proxy.
