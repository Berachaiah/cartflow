"""Training-side package: nothing here is imported by the web app.

Kept as a package so the trainer runs as `python -m ml.train_ranker` from the
repository root — with the root on `sys.path`, `import app.*` resolves and the
trainer can reuse the serving code (`app.services.ranking.features_for`) instead
of keeping a second copy of the feature maths.
"""
