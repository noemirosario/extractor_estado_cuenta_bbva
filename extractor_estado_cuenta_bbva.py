#!/usr/bin/env python3
"""
extract_bank_statement.py — Convierte un estado de cuenta BBVA a Excel
──────────────────────────────────────────────────────────────────────

• Para cuentas **débito** exporta columnas:
    Descripción | Cargo | Abono
    (reglas: ver `parse_debito`).

• Para cuentas **crédito** (no usado por defecto) detecta `+` / `-` antes del monto.

• Crea un único archivo Excel con dos pestañas:
    1. **Movimientos** – lista de transacciones del PDF actual.
    2. **Totales**      – Total abonos y Total cargos del PDF actual.

Dependencias: `pip install pdfplumber pandas openpyxl`
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Literal

import pandas as pd
import pdfplumber

# ─── CONFIG ──────────────────────────────────────────────────────────
PDF_PATH   = r"C:/Users/Juan/Downloads/angela.pdf"            # PDF de entrada
EXCEL_PATH = r"C:/Users/Juan/Documents/movs_bbva.xlsx"        # Excel de salida
ACCOUNT_TYPE: Literal["credito", "debito"] = "debito"       # tipo de cuenta
# ────────────────────────────────────────────────────────────────────

# Expresiones
RE_FECHA = re.compile(r"^(\d{2}/[A-Z]{3})\s+(\d{2}/[A-Z]{3})\s+(.*)")
NUM_DEC  = r"\d{1,3}(?:,\d{3})*\.\d{2}"      # número con decimales
RE_NUMS  = re.compile(NUM_DEC)
RE_CREDITO = re.compile(rf"(?P<desc>.+?)\s+(?P<sign>[+-])\s*\$?\s*(?P<val>{NUM_DEC})$", re.IGNORECASE)

clean_num = lambda s: float(s.replace(",", "")) if s else None

# ─── Utilidades ─────────────────────────────────────────────────────

def pdf_to_lines(pdf: Path) -> List[str]:
    lines: List[str] = []
    with pdfplumber.open(pdf) as doc:
        for page in doc.pages:
            lines.extend(l.strip() for l in (page.extract_text() or "").splitlines())
    return lines

# ─── Parsing débito ─────────────────────────────────────────────────

def parse_debito(lines: List[str]) -> pd.DataFrame:
    i, n = 0, len(lines)
    moves = []
    while i < n:
        head = RE_FECHA.match(lines[i])
        if not head:
            i += 1
            continue

        cargo = abono = None
        desc_parts: List[str] = []

        tail = head.group(3)
        nums_head = RE_NUMS.findall(tail)
        if nums_head:
            if len(nums_head) == 1:
                abono = clean_num(nums_head[0])
            else:
                cargo = clean_num(nums_head[0])
            tail = RE_NUMS.sub("", tail).strip()
        if tail:
            desc_parts.append(tail)
        i += 1

        while i < n and not RE_FECHA.match(lines[i]):
            l = lines[i]
            if not l or "referencia" in l.lower():
                i += 1
                continue
            nums = RE_NUMS.findall(l)
            if nums and cargo is None and abono is None:
                if len(nums) == 1:
                    abono = clean_num(nums[0])
                else:
                    cargo = clean_num(nums[0])
            elif not nums:
                desc_parts.append(l)
            i += 1

        descripcion = " ".join(desc_parts)
        # Regla: SPEI RECIBIDO nunca es cargo
        if "SPEI RECIBIDO" in descripcion.upper() and cargo is not None and abono is None:
            abono, cargo = cargo, None

        if cargo is None and abono is None:
            continue
        moves.append({"Descripción": descripcion, "Cargo": cargo, "Abono": abono})
    return pd.DataFrame(moves)

# ─── Parsing crédito (simplificado) ────────────────────────────────

def parse_credito(lines: List[str]) -> pd.DataFrame:
    rows = []
    for l in lines:
        m = RE_CREDITO.search(l)
        if m:
            val = clean_num(m.group("val"))
            rows.append({
                "Descripción": m.group("desc"),
                "Cargo": val if m.group("sign") == "-" else None,
                "Abono": val if m.group("sign") == "+" else None,
            })
    return pd.DataFrame(rows)

# ─── Export a Excel ────────────────────────────────────────────────

def export_to_excel(df: pd.DataFrame, out: Path):
    total_abono = df["Abono"].fillna(0).sum()
    total_cargo = df["Cargo"].fillna(0).sum()
    totales = pd.DataFrame({
        "Concepto": ["Total abonos", "Total cargos"],
        "Monto": [total_abono, total_cargo],
    })
    with pd.ExcelWriter(out, engine="openpyxl", mode="w") as w:
        df.to_excel(w, sheet_name="Movimientos", index=False)
        totales.to_excel(w, sheet_name="Totales", index=False)

# ─── Main ──────────────────────────────────────────────────────────

def main():
    pdf = Path(PDF_PATH)
    if not pdf.exists():
        sys.exit("❌ PDF no encontrado")

    lines = pdf_to_lines(pdf)
    df = parse_debito(lines) if ACCOUNT_TYPE == "debito" else parse_credito(lines)
    if df.empty:
        sys.exit("⚠️  No se extrajeron movimientos; revisa el formato/regex.")

    export_to_excel(df, Path(EXCEL_PATH))
    export_to_excel(df, Path(EXCEL_PATH))
    print("✅ Exportado →", EXCEL_PATH)

if __name__ == "__main__":
    main()