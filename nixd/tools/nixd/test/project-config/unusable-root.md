# RUN: python3 %S/unusable-root.py root-uri
# RUN: python3 %S/unusable-root.py root-path
# RUN: python3 %S/unusable-root.py root-path-inaccessible

A nonexistent or inaccessible supplied root must log the supplied path, remain
silent before `initialized`, warn exactly once afterward, skip the conflicting
launch-root project file, and run both evaluator and formatter children from
the captured launch directory. `rootUri` remains authoritative over a usable
`rootPath`.
