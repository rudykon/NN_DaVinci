# Plugin API

NN_DaVinci discovers Python entry points in these groups:

- `nn_davinci.adapters`
- `nn_davinci.layouts`
- `nn_davinci.analyzers`
- `nn_davinci.themes`
- `nn_davinci.exporters`
- `nn_davinci.operators`

A local plugin can also provide `nn-davinci-plugin.json`:

```json
{
  "name": "my-layout",
  "version": "0.1.0",
  "api_version": "1.0",
  "capabilities": ["layout"],
  "entry_point": "my_layout.plugin:create_plugin",
  "description": "A domain-specific layout"
}
```

Major API versions must match. Discovery reads metadata only; `PluginManager.load()` is the
explicit code-execution boundary. Load errors report the plugin, entry point and original error.
Adapters additionally declare fine-grained capabilities such as shapes, hierarchy, parameters,
runtime capture and dynamic dimensions.

Operator plugins return a mapping from operator names to semantic specifications, for example
`{"FlashAttention": {"category": "attention", "icon": "attention"}}`. Adapters then resolve
that operator into the registered category and the generic renderer remains usable even when a
plugin does not provide a custom drawing primitive.

A runnable local template is provided at `examples/plugins/paper_style/`. Local manifests may
point to a sibling Python file such as `plugin.py:create_plugin`; NN_DaVinci resolves that file
without requiring a package installation. Loading remains explicit because plugin code is trusted
Python code.

From the CLI, discovery and loading are explicit:

```bash
nnviz --plugin-path ./plugins --plugin my-layout render model.onnx --layout my-layout
```
