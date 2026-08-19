# RUN: python3 %S/project_config_test.py workspace-overlay

Editor configuration is an overlay over immutable CLI or project-file bases.
Null and empty-object resets rebuild that base; malformed and failed responses
retain the active overlay rather than silently replacing it.
