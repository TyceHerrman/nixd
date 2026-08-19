# RUN: nixd --help | FileCheck %s

```
CHECK: --enable-project-config
CHECK-SAME: trusted project configuration may evaluate Nix and execute formatter commands
```
