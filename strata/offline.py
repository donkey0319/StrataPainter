"""Optional isolated Blender/Cycles backend. No executable is required to paint/export."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from .bundleio import validate_archive


class BackendUnavailable(RuntimeError):
    pass


def capabilities():
    from .tangents import blender_path
    try:
        executable=blender_path()
        return {"blender_cycles":{"available":bool(executable),"executable":executable,"reason":None if executable else "Install Blender or set STRATA_BLENDER"},"particles":{"available":False,"reason":"Particle simulation brushes are a separate, unimplemented optional package"}}
    except (OSError,ValueError) as error:
        return {"blender_cycles":{"available":False,"executable":None,"reason":str(error)},"particles":{"available":False,"reason":"Particle simulation brushes are not implemented"}}


def render_bundle(bundle, output, size=512, samples=32, backend="blender_cycles", timeout=300):
    if backend!="blender_cycles":raise BackendUnavailable("Unsupported offline backend: "+backend)
    status=capabilities()[backend]
    if not status["available"]:raise BackendUnavailable(status["reason"])
    if type(size) is not int or not 16<=size<=4096 or type(samples) is not int or not 1<=samples<=1024:raise ValueError("Render limits: 16..4096 pixels and 1..1024 samples")
    destination=Path(output).resolve()
    if destination.suffix.lower()!=".png":raise ValueError("Offline output must be PNG")
    bundle=Path(bundle).resolve();validate_archive(bundle)
    root=os.environ.get("STRATA_RESOURCE_CACHE")
    if root:Path(root).mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="strata-offline-",dir=root) as temporary:
        work=Path(temporary);image=work/"render.png";environment=os.environ.copy()
        environment.update(BLENDER_USER_CONFIG=str(work/"config"),BLENDER_USER_SCRIPTS=str(work/"scripts"))
        process=subprocess.run([status["executable"],"--background","--factory-startup","--python",str(Path(__file__).with_name("blender_delivery.py")),"--",str(bundle),"--render",str(image),"--size",str(size),"--samples",str(samples)],env=environment,capture_output=True,text=True,timeout=timeout,creationflags=0x08000000 if os.name=="nt" else 0)
        if process.returncode or not image.is_file():raise RuntimeError("Blender render failed: "+(process.stderr+process.stdout)[-1800:])
        from .delivery import _publish
        _publish(destination,lambda path:path.write_bytes(image.read_bytes()))
        lines=[line for line in process.stdout.splitlines() if line.startswith("STRATA_DELIVERY_RESULT ")]
        result=json.loads(lines[-1].partition(" ")[2]) if lines else {}
        return dict(result,path=str(destination),render=str(destination),backend=backend)
