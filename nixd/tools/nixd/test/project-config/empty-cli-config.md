# RUN: not nixd --config= --lit-test < %s

An explicit empty --config value is a supplied CLI source and therefore must
be parsed (and rejected), rather than treated as if --config were absent.

<-- initialize(0)

```json
{ "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": { "processId": 123, "rootPath": "", "capabilities": {} } }
```
