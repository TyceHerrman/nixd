# RUN: python3 %S/project_config_test.py selection

Project configuration is opt-in. When enabled, root selection is `rootUri`,
then `rootPath`, then the launch directory; it is exact rather than ancestral.
Explicit CLI configuration remains authoritative, including an explicit empty
value, and the help output warns that project configuration is trusted code.
