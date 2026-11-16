import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from update_process_support import TEST_PUBLIC_KEY_PEM, write_signed_release


def test_preparation_rejects_unavailable_car_links_without_publishing_or_changing_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from installer.verify import file_sha256
    from prebuilt_support import write_complete_release

    signed = write_complete_release(tmp_path / "source", property_car="-1")
    before = {
        path: file_sha256(path)
        for path in signed.release.parent.rglob("*")
        if path.is_file()
    }
    destination = tmp_path / "candidate"
    user_profile = tmp_path / "user-profile"
    monkeypatch.setenv("LOCALAPPDATA", str(user_profile))

    with pytest.raises(ValueError, match="vínculo CAR.*documento.*operação"):
        prepare_prebuilt_bases(signed.release, destination, TEST_PUBLIC_KEY_PEM)

    assert not destination.exists()
    assert not list(tmp_path.glob(".prebuilt-*"))
    assert not user_profile.exists()
    assert all(file_sha256(path) == expected for path, expected in before.items())


@pytest.mark.parametrize("operation_key", [("2", "1"), ("1", "2")])
def test_preparation_rejects_a_car_document_link_without_its_operation(
    tmp_path: Path, operation_key: tuple[str, str]
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release

    signed = write_complete_release(tmp_path / "source", operation_key=operation_key)
    original = signed.release.read_bytes()
    destination = tmp_path / "candidate"

    with pytest.raises(ValueError, match="vínculo CAR.*documento.*operação"):
        prepare_prebuilt_bases(signed.release, destination, TEST_PUBLIC_KEY_PEM)

    assert not destination.exists()
    assert not list(tmp_path.glob(".prebuilt-*"))
    assert signed.release.read_bytes() == original


def test_preparation_accepts_an_explicit_borrower_link_and_records_its_coverage(
    tmp_path: Path,
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release

    signed = write_complete_release(tmp_path / "source", property_document="")
    manifest_path = prepare_prebuilt_bases(
        signed.release, tmp_path / "candidate", TEST_PUBLIC_KEY_PEM
    )

    coverage = json.loads(manifest_path.read_bytes())["sicor_link_coverage"]
    assert coverage["minimum_required"] == 1
    assert coverage["full_coverage_required"] is False
    assert coverage["unit"] == "active_property_rows"
    assert coverage["counts"] == {
        "active_properties": 1,
        "properties_with_formal_car": 1,
        "properties_with_unavailable_car": 0,
        "properties_with_malformed_car": 0,
        "formal_car_properties_with_direct_document": 0,
        "formal_car_properties_with_borrower_document": 1,
        "formal_car_properties_with_compatible_operation": 1,
        "properties_with_usable_link": 1,
    }


def test_preparation_requires_one_link_without_claiming_full_record_coverage(
    tmp_path: Path,
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release

    signed = write_complete_release(tmp_path / "source", extra_property_cars=("-1",))
    manifest_path = prepare_prebuilt_bases(
        signed.release, tmp_path / "candidate", TEST_PUBLIC_KEY_PEM
    )

    coverage = json.loads(manifest_path.read_bytes())["sicor_link_coverage"]
    assert coverage["full_coverage_required"] is False
    assert coverage["counts"] == {
        "active_properties": 2,
        "properties_with_formal_car": 1,
        "properties_with_unavailable_car": 1,
        "properties_with_malformed_car": 0,
        "formal_car_properties_with_direct_document": 1,
        "formal_car_properties_with_borrower_document": 1,
        "formal_car_properties_with_compatible_operation": 1,
        "properties_with_usable_link": 1,
    }


@pytest.mark.parametrize(
    "property_car",
    [
        "CAR-INDISPONIVEL",
        "ZZ-0000000-00000000000000000000000000000000",
        "RR-000000X-00000000000000000000000000000000",
        "RR-0000000-G0000000000000000000000000000000",
    ],
)
def test_preparation_rejects_an_unusable_nonempty_car_as_a_functional_witness(
    tmp_path: Path, property_car: str
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release

    signed = write_complete_release(tmp_path / "source", property_car=property_car)
    destination = tmp_path / "candidate"

    with pytest.raises(ValueError, match="vínculo CAR.*documento.*operação"):
        prepare_prebuilt_bases(signed.release, destination, TEST_PUBLIC_KEY_PEM)

    assert not destination.exists()


@pytest.mark.parametrize("document", ["", "***********", "00000000000*"])
def test_preparation_rejects_formal_car_without_a_complete_unmasked_document(
    tmp_path: Path, document: str
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release

    signed = write_complete_release(
        tmp_path / "source", property_document=document, borrower_document=document
    )
    destination = tmp_path / "candidate"

    with pytest.raises(ValueError, match="vínculo CAR.*documento.*operação"):
        prepare_prebuilt_bases(signed.release, destination, TEST_PUBLIC_KEY_PEM)

    assert not destination.exists()


def test_preparation_accepts_a_direct_property_link_without_a_borrower_document(
    tmp_path: Path,
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release

    signed = write_complete_release(tmp_path / "source", borrower_document="")
    manifest_path = prepare_prebuilt_bases(
        signed.release, tmp_path / "candidate", TEST_PUBLIC_KEY_PEM
    )

    counts = json.loads(manifest_path.read_bytes())["sicor_link_coverage"]["counts"]
    assert counts["formal_car_properties_with_direct_document"] == 1
    assert counts["formal_car_properties_with_borrower_document"] == 0
    assert counts["properties_with_usable_link"] == 1


def test_prebuilt_preparation_rejects_partial_release_without_creating_output(
    tmp_path: Path,
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases

    signed = write_signed_release(tmp_path / "source")
    destination = tmp_path / "candidate"

    with pytest.raises(ValueError, match="36 pacotes"):
        prepare_prebuilt_bases(signed.release, destination, TEST_PUBLIC_KEY_PEM)

    assert not destination.exists()


@pytest.mark.parametrize("fault", ["missing_glebas", "invalid_gpkg"])
def test_failed_preparation_never_publishes_a_partial_candidate(
    tmp_path: Path, fault: str
) -> None:
    from installer.base_release import build_base_release
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release
    from update_process_support import _sign

    signed = write_complete_release(tmp_path / "source")
    identifier = "sicor_operacoes_car" if fault == "missing_glebas" else "embargos"
    package = signed.packages[identifier]
    with zipfile.ZipFile(package) as archive:
        content = {name: archive.read(name) for name in archive.namelist()}
    document = json.loads(content["package.json"])
    if fault == "missing_glebas":
        removed = document["payloads"].pop("glebas")
        del content[removed]
        content["package.json"] = json.dumps(document).encode()
    else:
        content[document["payloads"]["file"]] = b"invalid geopackage"
    with zipfile.ZipFile(package, "w") as archive:
        for name, payload in content.items():
            archive.writestr(name, payload)
    catalog = json.loads(signed.catalog.read_bytes())
    descriptor = next(item for item in catalog["packages"] if item["id"] == identifier)
    descriptor.update(
        sha256=hashlib.sha256(package.read_bytes()).hexdigest(),
        size_bytes=package.stat().st_size,
    )
    signed.catalog.write_bytes(json.dumps(catalog).encode())
    signed.signature.write_bytes(_sign(signed.catalog.read_bytes()))
    build_base_release(
        signed.catalog,
        signed.signature,
        signed.packages,
        signed.release,
        TEST_PUBLIC_KEY_PEM,
    )
    source_bytes = signed.release.read_bytes()
    destination = tmp_path / "candidate"

    with pytest.raises(ValueError):
        prepare_prebuilt_bases(signed.release, destination, TEST_PUBLIC_KEY_PEM)

    assert not destination.exists()
    assert not list(tmp_path.glob(".prebuilt-*"))
    assert signed.release.read_bytes() == source_bytes


def test_prebuilt_preparation_preserves_an_existing_destination(tmp_path: Path) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases

    signed = write_signed_release(tmp_path / "source")
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "car_microcredito.db"
    sentinel.write_bytes(b"installed data")

    with pytest.raises(ValueError, match="destino deve ser novo"):
        prepare_prebuilt_bases(signed.release, destination, TEST_PUBLIC_KEY_PEM)

    assert sentinel.read_bytes() == b"installed data"


def test_prebuilt_preparation_rejects_invalid_source_signature(tmp_path: Path) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases

    signed = write_signed_release(tmp_path / "source")
    with zipfile.ZipFile(signed.release) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["catalog.json"] += b"\n"
    with zipfile.ZipFile(signed.release, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)

    destination = tmp_path / "candidate"
    with pytest.raises(ValueError, match="(?i)assinatura"):
        prepare_prebuilt_bases(signed.release, destination, TEST_PUBLIC_KEY_PEM)

    assert not destination.exists()


def test_publisher_cli_prepares_a_candidate_without_installing_user_bases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from installer.cli import app
    from prebuilt_support import write_complete_release

    signed = write_complete_release(tmp_path / "source")
    destination = tmp_path / "candidate"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-profile"))
    result = CliRunner().invoke(
        app,
        [
            "prepare-bases",
            "--release",
            str(signed.release),
            "--output",
            str(destination),
            "--public-key",
            str(signed.public_key),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (destination / "snapshot.candidate.json").is_file()
    assert not (tmp_path / "user-profile").exists()


def test_prebuilt_candidate_contains_queryable_database_and_all_35_payload_files(
    tmp_path: Path,
) -> None:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release

    signed = write_complete_release(tmp_path / "source")
    source_bytes = signed.release.read_bytes()
    destination = tmp_path / "candidate"

    manifest_path = prepare_prebuilt_bases(
        signed.release, destination, TEST_PUBLIC_KEY_PEM
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "bases-plugin-prebuilt-candidate"
    assert manifest["status"] == "requires_client_homologation"
    assert len(manifest["files"]) == 35
    assert len(manifest["components"]) == 37
    assert len(list((destination / "car").rglob("*.gpkg"))) == 27
    assert len(list((destination / "ambientais").glob("*.gpkg"))) == 6
    assert (
        destination / "catalog.source.json"
    ).read_bytes() == signed.catalog.read_bytes()
    assert (
        destination / "catalog.source.json.sig"
    ).read_bytes() == signed.signature.read_bytes()
    assert not any((destination / name).exists() for name in (".h", ".u", ".d"))
    assert signed.release.read_bytes() == source_bytes
    with closing(sqlite3.connect(destination / "car_microcredito.db")) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM sicor_mutuario").fetchone() == (
            1,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM trabalho_escravo"
        ).fetchone() == (1,)
        sources = [
            row[0] for row in connection.execute("SELECT arquivo FROM importacao")
        ]
        assert all(value.startswith("atualizacao-assinada:") for value in sources)
