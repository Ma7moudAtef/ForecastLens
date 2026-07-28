"""Synthetic workbooks, generated on demand.

Nothing in here is committed as a spreadsheet. The repository allows exactly
one .xlsx (tests/fixtures/sample_public.xlsx); every other fixture is built
from code into a temporary directory when a test asks for it, so a synthetic
shape can never be confused with — or become a hiding place for — real data.
"""
