# RUN: mkdir %t-root && touch %t-root/.nixd.json && chmod 000 %t-root && sed 's|ROOT|%t-root|g' %s > %t-input && nixd --enable-project-config --lit-test < %t-input | FileCheck %s && chmod 700 %t-root && rm -rf %t-root

This creates an existing unreadable project configuration path. Initialization
must retain the built-in configuration after recording a structured I/O error;
it must not let filesystem status exceptions escape.

<-- initialize(0)

```json
{ "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": { "processId": 123, "rootPath": "ROOT", "capabilities": {} } }
```

```nix file:///project-config-io-error.nix
{ x = 1; }
```

<-- textDocument/formatting(2)

```json
{ "jsonrpc": "2.0", "id": 2, "method": "textDocument/formatting", "params": { "textDocument": { "uri": "file:///project-config-io-error.nix" }, "options": { "tabSize": 2, "insertSpaces": true } } }
```

```
CHECK: "id": 2,
```

```json
{ "jsonrpc": "2.0", "method": "exit" }
```
