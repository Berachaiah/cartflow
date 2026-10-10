"""
Background/asynchronous job definitions (PRD Ch.12 sec 24).
Each job needs: an idempotency key, a retry policy with backoff, a max
attempt count, and failure logging into `background_jobs` (see
models/system.py once it exists).
"""
