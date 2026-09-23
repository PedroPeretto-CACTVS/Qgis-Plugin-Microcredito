from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from qgis.core import (
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)

from qgis_plugin_microcredito.application.hashing import file_sha256
from qgis_plugin_microcredito.domain.base_catalog import definition_for


class AnalysisCancelled(RuntimeError):
    pass


def _check_cancel(cancel_check) -> None:
    if cancel_check is not None and cancel_check():
        raise AnalysisCancelled("Processamento cancelado pelo usuário.")


@dataclass(frozen=True)
class EnvironmentalSource:
    code: str
    name: str
    path: Path
    source_url: str
    attribute_candidates: tuple[str, ...] = ()
    regulatory_reference: str = ""
    review_guidance: str = ""


def default_sources(base_directory: str | Path) -> list[EnvironmentalSource]:
    base = Path(base_directory)

    def label(identifier: str, fallback: str) -> str:
        definition = definition_for(identifier)
        return definition.label if definition else fallback

    return [
        EnvironmentalSource(
            "embargos",
            label("embargos", "Embargos ambientais"),
            base / "embargos.gpkg",
            "https://dadosabertos.ibama.gov.br/dataset/termos-de-embargo",
            ("NUM_TAD", "NUM_EMBARGO", "SITUACAO", "DES_STATUS", "NOME_EMBARG"),
            "MCR 2-9 (embargos ambientais)",
            "Confirmar vigência, órgão emissor, vínculo com o imóvel/atividade e eventual exceção documental.",
        ),
        EnvironmentalSource(
            "terras_indigenas",
            label("terras_indigenas", "Terras indígenas"),
            base / "terras_indigenas.gpkg",
            "https://terrabrasilis.dpi.inpe.br/downloads/",
            ("terrai_nom", "fase_ti", "modalidade", "etnia_nome"),
            "MCR 2-9 (terras indígenas)",
            "Confirmar a delimitação oficial, a área contínua da atividade e a condição do beneficiário.",
        ),
        EnvironmentalSource(
            "territorios_quilombolas",
            label("territorios_quilombolas", "Territórios quilombolas"),
            base / "territorios_quilombolas.gpkg",
            "https://pamgia.ibama.gov.br/server/rest/services/BasesSincronizadas/lim_quilombos_incra_a/MapServer/0",
            ("nm_comunid", "nm_municip", "cd_uf", "st_titulad", "fase", "responsave"),
            "MCR 2-9 (territórios quilombolas)",
            "Confirmar delimitação, área contínua da atividade, condição do beneficiário e exceções documentais.",
        ),
        EnvironmentalSource(
            "unidades_conservacao",
            label("unidades_conservacao", "Unidades de conservação"),
            base / "unidades_conservacao.gpkg",
            "https://terrabrasilis.dpi.inpe.br/downloads/",
            ("nome_uc", "categoria", "grupo", "esfera", "orgao_gest"),
            "MCR 2-9 (unidades de conservação)",
            "Verificar categoria, plano de manejo, população tradicional e documentos que autorizem a atividade.",
        ),
        EnvironmentalSource(
            "florestas_publicas",
            label("florestas_publicas", "Florestas públicas"),
            base / "florestas_publicas.gpkg",
            "https://dados.florestal.gov.br/pt_BR/dataset/cadastro-nacional-de-florestas-publicas-cnfp",
            (
                "nome",
                "tipo",
                "categoria",
                "protecao",
                "governo",
                "classe",
                "orgao",
                "atolegal",
                "estagio",
                "observacao",
            ),
            "MCR 2-9 (florestas públicas tipo B)",
            "Confirmar Tipo B e avaliar as exceções: imóvel registrado ou, sob "
            "condições cumulativas, imóvel de até 15 módulos fiscais.",
        ),
        EnvironmentalSource(
            "desmatamento_pos_2020",
            label(
                "desmatamento_pos_2020", "Desmatamento PRODES após 2020"
            ),
            base / "desmatamento_pos_2020.gpkg",
            "https://terrabrasilis.dpi.inpe.br/downloads/",
            (
                "year",
                "image_date",
                "main_class",
                "class_name",
                "area_km",
                "source",
                "satellite",
            ),
            "MCR 2-9-17/18 (supressão de vegetação nativa)",
            "Esta camada atende ao recorte solicitado após 2020; a conformidade MCR exige avaliação desde 31/07/2019 e documentos de conformidade quando aplicáveis.",
        ),
    ]


def _load_layer(path: Path) -> QgsVectorLayer:
    layer = QgsVectorLayer(str(path), path.stem, "ogr")
    if layer.isValid():
        return layer
    # Permite que a pasta contenha o arquivo oficial sem exigir renomeação manual.
    if path.parent.is_dir():
        for pattern in (f"{path.stem}.shp", f"{path.stem}.geojson"):
            candidate = path.parent / pattern
            candidate_layer = QgsVectorLayer(str(candidate), candidate.stem, "ogr")
            if candidate_layer.isValid():
                return candidate_layer
    return layer


def _file_metadata(path: str | Path) -> dict[str, object]:
    candidate = Path(str(path).split("|", 1)[0])
    try:
        stat = candidate.stat()
        return {
            "arquivo_consultado": str(candidate),
            "arquivo_tamanho_bytes": int(stat.st_size),
            "arquivo_modificado_em": datetime.fromtimestamp(stat.st_mtime)
            .astimezone()
            .isoformat(timespec="seconds"),
        }
    except OSError:
        return {"arquivo_consultado": str(candidate)}


def source_files(source):
    path = next(
        (
            p
            for p in (
                source.path,
                source.path.with_suffix(".shp"),
                source.path.with_suffix(".geojson"),
            )
            if p.is_file()
        ),
        None,
    )
    if path is None:
        return []
    if path.suffix.lower() == ".shp":
        return sorted(p for p in path.parent.glob(path.stem + ".*") if p.is_file())
    return [path]


def source_signature(source):
    return tuple(
        (str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in source_files(source)
    )


def prepare_target(target):
    if not target.isValid() or not target.crs().isValid() or target.featureCount() <= 0:
        raise ValueError(
            "Área do empreendimento ausente, inválida ou sem sistema de coordenadas."
        )
    geometries = []
    for feature in target.getFeatures():
        geom = feature.geometry()
        if (
            not feature.hasGeometry()
            or geom.isEmpty()
            or geom.type() != 2
            or not geom.isGeosValid()
        ):
            raise ValueError(
                "Há uma parte ausente ou inválida na área do empreendimento. A análise seria incompleta."
            )
        geometries.append(geom)
    united = QgsGeometry.unaryUnion(geometries)
    if (
        united.isNull()
        or united.isEmpty()
        or united.lastError()
        or not united.isGeosValid()
    ):
        raise ValueError("Não foi possível formar uma área válida do empreendimento.")
    return united


def analyze_layer(
    target,
    source,
    layer=None,
    index=None,
    *,
    prepared=None,
    context=None,
    source_error=None,
    source_evidence=None,
    cancel_check=None,
):
    base = {
        "codigo": source.code,
        "fonte": source.name,
        "arquivo": str(source.path),
        "url_fonte": source.source_url,
        "referencia_regulatoria": source.regulatory_reference,
        "orientacao_revisao": source.review_guidance,
    }
    _check_cancel(cancel_check)
    try:
        if source_error:
            raise ValueError(source_error)
        layer = layer if layer is not None else _load_layer(source.path)
        if (
            not layer.isValid()
            or not layer.crs().isValid()
            or layer.featureCount() <= 0
        ):
            raise ValueError(
                "Camada oficial ausente, vazia, inválida ou sem sistema de coordenadas."
            )
        base.update(
            source_evidence
            if source_evidence is not None
            else _file_metadata(layer.source())
        )
        geometry = prepared if prepared is not None else prepare_target(target)
        context = (
            context if context is not None else QgsProject.instance().transformContext()
        )
        transformed = QgsGeometry(geometry)
        if (
            transformed.transform(
                QgsCoordinateTransform(target.crs(), layer.crs(), context)
            )
            != 0
        ):
            raise ValueError("A reprojeção da área não foi concluída.")
        # O provedor OGR pode aproveitar o índice persistente do GeoPackage.
        request = QgsFeatureRequest().setFilterRect(transformed.boundingBox())
        if index is not None:
            request = QgsFeatureRequest().setFilterFids(
                index.intersects(transformed.boundingBox())
            )
        distance = QgsDistanceArea()
        distance.setSourceCrs(layer.crs(), context)
        distance.setEllipsoid("GRS80")
        fields = {field.name().lower(): field.name() for field in layer.fields()}
        selected = [
            fields[name.lower()]
            for name in source.attribute_candidates
            if name.lower() in fields
        ]
        occurrences, intersections, contacts, repaired_features = [], [], [], []
        total_area = 0.0
        for feature in layer.getFeatures(request):
            _check_cancel(cancel_check)
            geom = feature.geometry()
            if not feature.hasGeometry() or geom.isEmpty():
                raise ValueError(
                    f"Geometria da fonte ausente na feição {feature.id()}."
                )
            if not geom.isGeosValid():
                repaired = geom.makeValid()
                if (
                    repaired.isNull()
                    or repaired.isEmpty()
                    or repaired.lastError()
                    or repaired.type() != QgsWkbTypes.PolygonGeometry
                    or not repaired.isGeosValid()
                ):
                    raise ValueError(
                        f"Geometria da fonte inválida e não reparável na feição {feature.id()}."
                    )
                geom = repaired
                repaired_features.append(int(feature.id()))
            if not geom.intersects(transformed):
                continue
            intersection = geom.intersection(transformed)
            if intersection.isNull() or intersection.lastError():
                raise ValueError(f"Falha ao cruzar a feição {feature.id()}.")
            if intersection.isEmpty():
                continue
            area = abs(distance.measureArea(intersection))
            if area == 0:
                contacts.append(int(feature.id()))
                continue
            intersections.append(intersection)
            total_area += area
            occurrences.append(
                {
                    "fid": int(feature.id()),
                    "area_ha": round(area / 10000, 4),
                    "atributos": {
                        name: feature[name]
                        for name in selected
                        if feature[name] not in (None, "")
                    },
                }
            )
        unique_area = 0.0
        if intersections:
            union = QgsGeometry.unaryUnion(intersections)
            if union.isNull() or union.lastError() or not union.isGeosValid():
                raise ValueError("Falha ao calcular a área única sobreposta.")
            unique_area = abs(distance.measureArea(union)) / 10000
        return {
            **base,
            "resultado": "ocorrencia_para_analise"
            if occurrences
            else "sem_ocorrencia_identificada",
            "quantidade": len(occurrences),
            "area_sobreposta_ha": round(unique_area, 4),
            "soma_areas_ocorrencias_ha": round(total_area / 10000, 4),
            "contatos_borda": contacts,
            "ocorrencias": occurrences,
            "ocorrencias_truncadas": 0,
            "geometrias_reparadas": repaired_features,
            "crs_fonte": layer.crs().authid(),
            "total_fonte": int(layer.featureCount()),
        }
    except AnalysisCancelled:
        raise
    except Exception as exc:
        return {**base, "resultado": "inconclusivo", "motivo": str(exc)}


def analyze_environment(target_path, sources):
    return EnvironmentalAnalyzer(sources).analyze(target_path)


class EnvironmentalAnalyzer:
    """Reaproveita fontes na mesma execução; invalida o cache quando o arquivo muda."""

    def __init__(self, sources, context=None):
        self.sources = list(sources)
        self.context = context
        self._layers = {}
        self._source_errors = {}
        self._signatures = {}
        self._evidence = {}

    def _source_objects(self, source):
        signature = source_signature(source)
        if (
            source.code not in self._layers
            or self._signatures.get(source.code) != signature
        ):
            layer = _load_layer(source.path)
            self._layers[source.code] = layer
            self._signatures[source.code] = signature
            hashes = {p.name: file_sha256(p) for p in source_files(source)}
            self._evidence[source.code] = {
                **_file_metadata(layer.source()),
                "sha256_conjunto_fonte": hashlib.sha256(
                    json.dumps(hashes, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            }
            error = None
            if layer.isValid():
                missing = (
                    QgsFeatureRequest()
                    .setFilterExpression("$geometry IS NULL OR is_empty($geometry)")
                    .setLimit(1)
                )
                if next(layer.getFeatures(missing), None) is not None:
                    error = (
                        "A fonte contém feição sem geometria; cobertura não comprovada."
                    )
            self._source_errors[source.code] = error
        return self._layers[source.code], None

    def analyze(self, target_path, cancel_check=None):
        from qgis_plugin_microcredito.domain.policy import aggregate

        _check_cancel(cancel_check)
        target = QgsVectorLayer(str(target_path), "empreendimento", "ogr")
        results = []
        try:
            prepared = prepare_target(target)
            distance = QgsDistanceArea()
            distance.setSourceCrs(
                target.crs(), self.context or QgsProject.instance().transformContext()
            )
            distance.setEllipsoid("GRS80")
            car_area_ha = abs(distance.measureArea(prepared)) / 10000
            if car_area_ha <= 0:
                raise ValueError(
                    "Área do CAR igual a zero; não é possível calcular a porcentagem de sobreposição."
                )
        except Exception as exc:
            return {
                "resultado_geral": "inconclusivo",
                "camadas": [
                    {
                        "codigo": s.code,
                        "fonte": s.name,
                        "resultado": "inconclusivo",
                        "motivo": str(exc),
                    }
                    for s in self.sources
                ],
            }
        for source in self.sources:
            _check_cancel(cancel_check)
            layer, index = self._source_objects(source)
            result = analyze_layer(
                target,
                source,
                layer,
                index,
                prepared=prepared,
                context=self.context,
                source_error=self._source_errors[source.code],
                source_evidence=self._evidence[source.code],
                cancel_check=cancel_check,
            )
            _check_cancel(cancel_check)
            if source_signature(source) != self._signatures[source.code]:
                result = {
                    "codigo": source.code,
                    "fonte": source.name,
                    "resultado": "inconclusivo",
                    "motivo": "A fonte mudou durante a análise; execute novamente.",
                }
            results.append(result)
        return {
            "resultado_geral": aggregate(item["resultado"] for item in results),
            "area_car_ha": round(car_area_ha, 4),
            "camadas": results,
        }
