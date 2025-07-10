#!/usr/bin/env python3
# bbva_statement_app.py
"""
Streamlit app — Extrae movimientos de estados de cuenta BBVA (débito y crédito)
y permite descargar un Excel con dos pestañas (Movimientos / Totales).

Ejecuta:
    streamlit run StreamlitApp_extractor_estado_cuenta_bbva.py
Requisitos:
    pip install streamlit pdfplumber pandas openpyxl
"""
from __future__ import annotations

import io
import re
from typing import List, Literal

import pandas as pd
import pdfplumber
import streamlit as st

# ───────────────────────── Expresiones y helpers ────────────────────────────
RE_FECHA_DEB = re.compile(r"^(\d{2}/[A-Z]{3})\s+(\d{2}/[A-Z]{3})\s+(.*)")
NUM_DEC      = r"\d{1,3}(?:,\d{3})*\.\d{2}"
RE_NUMS      = re.compile(NUM_DEC)

# Crédito: 03-mar-2025 … 03-mar-2025 …  + $529.00
RE_CREDITO = re.compile(
    rf"^(?P<fecha_oper>\d{{2}}-[A-Za-z]{{3}}-\d{{4}})\s+"
    rf"(?P<fecha_cargo>\d{{2}}-[A-Za-z]{{3}}-\d{{4}})\s+"
    rf"(?P<desc>.+?)\s+(?P<sign>[+-])\s*\$?\s*(?P<val>{NUM_DEC})$"
)

clean_num = lambda s: float(s.replace(",", "")) if s else None

# ───────────────────────── PDF → líneas ─────────────────────────────────────

def pdf_to_lines(file_bytes: bytes) -> List[str]:
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return [ln.strip() for p in pdf.pages for ln in (p.extract_text() or "").splitlines()]

# ───────────────────────── Parse débito ─────────────────────────────────────

def parse_debito(lines: List[str]) -> pd.DataFrame:
    i, n = 0, len(lines)
    rows = []
    while i < n:
        head = RE_FECHA_DEB.match(lines[i])
        if not head:
            i += 1
            continue

        # EXTRAER FECHAS
        fecha_oper = head.group(1)
        fecha_liq = head.group(2)
        tail = head.group(3)

        cargo = abono = None
        desc_parts: List[str] = []

        # Buscar montos en la misma línea
        nums_head = RE_NUMS.findall(tail)
        if nums_head:
            if len(nums_head) > 1:
                cargo = clean_num(nums_head[0])
            else:
                abono = clean_num(nums_head[0])
            tail = RE_NUMS.sub("", tail).strip()

        if tail:
            desc_parts.append(tail)

        i += 1
        # Buscar líneas adicionales hasta la siguiente cabecera
        while i < n and not RE_FECHA_DEB.match(lines[i]):
            l = lines[i]
            if not l or "referencia" in l.lower():
                i += 1
                continue
            nums = RE_NUMS.findall(l)
            if nums and cargo is None and abono is None:
                if len(nums) > 1:
                    cargo = clean_num(nums[0])
                else:
                    abono = clean_num(nums[0])
            elif not nums:
                desc_parts.append(l)
            i += 1

        desc = " ".join(desc_parts)
        if "SPEI RECIBIDO" in desc.upper() and cargo is not None and abono is None:
            abono, cargo = cargo, None
        if cargo is None and abono is None:
            continue

        # AGREGAR FECHAS AL RESULTADO
        rows.append({
            "Fecha Oper": fecha_oper,
            "Fecha Liq": fecha_liq,
            "Descripción": desc,
            "Cargo": cargo,
            "Abono": abono
        })

    # Crear DataFrame
    df = pd.DataFrame(rows)

    return df



# ───────────────────────── Parse crédito ────────────────────────────────────
def parse_credito(lines: List[str]) -> pd.DataFrame:
    rows = []
    for l in lines:
        m = RE_CREDITO.search(l)
        if not m:
            continue
        val  = clean_num(m.group("val"))
        sign = m.group("sign")
        monto = val if sign == "+" else -val
        rows.append({
            "Fecha de la operación": m.group("fecha_oper"),
            "Fecha de cargo": m.group("fecha_cargo"),
            "Descripción del movimiento": m.group("desc"),
            "Monto": monto,
        })

    df = pd.DataFrame(rows)

    # Convertir las columnas de fecha a tipo datetime
    for col in ["Fecha de la operación", "Fecha de cargo"]:
        df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)

    return df


# ───────────────────────── Streamlit UI ────────────────────────────────────

st.set_page_config(page_title="Extractor BBVA", layout="centered")
st.title("🏦 Extractor Estado de Cuenta BBVA")

uploaded = st.file_uploader("📄 Sube tu PDF", type=["pdf"])
account_type: Literal["débito", "crédito"] = st.radio("Tipo de cuenta", ["débito", "crédito"], index=0)

if uploaded:
    try:
        lines = pdf_to_lines(uploaded.read())
        df = parse_debito(lines) if account_type == "débito" else parse_credito(lines)
        if df.empty:
            st.error("No se encontraron movimientos.")
        else:
            st.subheader("📋 Movimientos")
            st.dataframe(df, use_container_width=True)

            if account_type == "débito":
                total_abono = df["Abono"].fillna(0).sum()
                total_cargo = df["Cargo"].fillna(0).sum()

                st.subheader("📊 Totales")
                st.write(f"**Total abonos:** ${total_abono:,.2f}")
                st.write(f"**Total cargos:** ${total_cargo:,.2f}")

            else:  # crédito
                total_abono = df[df["Monto"] > 0]["Monto"].sum()
                total_cargo = -df[df["Monto"] < 0]["Monto"].sum()

                st.subheader("📊 Totales")
                st.write(f"**Total cargos:** ${total_abono:,.2f}")
                st.write(f"**Total abonos:** ${total_cargo:,.2f}")


            # Excel buffer
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Movimientos", index=False)
                pd.DataFrame({
                    "Concepto": ["Total cargos", "Total abonos"],
                    "Monto": [total_abono, total_cargo],
                }).to_excel(writer, sheet_name="Totales", index=False)
            st.download_button("💾 Descargar Excel", data=excel_buffer.getvalue(), file_name="bbva_movimientos.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        st.error(f"Error procesando PDF: {e}")
else:
    st.info("⬆️ Sube un PDF para comenzar.")
