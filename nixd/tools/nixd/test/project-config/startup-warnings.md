# RUN: python3 %S/startup-warnings.py missing
# RUN: python3 %S/startup-warnings.py io
# RUN: python3 %S/startup-warnings.py io-directory
# RUN: python3 %S/startup-warnings.py json
# RUN: python3 %S/startup-warnings.py schema
# RUN: python3 %S/startup-warnings.py invalid-cli

These real-server cases distinguish a silent missing file from invalid existing
files. Invalid files must log their exact path and reason during initialization,
remain silent on the LSP channel until `initialized`, warn exactly once, and
continue serving requests with built-in defaults. An explicit empty CLI config
remains fatal.
