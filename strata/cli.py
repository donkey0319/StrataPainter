"""Headless batch delivery CLI. GUI startup remains run.py."""
import argparse
from contextlib import contextmanager,redirect_stdout
import json
import os
from pathlib import Path
import sys
import tempfile
from .extensions import API_VERSION,builtins,load_extension


@contextmanager
def engine_session():
    import moderngl
    from .engine import Engine
    ctx=moderngl.create_standalone_context(require=330);engine=Engine(ctx)
    try:yield engine
    finally:
        engine._release_project();engine.resources.release();engine.gpu.release_scratch();ctx.release()


def run_job(engine,job,registry=None,base=None):
    registry=registry or builtins();base=Path(base or Path.cwd()).resolve()
    if not isinstance(job,dict) or set(job)-{"version","steps"} or job.get("version")!=API_VERSION or not isinstance(job.get("steps"),list) or not 1<=len(job["steps"])<=64:raise ValueError("Batch v1 requires 1..64 steps")
    steps=[]
    for step in job["steps"]:
        if not isinstance(step,dict) or set(step)-{"command","params"}:raise ValueError("Invalid batch step")
        command=step.get("command");params=step.get("params",{})
        registry.validate(command,params);params=dict(params)
        if command.partition(".")[0] in ("project","textures","delivery"):
            for key in ("path","folder"):
                if key in params:params[key]=str((base/params[key]).resolve())
            if command=="project.new" and "mesh" in params:
                from .mesh import BUILTIN_MESHES
                if params["mesh"] not in BUILTIN_MESHES:params["mesh"]=str((base/params["mesh"]).resolve())
            if command=="textures.export" and isinstance(params.get("template"),str) and params["template"].endswith(".json"):
                params["template"]=str((base/params["template"]).resolve())
        steps.append((command,params))
    results=[]
    for index,(command,params) in enumerate(steps):
        try:results.append({"command":command,"result":registry.execute(engine,command,params)})
        except Exception as error:raise RuntimeError(f"Step {index+1} ({command}) failed: {error}") from error
    return {"version":API_VERSION,"results":results}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--extension",action="append",default=[],help="Explicitly import a trusted API v1 Python module")
    commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("commands",help="List built-in/explicit extension signatures")
    commands.add_parser("capabilities",help="Probe optional render/particle packages without creating GL")
    batch=commands.add_parser("batch",help="Execute a versioned JSON job");batch.add_argument("job")
    render=commands.add_parser("render",help="Render a Blender delivery ZIP using optional Cycles")
    render.add_argument("bundle");render.add_argument("output");render.add_argument("--size",type=int,default=512);render.add_argument("--samples",type=int,default=32);render.add_argument("--backend",default="blender_cycles")
    args=parser.parse_args(argv)
    try:
        registry=builtins()
        for module in args.extension:
            with redirect_stdout(sys.stderr):load_extension(registry,module)
        if args.command=="commands":result={"api_version":API_VERSION,"commands":registry.describe()}
        elif args.command=="capabilities":
            from .offline import capabilities
            result=capabilities()
        elif args.command=="render":
            from .offline import render_bundle
            result=render_bundle(args.bundle,args.output,args.size,args.samples,args.backend)
        else:
            path=Path(args.job).resolve()
            if path.stat().st_size>1024**2:raise ValueError("Batch input exceeds 1 MiB")
            def invalid(value):raise ValueError("Non-finite JSON constant: "+value)
            job=json.loads(path.read_text(encoding="utf-8"),parse_constant=invalid)
            with tempfile.TemporaryDirectory(prefix="strata-batch-") as cache:
                previous=os.environ.get("STRATA_RESOURCE_CACHE");os.environ.setdefault("STRATA_RESOURCE_CACHE",cache)
                try:
                    with redirect_stdout(sys.stderr),engine_session() as engine:result=run_job(engine,job,registry,path.parent)
                finally:
                    if previous is None:os.environ.pop("STRATA_RESOURCE_CACHE",None)
        print(json.dumps(result,indent=2,allow_nan=False));return 0
    except Exception as error:
        print(json.dumps({"error":str(error)},ensure_ascii=True),file=sys.stderr);return 2
