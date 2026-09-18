"""Tests for the exploratory helpers.

The previous version of this file did not parse:

    from etl.cleaning import clean_data

        data = pd.read_csv("/Users/tingtinghe/Documents/brerc-dashboard/data/varied_sample.csv")

- the indented line was an IndentationError, so the whole module failed to import
  and broke `unittest discover` for the package;
- the path pointed at one person's machine, so it could not run anywhere else;
- it read from `data/`, which is git-ignored and empty on a fresh clone.

Rewritten to use an in-memory frame, and to skip cleanly when pandas is absent so
the ETL suite stays runnable with the standard library alone.
"""

from __future__ import annotations

import unittest
import warnings

try:
    import pandas as pd

    HAVE_PANDAS = True
except ImportError:  # pragma: no cover - environment dependent
    HAVE_PANDAS = False

from etl.cleaning import clean_data, describe_dataset


@unittest.skipUnless(HAVE_PANDAS, "pandas is not installed")
class TestDescribeDataset(unittest.TestCase):
    def frame(self):
        return pd.DataFrame(
            {
                "RecordKey": ["1", "2"],
                "SPECIES_No": [999999, 2028],
                "GridRef": ["ST585725", "ST587721"],
                "RecordDate": ["2000", "2011"],
            }
        )

    def test_returns_a_structural_summary(self):
        summary = describe_dataset(self.frame())
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["columns"], ["RecordKey", "SPECIES_No", "GridRef", "RecordDate"])
        self.assertEqual(summary["non_null"]["GridRef"], 2)
        self.assertEqual(summary["distinct"]["GridRef"], 2)

    def test_it_does_not_leak_record_content(self):
        # The original printed df.head(), which puts real grid references, place
        # names, recorder attributions and comments into stdout - and therefore
        # into CI logs, terminal scrollback and any log aggregator. A diagnostic
        # helper must not be the thing that leaks the data the pipeline protects.
        rendered = str(describe_dataset(self.frame()))
        self.assertNotIn("ST585725", rendered)
        self.assertNotIn("2028", rendered)

    def test_it_prints_nothing(self):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            describe_dataset(self.frame())
        self.assertEqual(buffer.getvalue(), "")

    def test_it_performs_no_cleaning(self):
        # Explicitly documents that this helper is NOT the safety boundary: it
        # neither gates a sensitive species nor generalises a fine reference. It
        # reports what is in the frame and changes nothing.
        df = self.frame()
        describe_dataset(df)
        self.assertIn(2028, list(df["SPECIES_No"]))
        self.assertIn("ST585725", list(df["GridRef"]))


@unittest.skipUnless(HAVE_PANDAS, "pandas is not installed")
class TestDeprecatedAlias(unittest.TestCase):
    def test_clean_data_warns(self):
        df = pd.DataFrame({"a": [1]})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            clean_data(df)
        self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))


class TestModuleImports(unittest.TestCase):
    def test_this_file_parses(self):
        # The previous version did not; `unittest discover` failed on import.
        self.assertTrue(callable(describe_dataset))


if __name__ == "__main__":
    unittest.main(verbosity=1)
