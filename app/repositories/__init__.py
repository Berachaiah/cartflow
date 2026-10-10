"""
Data-access layer (PRD Ch.12 sec 5 "Repository layer"). Repositories:
  - Perform database reads/writes only.
  - Avoid embedding business decisions (that belongs in services/).
  - Expose reusable, composable query methods.

One repository module per model, subclassing BaseRepository from base.py.
"""
