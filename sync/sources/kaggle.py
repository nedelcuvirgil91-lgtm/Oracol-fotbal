"""
================================================================================
FOOTBALL ORACLE — sync/sources/kaggle.py (v1.1)
Interfata izolata pentru sursa de date Kaggle.
Toata logica specifica bibliotecii `kagglehub` traieste EXCLUSIV aici.
Restul proiectului foloseste DOAR functiile publice de mai jos.
Daca in viitor kagglehub e inlocuit, se modifica NUMAI acest fisier.

IMPORTANT: acest modul NU modifica niciodata dictionarele de mapare
(TEAM_ALIASES, normalize_league_name, column_map etc.). El doar
RAPORTEAZA coloane/structuri necunoscute. Orice actualizare a mapărilor
se face manual, de catre utilizator, in mappings.py sau import_historical.py.
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import kagglehub
import pandas as pd

logger = logging.getLogger("football_oracle.sync.kaggle")

# Constante izolate aici. Daca proiectul introduce ulterior un config.py
# centralizat, se muta doar aceste 2 linii — restul modulului nu se schimba.
MAIN_DATASET = "adamgbor/club-football-match-data-2000-2025"
XG_DATASET = "codytipton/understat-data"

# Campuri logice minime asteptate intr-un fisier de meciuri. Fiecare intrare
# e o lista de alias-uri posibile de nume de coloana (case-insensitive).
# Nu opreste executia — doar genereaza un WARNING daca niciun alias nu e gasit.
REQUIRED_FIELD_ALIASES: dict[str, list[str]] = {
    "date": ["date", "match_date", "kickoff", "utc_date"],
    "home_team": ["home_team", "hometeam", "home", "team_home"],
    "away_team": ["away_team", "awayteam", "away", "team_away"],
}

SAMPLE_ROWS_FOR_TYPES = 1000


class KaggleSourceError(Exception):
    """Eroare specifica sursei Kaggle (autentificare, download, sau date lipsa)."""


@dataclass
class CsvSummary:
    filename: str
    path: str
    rows: int
    columns: list[str]
    dtypes: dict[str, str]
    missing_required_fields: list[str]
    file_size_bytes: int


@dataclass
class DatasetInspection:
    dataset_slug: str
    local_path: str
    inspected_at_utc: str
    csv_files: list[CsvSummary] = field(default_factory=list)


def _check_credentials() -> None:
    """Valideaza si mapeaza variabilele de mediu necesare pentru kagglehub."""
    username = os.environ.get("KAGGLE_USERNAME")
    key = os.environ.get("KAGGLE_KEY") or os.environ.get("KAGGLE_TOKEN")

    if not username or not key:
        raise KaggleSourceError(
            "Lipsesc credentialele Kaggle. Seteaza variabilele de mediu "
            "KAGGLE_USERNAME si KAGGLE_KEY (sau KAGGLE_TOKEN) inainte de rulare. "
            "In GitHub Actions acestea trebuie mapate din secrets."
        )

    if not os.environ.get("KAGGLE_KEY") and os.environ.get("KAGGLE_TOKEN"):
        os.environ["KAGGLE_KEY"] = os.environ["KAGGLE_TOKEN"]


def download_dataset(dataset_slug: str) -> str:
    """
    Descarca (sau foloseste din cache local) un dataset Kaggle si
    returneaza calea locala catre folderul cu fisiere.
    """
    _check_credentials()
    try:
        path = kagglehub.dataset_download(dataset_slug)
    except Exception as exc:
        raise KaggleSourceError(
            f"Descarcarea dataset-ului '{dataset_slug}' a esuat. "
            f"Verifica username-ul, cheia API si slug-ul dataset-ului. "
            f"Detaliu tehnic: {exc}"
        ) from exc

    if not path or not os.path.isdir(path):
        raise KaggleSourceError(
            f"kagglehub a returnat o cale invalida pentru '{dataset_slug}': {path!r}"
        )

    logger.info("Dataset '%s' disponibil local la: %s", dataset_slug, path)
    return path


def _discover_csv_files(local_path: str) -> list[str]:
    """Detecteaza automat toate fisierele .csv, fara nume hardcodate."""
    csv_paths = []
    for root, _dirs, files in os.walk(local_path):
        for fname in files:
            if fname.lower().endswith(".csv"):
                csv_paths.append(os.path.join(root, fname))
    return sorted(csv_paths)


def list_available_csv(dataset_slug: str) -> list[str]:
    """
    Descarca dataset-ul (daca nu e deja in cache) si returneaza DOAR
    lista numelor fisierelor CSV disponibile, fara nicio inspectie de continut.
    """
    local_path = download_dataset(dataset_slug)
    csv_paths = _discover_csv_files(local_path)
    return [os.path.basename(p) for p in csv_paths]


def _count_rows_fast(csv_path: str) -> int:
    """
    Numara randurile fara sa incarce fisierul in memorie ca DataFrame.
    Citeste in chunk-uri binare si numara newline-uri; scade 1 pentru header.
    """
    count = 0
    with open(csv_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            count += chunk.count(b"\n")
    return max(count - 1, 0)


def _read_header(csv_path: str) -> list[str]:
    """Citeste doar header-ul, fara niciun rand de date."""
    header_df = pd.read_csv(csv_path, nrows=0)
    return list(header_df.columns)


def _infer_dtypes_from_sample(csv_path: str, sample_rows: int = SAMPLE_ROWS_FOR_TYPES) -> dict[str, str]:
    """Infereaza tipurile de coloane dintr-un esantion mic, nu din tot fisierul."""
    sample_df = pd.read_csv(csv_path, nrows=sample_rows)
    return {col: str(dtype) for col, dtype in sample_df.dtypes.items()}


def _check_required_fields(columns: list[str]) -> list[str]:
    """Returneaza lista campurilor logice obligatorii care NU au fost gasite."""
    lower_columns = {c.lower() for c in columns}
    missing = []
    for field_name, aliases in REQUIRED_FIELD_ALIASES.items():
        if not any(alias in lower_columns for alias in aliases):
            missing.append(field_name)
    return missing


def inspect_dataset(dataset_slug: str) -> DatasetInspection:
    """
    Descarca dataset-ul (daca nu e deja in cache) si intoarce un rezumat
    eficient pentru fiecare CSV gasit: numar de randuri (fara incarcare
    completa), coloane, tipuri inferate dintr-un esantion, si campuri
    obligatorii lipsa. Nu importa nimic in Supabase — doar inspecteaza.
    """
    local_path = download_dataset(dataset_slug)
    csv_file_paths = _discover_csv_files(local_path)

    if not csv_file_paths:
        raise KaggleSourceError(
            f"Niciun fisier .csv gasit in dataset-ul '{dataset_slug}' "
            f"(cale locala: {local_path}). Verifica daca dataset-ul chiar "
            f"contine fisiere CSV sau daca structura s-a schimbat pe Kaggle."
        )

    summaries: list[CsvSummary] = []
    for csv_path in csv_file_paths:
        try:
            columns = _read_header(csv_path)
            rows = _count_rows_fast(csv_path)
            dtypes = _infer_dtypes_from_sample(csv_path)
            missing_fields = _check_required_fields(columns)
            file_size = os.path.getsize(csv_path)
        except Exception as exc:
            logger.warning("Nu am putut inspecta '%s': %s", csv_path, exc)
            continue

        if missing_fields:
            logger.warning(
                "Fisierul '%s' nu are campuri recunoscute pentru: %s. "
                "Coloanele existente sunt: %s",
                os.path.basename(csv_path), missing_fields, columns,
            )

        summaries.append(
            CsvSummary(
                filename=os.path.basename(csv_path),
                path=csv_path,
                rows=rows,
                columns=columns,
                dtypes=dtypes,
                missing_required_fields=missing_fields,
                file_size_bytes=file_size,
            )
        )

    inspection = DatasetInspection(
        dataset_slug=dataset_slug,
        local_path=local_path,
        inspected_at_utc=datetime.now(timezone.utc).isoformat(),
        csv_files=summaries,
    )

    logger.info("Inspectie '%s': %d fisiere CSV gasite.", dataset_slug, len(summaries))
    for s in summaries:
        logger.info(
            "  - %s: %d randuri, %d coloane, %.1f MB",
            s.filename, s.rows, len(s.columns), s.file_size_bytes / (1024 * 1024),
        )

    return inspection


def inspect_all_sources() -> dict[str, DatasetInspection]:
    """Inspecteaza ambele dataseturi (principal + xG) si intoarce rezultatele."""
    return {
        "main": inspect_dataset(MAIN_DATASET),
        "xg": inspect_dataset(XG_DATASET),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sursa Kaggle pentru Football Oracle")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Descarca si inspecteaza structura dataseturilor Kaggle (eficient, fara import).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Doar listeaza numele fisierelor CSV disponibile, fara inspectie.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.list:
        for slug in (MAIN_DATASET, XG_DATASET):
            files = list_available_csv(slug)
            logger.info("Dataset '%s' — %d fisiere: %s", slug, len(files), files)

    elif args.inspect:
        try:
            results = inspect_all_sources()
        except KaggleSourceError as exc:
            logger.error("Inspectie esuata: %s", exc)
            raise SystemExit(1) from exc

        for key, inspection in results.items():
            logger.info("=== %s — %s ===", key.upper(), inspection.dataset_slug)
            logger.info("Cale locala: %s | Inspectat la: %s", inspection.local_path, inspection.inspected_at_utc)
            for csv in inspection.csv_files:
                logger.info(
                    "  %s: %d randuri, coloane=%s",
                    csv.filename, csv.rows, csv.columns,
                )
                logger.info("    Tipuri (esantion %d randuri): %s", SAMPLE_ROWS_FOR_TYPES, csv.dtypes)
                if csv.missing_required_fields:
                    logger.warning("    Campuri lipsa: %s", csv.missing_required_fields)
    else:
        parser.print_help()
