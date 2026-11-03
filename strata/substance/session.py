"""Durable whole-stroke replay checkpoints. A partial stroke is never published."""
import copy
import hashlib
from .report import job_dict,job_load


def create(engine,pending):
    tasks=[]
    for ts,layer,jobs,mask in pending:
        for job in jobs:
            for stroke in job.strokes:
                single=copy.copy(job)
                single.strokes=[stroke]
                tasks.append({"set_pid":ts.pid,"layer_pid":layer.pid,"mask":mask,"job":job_dict(single)})
    state={"schema":1,"tasks":tasks,"next":0,"dabs":0,"skipped":0,"status":"pending","checkpoint":""}
    state["checkpoint"]=fingerprint(engine,state)
    return state


def validate(state):
    if not isinstance(state,dict) or state.get("schema")!=1 or not isinstance(state.get("tasks"),list):
        raise ValueError("Invalid import continuation state")
    if state.get("status") not in ("pending","budget","cancelled","complete"):
        raise ValueError("Invalid import continuation status")
    for key in ("next","dabs","skipped"):
        if type(state.get(key)) is not int or state[key]<0:raise ValueError("Invalid import continuation counter")
    if state["next"]>len(state["tasks"]) or len(state.get("checkpoint",""))!=64:
        raise ValueError("Invalid import continuation checkpoint")
    for task in state["tasks"]:
        if not isinstance(task,dict) or type(task.get("mask")) is not bool:
            raise ValueError("Invalid import replay task")
        for key in ("set_pid","layer_pid"):
            value=task.get(key)
            if not isinstance(value,str) or len(value)!=32 or any(c not in "0123456789abcdef" for c in value):raise ValueError("Invalid replay owner")
        job=job_load(task["job"])
        if len(job.strokes)!=1:raise ValueError("Replay task requires one complete stroke")
    return state


def targets(engine,state):
    for task in state["tasks"]:
        ts=next((s for s in engine.sets if s.pid==task["set_pid"]),None)
        layer=next((l for l in engine._walk(ts.layers) if l.pid==task["layer_pid"]),None) if ts else None
        if layer is None or ts.tiles is not None:raise ValueError("Replay target changed or is tiled; restore its checkpoint before continuing")
        yield ts,layer,task


def fingerprint(engine,state):
    h=hashlib.sha256()
    for key in ("positions","normals","indices","uvs"):h.update(getattr(engine.mesh,key).tobytes())
    seen=set()
    for ts,layer,task in targets(engine,state):
        key=(ts.pid,layer.pid,task["mask"])
        if key in seen:continue
        seen.add(key);h.update(str((key,ts.res,layer.kind)).encode())
        textures={"mask":layer.mask_tex} if task["mask"] else layer.tex
        for name,texture in sorted(textures.items()):
            h.update(name.encode());h.update(texture.read())
    return h.hexdigest()


def resume(engine,budget=150000,per_layer=40000,progress=None):
    from .replay import Replayer
    from .apply import ReplayStats
    if type(budget) is not int or budget<1 or type(per_layer) is not int or per_layer<1:
        raise ValueError("Replay budgets must be positive integers")
    state=engine.import_state
    if state is None:return 0
    validate(state)
    if state["status"]=="complete":return 0
    if fingerprint(engine,state)!=state["checkpoint"]:
        raise ValueError("Imported pixels, owners, mesh or resolution changed; restore the saved checkpoint before continuing")
    completed=0;layer_dabs={};state["status"]="pending"
    resolved=list(targets(engine,state))
    try:
        while state["next"]<len(resolved):
            ts,layer,task=resolved[state["next"]]
            remaining=min(budget-completed,per_layer-layer_dabs.get(layer.pid,0))
            if remaining<=0:state["status"]="budget";break
            def report(dabs):
                return progress((completed+dabs)/budget) if progress else True
            rp=Replayer(engine,ts,max_dabs=remaining,progress=report,seed_offset=state["dabs"])
            rp.replay(layer,[job_load(task["job"])],target_mask=task["mask"],budget=remaining)
            if not rp.complete:
                state["status"]="cancelled" if rp.cancelled else "budget"
                break
            completed+=rp.dabs;state["dabs"]+=rp.dabs;state["skipped"]+=rp.skipped
            layer_dabs[layer.pid]=layer_dabs.get(layer.pid,0)+rp.dabs
            state["next"]+=1;ts.dirty=True
        if state["next"]==len(resolved):state["status"]="complete"
    finally:
        state["checkpoint"]=fingerprint(engine,state)
        stats=ReplayStats();stats.dabs=state["dabs"];stats.skipped=state["skipped"]
        stats.truncated=state["status"]!="complete"
        engine.last_replay=stats;engine.dirty=True
        if completed:engine._edit_serial+=1
        for report in engine.import_reports[-1:]:report["replay"]={"status":state["status"],"truncated":stats.truncated,"completed_strokes":state["next"],"total_strokes":len(resolved),"dabs":state["dabs"],"skipped_strokes":state["skipped"]}
    return completed
