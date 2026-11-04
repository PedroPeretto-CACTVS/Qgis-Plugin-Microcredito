from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

_NUMBER_TEXT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
_COORDINATE = re.compile(
    rf"^\s*({_NUMBER_TEXT})\s+({_NUMBER_TEXT})(?:\s+{_NUMBER_TEXT}){{0,2}}\s*$"
)
_TYPE = re.compile(r"^\s*([A-Za-z]+)\b")
_AREA_HEADER = re.compile(
    r"^\s*(MULTIPOLYGON|POLYGON)(?:\s+(?:ZM|Z|M))?\s*(?=\()",
    re.IGNORECASE,
)
_POINT_HEADER = re.compile(
    r"^\s*POINT(?:\s+(?:ZM|Z|M))?\s*(?=\()",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AreaWktAnalysis:
    geometry: dict[str, Any] | None
    issue: str | None
    warnings: tuple[str, ...] = ()


def wkt_type(value: str) -> str:
    match = _TYPE.match(value)
    return match.group(1).upper() if match else ""


def _parse_group(text: str, position: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    token: list[str] = []
    expecting_separator = False
    position += 1
    while position < len(text):
        char = text[position]
        if char == "(":
            if "".join(token).strip() or expecting_separator:
                raise ValueError("WKT mistura coordenadas e grupos.")
            child, position = _parse_group(text, position)
            result.append(child)
            expecting_separator = True
        elif char == ")":
            if "".join(token).strip():
                if expecting_separator:
                    raise ValueError("WKT exige vírgula entre elementos.")
                result.append("".join(token).strip())
                expecting_separator = True
            if not expecting_separator:
                raise ValueError("WKT contém elemento vazio.")
            return result, position + 1
        elif char == ",":
            if "".join(token).strip():
                if expecting_separator:
                    raise ValueError("WKT exige vírgula entre elementos.")
                result.append("".join(token).strip())
                token = []
                expecting_separator = True
            if not expecting_separator:
                raise ValueError("WKT contém elemento vazio.")
            expecting_separator = False
            position += 1
        else:
            if expecting_separator:
                if char.isspace():
                    position += 1
                    continue
                raise ValueError("WKT exige vírgula entre elementos.")
            token.append(char)
            position += 1
    raise ValueError("WKT com parênteses incompletos.")


def _coordinates(items: list[Any]) -> Any:
    if not items:
        raise ValueError("WKT sem coordenadas.")
    if all(isinstance(item, str) for item in items):
        points: list[list[float]] = []
        for item in items:
            match = _COORDINATE.fullmatch(item)
            if not match:
                raise ValueError("Coordenada WKT inválida.")
            point = [float(match.group(1)), float(match.group(2))]
            if not all(math.isfinite(value) for value in point):
                raise ValueError("Coordenada WKT não finita.")
            points.append(point)
        return points
    if any(isinstance(item, str) for item in items):
        raise ValueError("WKT mistura coordenadas e grupos.")
    return [_coordinates(item) for item in items]


def _ring_issue(value: object) -> str | None:
    if not isinstance(value, list) or len(value) < 4:
        return "fewer_than_4_points"
    points = value
    if not all(
        isinstance(point, list)
        and len(point) == 2
        and all(isinstance(axis, float) for axis in point)
        for point in points
    ):
        return "invalid_coordinate_structure"
    if points[0] != points[-1]:
        return "open_ring"
    distinct_vertices = {tuple(point) for point in points[:-1]}
    if len(distinct_vertices) < 3:
        return "fewer_than_3_distinct_vertices"
    origin_x, origin_y = points[0]
    try:
        area_twice = math.fsum(
            (points[index][0] - origin_x) * (points[index + 1][1] - origin_y)
            - (points[index + 1][0] - origin_x) * (points[index][1] - origin_y)
            for index in range(len(points) - 1)
        )
    except (OverflowError, ValueError):
        return "zero_area"
    if not math.isfinite(area_twice) or math.isclose(area_twice, 0.0, abs_tol=1e-12):
        return "zero_area"
    return None


def _normalize_polygon(
    value: object,
) -> tuple[list[Any] | None, str | None, tuple[str, ...]]:
    if not isinstance(value, list) or not value:
        return None, "empty_polygon", ()
    exterior_issue = _ring_issue(value[0])
    if exterior_issue:
        if exterior_issue == "zero_area" and len(value) == 1:
            return None, "zero_area", ()
        return None, f"outer_{exterior_issue}", ()
    normalized = [value[0]]
    warnings: list[str] = []
    for ring in value[1:]:
        if issue := _ring_issue(ring):
            if issue == "zero_area":
                warnings.append("zero_area_hole_removed")
                continue
            return None, f"hole_{issue}", ()
        normalized.append(ring)
    return normalized, None, tuple(warnings)


def _area_parts(value: str) -> tuple[str, Any]:
    header = _AREA_HEADER.match(value)
    if not header:
        raise ValueError("unsupported_area_type")
    nested, end = _parse_group(value, header.end())
    if value[end:].strip():
        raise ValueError("trailing_content")
    return header.group(1).upper(), _coordinates(nested)


def analyze_area_wkt(value: str) -> AreaWktAnalysis:
    try:
        geometry_type, coordinates = _area_parts(value)
    except ValueError:
        return AreaWktAnalysis(None, "invalid_syntax")
    if geometry_type == "POLYGON":
        normalized, issue, polygon_warnings = _normalize_polygon(coordinates)
        if issue is not None or normalized is None:
            return AreaWktAnalysis(None, issue or "empty_polygon")
        return AreaWktAnalysis(
            {"type": "Polygon", "coordinates": normalized}, None, polygon_warnings
        )
    if not isinstance(coordinates, list) or not coordinates:
        return AreaWktAnalysis(None, "empty_multipolygon")
    normalized_polygons: list[Any] = []
    multipolygon_warnings: list[str] = []
    for polygon in coordinates:
        normalized, issue, polygon_warnings = _normalize_polygon(polygon)
        if issue == "zero_area":
            multipolygon_warnings.append("zero_area_component_removed")
            continue
        if issue is not None or normalized is None:
            return AreaWktAnalysis(None, f"component_{issue or 'empty_polygon'}")
        normalized_polygons.append(normalized)
        multipolygon_warnings.extend(polygon_warnings)
    if not normalized_polygons:
        return AreaWktAnalysis(None, "zero_area")
    return AreaWktAnalysis(
        {"type": "MultiPolygon", "coordinates": normalized_polygons},
        None,
        tuple(multipolygon_warnings),
    )


def parse_area_wkt(value: str) -> dict[str, Any]:
    analysis = analyze_area_wkt(value)
    if analysis.issue is not None or analysis.geometry is None:
        raise ValueError(f"Área WKT inválida: {analysis.issue or 'sem_geometria'}.")
    return analysis.geometry


def is_valid_point_wkt(value: str) -> bool:
    header = _POINT_HEADER.match(value)
    if not header:
        return False
    try:
        nested, end = _parse_group(value, header.end())
        coordinates = _coordinates(nested)
    except ValueError:
        return False
    return bool(
        not value[end:].strip()
        and isinstance(coordinates, list)
        and len(coordinates) == 1
        and isinstance(coordinates[0], list)
        and len(coordinates[0]) == 2
    )
