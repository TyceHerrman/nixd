# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --lit-test < %t | FileCheck %s

This catches an unconditional project-file load: a `.nixd.json` must have no
effect until `--enable-project-config` is supplied.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": {
    "processId": 123,
    "rootUri": "file://ROOT",
    "capabilities": {}
  }
}
```

```nix file:///project-disabled.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///project-disabled.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

```
# The built-in formatter, not the project formatter.
CHECK: "id": 2,
CHECK-NOT: project-format
```

```json
{"jsonrpc":"2.0","method":"exit"}
```
