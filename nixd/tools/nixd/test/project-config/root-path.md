# RUN: sed 's|ROOT|%S/fixtures/project|g' %s > %t && nixd --enable-project-config --lit-test < %t | FileCheck %s

This catches failure to use a non-empty legacy `rootPath` when `rootUri` is
absent.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": {
    "processId": 123,
    "rootPath": "ROOT",
    "capabilities": {}
  }
}
```

```nix file:///project-root-path.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///project-root-path.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

```
CHECK: "newText": "project-format"
```

```json
{"jsonrpc":"2.0","method":"exit"}
```
