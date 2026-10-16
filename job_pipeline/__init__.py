"""Job Data Collection Pipeline.

A modular Python package that fetches job postings from one or more sources,
normalizes them into a single schema, deduplicates on job URL, and persists the
result as JSON Lines plus a CSV export (locally or to Amazon S3).
"""

__version__ = "1.0.0"
