# RUN: python3 %S/nixpkgs-visibility-reset.py

This real-server test proves that an accepted editor nixpkgs override is
visible while active, but is no longer observable through any nixpkgs-backed
language feature after a complete empty-base reset. An omitted nixpkgs patch
must keep it inactive, while an invalid reply must retain an active override.
