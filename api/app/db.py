"""
Database connection for the API (B0).

Keeps the connection details in ONE place, read from an environment variable,
so that moving from your laptop to a real server is a credentials change only
(no code change) — that is decision D-005.

The API opens a connection per request and closes it. That is simple and correct
for B0; connection pooling comes later if it is needed.

SAFETY RULES enforced here and in every query:
  * queries read ONLY from the `public_occurrences` view, never the staging table
  * all SQL is parameterised (%s placeholders) — never string-formatted, which is
    how SQL injection happens
"""

import os

import psycopg
from psycopg.rows import dict_row

# Read the connection string from the environment. The fallback is a local
# development default — it contains no real secret.
#
# Format: postgresql://USER:PASSWORD@HOST:PORT/DATABASE
# Put your real one in a git-ignored .env file, never in this file.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/brerc_ui",
)


def get_connection() -> psycopg.Connection:
    """
    Open a connection to the UI database.

    `row_factory=dict_row` makes each returned row behave like a dictionary
    ({"scientific_name": "...", ...}) instead of a plain tuple, which makes the
    endpoint code much easier to read.
    """
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)
