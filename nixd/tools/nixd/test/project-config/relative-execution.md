# RUN: python3 %S/project_config_test.py relative-execution

Project-relative evaluator imports and formatter commands run from the selected
workspace root. An unusable authoritative root warns and falls back to the
launch directory without loading its project file.
