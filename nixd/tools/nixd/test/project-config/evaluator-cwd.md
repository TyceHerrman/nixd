# RUN: python3 %S/evaluator-cwd.py root-uri
# RUN: python3 %S/evaluator-cwd.py root-path
# RUN: python3 %S/evaluator-cwd.py launch

Each real server loads an expression containing `import ./nixpkgs.nix`. The
hand-written imported value becomes observable through hover only when the
evaluator child runs from the selected `rootUri`, non-empty `rootPath`, or the
captured launch-directory fallback.
