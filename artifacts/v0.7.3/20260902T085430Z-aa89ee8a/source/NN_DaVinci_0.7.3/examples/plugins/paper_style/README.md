# NN_DaVinci plugin API 2 template

This minimal local theme plugin declares API and capability versions in
`nn-davinci-plugin.json`. Local plugins execute Python in the editor process;
they are not sandboxed, are never downloaded by NN_DaVinci, and require an
explicit `allow_local_code=True` confirmation after source review.

```python
from nn_davinci.plugins import PluginManager

plugins = PluginManager()
plugins.discover(["examples/plugins"])
print(plugins.negotiate("paper-style-example"))
plugins.load("paper-style-example", allow_local_code=True)
```
