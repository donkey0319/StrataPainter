"""Explicit API v1 example; never autoloaded from projects or delivery archives."""
STRATA_EXTENSION_API = 1


def register(registry):
    def tint(engine, color=(0.7, 0.2, 0.1)):
        if engine.layer is None:
            raise ValueError("Select a layer before tinting")
        return engine.set_properties(engine.layer, color=list(color))
    registry.register("example.tint", tint, "Set the selected native layer color")
