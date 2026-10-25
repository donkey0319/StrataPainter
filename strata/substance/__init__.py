"""Substance 3D Painter interoperability: read .spp projects, .spsm smart materials and .spmsk smart
masks, and turn them into Strata layers.

  spfile.py    HDF5 container access, embedded .image decoding, shelf thumbnails
  qt.py        Qt QDataStream values (settings, image headers, metadata)
  hbo.py       Painter's HBO object streams (layer stacks, documents)
  assbin.py    the mesh embedded in .spp projects
  convert.py   Painter layer tree -> Strata layers (+ a report of what was approximated)
  importer.py  load_smart_material / load_smart_mask / inspect_project / load_project
  replay.py    replays recorded paint strokes with Strata's brush (GPU)
  library.py   finds Painter's starter and user smart materials / masks for the Assets panel

Only reading is supported. Requires h5py (pip install h5py).
"""
