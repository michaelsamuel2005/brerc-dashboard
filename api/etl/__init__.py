"""BRERC public-data safety boundary.

Import modules as ``etl.pipeline``, ``etl.policy`` and so on. Keeping this a real
package ensures the same imports work in tests, an installed wheel and the
future FastAPI process, rather than depending on the current working directory.
"""
