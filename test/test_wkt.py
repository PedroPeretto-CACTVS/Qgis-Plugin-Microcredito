from __future__ import annotations

import unittest

from qgis_plugin_microcredito.domain.wkt import analyze_area_wkt, parse_area_wkt


class WktAreaTests(unittest.TestCase):
    def test_preserves_small_square_away_from_origin(self):
        # Side 8e-7 gives area 6.4e-13, above the existing 5e-13 cutoff.
        geometry = parse_area_wkt(
            "POLYGON ((60 50,60.0000008 50,60.0000008 50.0000008,60 50.0000008,60 50))"
        )

        self.assertEqual(
            geometry,
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [60.0, 50.0],
                        [60.0000008, 50.0],
                        [60.0000008, 50.0000008],
                        [60.0, 50.0000008],
                        [60.0, 50.0],
                    ]
                ],
            },
        )

    def test_nonfinite_area_arithmetic_returns_analysis_instead_of_raising(self):
        for wkt in (
            "POLYGON ((0 0,1e308 0,0 1e308,1e308 1e308,0 0))",
            "POLYGON ((0 0,1e154 0,1e154 1e154,0 1e154,0 0))",
        ):
            with self.subTest(wkt=wkt):
                analysis = analyze_area_wkt(wkt)

                self.assertEqual(analysis.issue, "zero_area")
                self.assertIsNone(analysis.geometry)

    def test_small_square_remains_valid_after_translation_and_ring_reordering(self):
        for ring in (
            "0 0,0.0000008 0,0.0000008 0.0000008,0 0.0000008,0 0",
            "60 50,60.0000008 50,60.0000008 50.0000008,60 50.0000008,60 50",
            "-60 -50,-59.9999992 -50,-59.9999992 -49.9999992,-60 -49.9999992,-60 -50",
            "60 50,60 50.0000008,60.0000008 50.0000008,60.0000008 50,60 50",
            "60.0000008 50,60.0000008 50.0000008,60 50.0000008,60 50,60.0000008 50",
        ):
            with self.subTest(ring=ring):
                analysis = analyze_area_wkt(f"POLYGON (({ring}))")

                self.assertIsNone(analysis.issue)
                self.assertIsNotNone(analysis.geometry)
                self.assertEqual(analysis.warnings, ())

    def test_preserves_small_nonzero_hole_away_from_origin(self):
        analysis = analyze_area_wkt(
            "POLYGON ((60 50,60.000004 50,60.000004 50.000004,60 50.000004,60 50),"
            "(60.000001 50.000001,60.0000018 50.000001,"
            "60.0000018 50.0000018,60.000001 50.0000018,60.000001 50.000001))"
        )

        self.assertIsNone(analysis.issue)
        self.assertEqual(analysis.warnings, ())
        self.assertIsNotNone(analysis.geometry)
        assert analysis.geometry is not None
        self.assertEqual(len(analysis.geometry["coordinates"]), 2)
        self.assertEqual(
            analysis.geometry["coordinates"][1],
            [
                [60.000001, 50.000001],
                [60.0000018, 50.000001],
                [60.0000018, 50.0000018],
                [60.000001, 50.0000018],
                [60.000001, 50.000001],
            ],
        )

    def test_still_removes_hole_below_existing_area_threshold(self):
        analysis = analyze_area_wkt(
            "POLYGON ((0 0,1 0,1 1,0 1,0 0),"
            "(0.1 0.1,0.1000008 0.1,0.1000008 0.1000005,"
            "0.1 0.1000005,0.1 0.1))"
        )

        self.assertIsNone(analysis.issue)
        self.assertEqual(analysis.warnings, ("zero_area_hole_removed",))
        self.assertIsNotNone(analysis.geometry)
        assert analysis.geometry is not None
        self.assertEqual(len(analysis.geometry["coordinates"]), 1)

    def test_multipolygon_keeps_small_components_and_removes_only_zero_area(self):
        analysis = analyze_area_wkt(
            "MULTIPOLYGON (((0 0,0.0000008 0,0.0000008 0.0000008,0 0.0000008,0 0)),"
            "((60 50,60.0000008 50,60.0000008 50.0000008,60 50.0000008,60 50)),"
            "((0 0,1 1,2 2,0 0)))"
        )

        self.assertIsNone(analysis.issue)
        self.assertEqual(analysis.warnings, ("zero_area_component_removed",))
        self.assertIsNotNone(analysis.geometry)
        assert analysis.geometry is not None
        self.assertEqual(analysis.geometry["type"], "MultiPolygon")
        self.assertEqual(len(analysis.geometry["coordinates"]), 2)
        self.assertEqual(analysis.geometry["coordinates"][1][0][0], [60.0, 50.0])

    def test_preserves_existing_twice_area_tolerance_boundary(self):
        for height, expected_issue in (
            ("4.9999999e-13", "zero_area"),
            ("5e-13", "zero_area"),
            ("5.0000001e-13", None),
        ):
            with self.subTest(height=height):
                analysis = analyze_area_wkt(
                    f"POLYGON ((0 0,1 0,1 {height},0 {height},0 0))"
                )

                self.assertEqual(analysis.issue, expected_issue)
                self.assertEqual(analysis.geometry is None, expected_issue is not None)

    def test_preserves_ring_and_format_rejections(self):
        for wkt, expected_issue in (
            ("POLYGON ((0 0,1 0,0 1))", "outer_fewer_than_4_points"),
            ("POLYGON ((0 0,1 0,0 1,1 1))", "outer_open_ring"),
            (
                "POLYGON ((0 0,1 0,1 0,0 0))",
                "outer_fewer_than_3_distinct_vertices",
            ),
            ("POLYGON ((0 0,1 1,2 2,0 0))", "zero_area"),
            ("POLYGON ((0 0,1 0,no 1,0 0))", "invalid_syntax"),
            ("POLYGON ((0 0,1e999 0,0 1,0 0))", "invalid_syntax"),
            ("POLYGON ((0 0,1 0,0 1,0 0)) trailing", "invalid_syntax"),
        ):
            with self.subTest(wkt=wkt):
                analysis = analyze_area_wkt(wkt)

                self.assertEqual(analysis.issue, expected_issue)
                self.assertIsNone(analysis.geometry)
