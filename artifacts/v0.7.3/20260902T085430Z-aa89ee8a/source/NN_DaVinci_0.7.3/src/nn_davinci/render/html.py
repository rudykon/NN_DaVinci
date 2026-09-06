from __future__ import annotations

import json
import html
from typing import Any

from ..ir import GraphIR
from ..layout import LayoutResult
from .svg import SvgRenderer


class HtmlRenderer:
    def render(self, graph: GraphIR, layout: LayoutResult, theme: dict[str, Any], *, title: str | None = None, **options: Any) -> str:
        safe_graph = graph.copy()
        for node in safe_graph.nodes:
            for key in ("icon_href", "image_href"):
                if key in node.attributes and not _safe_embedded_image(node.attributes[key]):
                    node.attributes.pop(key)
        for annotation in safe_graph.annotations:
            if annotation.kind == "image" and not _safe_embedded_image(annotation.style.get("href")):
                annotation.style.pop("href", None)
        svg = SvgRenderer().render(safe_graph, layout, theme, title=title, publication=False, **options)
        graph_data = (
            json.dumps(graph.to_dict(), ensure_ascii=False)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-nndv-static'; base-uri 'none'; object-src 'none'">
<title>{html.escape(title or graph.name)}</title><style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:{theme['background']};font-family:{theme['font_family']}}}
#stage{{width:100%;height:100%;display:grid;place-items:center}}svg{{width:100%;height:100%}}.node{{cursor:pointer}}.node:hover .node-body{{stroke:{theme['accent']};stroke-width:3}}
.flow .edge path{{stroke-dasharray:9 7;animation:flow 1.1s linear infinite}}@keyframes flow{{to{{stroke-dashoffset:-32}}}}
#controls{{position:fixed;top:12px;left:12px;display:flex;gap:6px;z-index:3}}button{{padding:7px 10px;border:1px solid #ccd3df;background:white;border-radius:7px}}
#info{{position:fixed;right:12px;top:12px;width:230px;background:white;border:1px solid #ccd3df;border-radius:9px;padding:12px;box-shadow:0 8px 30px #0002;display:none}}
</style></head><body><div id="controls"><button id="animate">Animate flow</button><button id="fit">Fit</button></div><div id="stage">{svg}</div><aside id="info"></aside>
<script type="application/json" id="graph-data">{graph_data}</script><script nonce="nndv-static">
const graph=JSON.parse(document.getElementById('graph-data').textContent),svg=document.querySelector('svg'),stage=document.getElementById('stage');
document.getElementById('animate').onclick=()=>svg.classList.toggle('flow');document.getElementById('fit').onclick=()=>svg.removeAttribute('style');
document.querySelectorAll('.node').forEach(el=>el.onclick=()=>{{
  const n=graph.nodes.find(v=>v.id===el.dataset.nodeId),info=document.getElementById('info');
  const title=document.createElement('b'),type=document.createElement('p'),path=document.createElement('small'),parameters=document.createElement('p');
  title.textContent=n.name;type.textContent=n.op_type;path.textContent=n.path||'';parameters.textContent=`${{(n.parameters||0).toLocaleString()}} parameters`;
  info.replaceChildren(title,type,path,parameters);info.style.display='block';
}});
</script></body></html>'''


def _safe_embedded_image(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return lowered.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/gif;base64,", "data:image/webp;base64,"))
