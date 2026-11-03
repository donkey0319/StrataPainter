"""Discovery only: external graph execution is an isolated, opt-in future adapter."""
import shutil


def probe():
    commands={name:shutil.which(name) for name in ("sbsrender","sbsbaker","sbsupdater")}
    return {"commands":commands,"discovered":any(commands.values()),"execution_enabled":False,
            "reason":"No validated external runtime adapter is configured; installation, API, licensing and redistribution must be qualified before enabling execution.",
            "fallbacks":["native_graph_v1","embedded_bitmaps","reported_approximation"]}
