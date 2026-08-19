# RUN: python3 %S/project_config_test.py startup-warnings

Missing project files are silent. Unreadable, malformed, and schema-invalid
files report their literal reason after `initialized`, exactly once, while the
server continues with built-in defaults.
