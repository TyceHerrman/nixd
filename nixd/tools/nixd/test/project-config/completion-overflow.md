# RUN: python3 %S/completion-overflow.py

This real-server test preserves capped completion items and independent
incomplete flags for inactive static completion, current nixpkgs completion,
static-overflow short-circuiting, the exact static-cap provider boundary, and a
nixpkgs response that becomes stale while withheld by the transparent worker
proxy.
