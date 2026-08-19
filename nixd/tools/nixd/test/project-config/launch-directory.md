# RUN: cd %S/fixtures/launch && nixd --enable-project-config --lit-test < %s | FileCheck %s

This catches root selection that omits the captured launch directory when both
rootUri and rootPath are absent or empty.

<-- initialize(0)

```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": { "processId": 123, "rootPath": "", "capabilities": {} }
}
```

```nix file:///launch-directory.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "textDocument/formatting",
  "params": {
    "textDocument": { "uri": "file:///launch-directory.nix" },
    "options": { "tabSize": 2, "insertSpaces": true }
  }
}
```

```
CHECK: "id": 2,
CHECK: "newText": "launch-format"
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
