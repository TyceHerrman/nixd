# RUN: python3 %S/interactive-overlay.py | FileCheck %s

This uses a request/response-synchronous client because the Markdown transport
eagerly submits its entire transcript. It proves that a null array entry resets
a prior editor formatter override to the immutable CLI base.

```
CHECK: interactive [null] reset: cli
```
