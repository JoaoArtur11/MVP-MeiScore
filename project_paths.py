from __future__ import annotations

import os
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
DADOS_CNAE_DIR = PROJECT_ROOT / "dados cnae"
RFB_EXTRACT_DIR = PROJECT_ROOT / "rf_cnpj_csv" / "_extracted"

DB_PATH = Path(os.environ.get("MEMP_DB_PATH", PROJECT_ROOT / "cnpj_2026_01.duckdb"))
PNCP_JSONL_PATH = Path(os.environ.get("MEMP_PNCP_JSONL", PROJECT_ROOT / "pncp_contratos_6m.jsonl"))
OUT_CHARTS_DIR = Path(os.environ.get("MEMP_OUT_DIR", PROJECT_ROOT / "out_charts"))

_KIND_PATTERNS = {
    "empresas": ("EMPRECSV", "EMPRESAS"),
    "estabelecimentos": ("ESTABELE", "ESTABELECIMENTOS"),
    "simples": ("SIMPLES",),
}

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONTH_RE = re.compile(r"\b(\d{4}-\d{2})\b")


def _match_kind(name: str, kind: str) -> bool:
    tokens = _KIND_PATTERNS[kind]
    up = name.upper()
    return any(tok in up for tok in tokens)


def _extract_date_from_text(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if m:
        return date.fromisoformat(m.group(1))

    m = _MONTH_RE.search(text)
    if m:
        y, mo = m.group(1).split("-")
        return date(int(y), int(mo), 1)

    return None


def _path_date(p: Path) -> date | None:
    best = None
    for part in p.parts:
        d = _extract_date_from_text(part)
        if d and (best is None or d > best):
            best = d
    d_name = _extract_date_from_text(p.name)
    if d_name and (best is None or d_name > best):
        best = d_name
    return best


def _latest_snapshot(paths: Iterable[Path]) -> tuple[date | None, list[Path]]:
    paths = list(paths)
    dated = [(p, _path_date(p)) for p in paths]
    available_dates = [d for _, d in dated if d is not None]
    if not available_dates:
        return None, paths

    latest = max(available_dates)
    selected = [p for p, d in dated if d == latest]
    return latest, selected


def _iter_candidates(root: Path, kind: str) -> tuple[list[Path], list[Path]]:
    raw_files: list[Path] = []
    zip_files: list[Path] = []

    if not root.exists():
        return raw_files, zip_files

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if not _match_kind(p.name, kind):
            continue
        if p.suffix.lower() == ".zip":
            zip_files.append(p)
        else:
            raw_files.append(p)

    return raw_files, zip_files


def _extract_kind_from_zip(zip_path: Path, kind: str, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / f".{zip_path.stem}.{kind}.manifest"

    if manifest.exists() and manifest.stat().st_mtime >= zip_path.stat().st_mtime:
        names = [line.strip() for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
        cached = [out_dir / n for n in names]
        if cached and all(p.exists() for p in cached):
            return cached

    extracted: list[Path] = []
    extracted_names: list[str] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            member_name = Path(info.filename).name
            if not _match_kind(member_name, kind):
                continue

            out_file = out_dir / member_name
            if out_file.exists() and out_file.stat().st_size == info.file_size:
                extracted.append(out_file)
                extracted_names.append(member_name)
                continue

            tmp = out_file.with_suffix(out_file.suffix + ".part")
            with zf.open(info, "r") as src, tmp.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            tmp.replace(out_file)
            extracted.append(out_file)
            extracted_names.append(member_name)

    if extracted_names:
        manifest.write_text("\n".join(sorted(set(extracted_names))), encoding="utf-8")

    return extracted


def get_rfb_files(kind: str) -> list[str]:
    """
    Resolve arquivos da RFB no projeto atual.

    Prioridade:
    1) pasta `dados cnae` (brutos ou zip)
    2) fallback em `rf_cnpj_csv`

    Sempre escolhe o snapshot mais recente encontrado no path.
    """
    if kind not in _KIND_PATTERNS:
        raise ValueError(f"Tipo invalido: {kind}")

    raw_data, zip_data = _iter_candidates(DADOS_CNAE_DIR, kind)
    raw_csv, zip_csv = _iter_candidates(PROJECT_ROOT / "rf_cnpj_csv", kind)

    raw_candidates = raw_data + raw_csv
    zip_candidates = zip_data + zip_csv
    all_candidates = raw_candidates + zip_candidates

    snapshot_date, _ = _latest_snapshot(all_candidates)
    if snapshot_date is None:
        selected_raw = raw_candidates
        selected_zip = zip_candidates
    else:
        selected_raw = [p for p in raw_candidates if _path_date(p) == snapshot_date]
        selected_zip = [p for p in zip_candidates if _path_date(p) == snapshot_date]

    extracted: list[Path] = []
    if selected_zip:
        snap_label = snapshot_date.isoformat() if snapshot_date else "snapshot_undated"
        out_dir = RFB_EXTRACT_DIR / snap_label
        for z in selected_zip:
            extracted.extend(_extract_kind_from_zip(z, kind, out_dir))

    resolved = sorted({str(p) for p in (selected_raw + extracted)})
    return resolved
