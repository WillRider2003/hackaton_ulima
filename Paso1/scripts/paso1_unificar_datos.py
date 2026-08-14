# -*- coding: utf-8 -*-
"""
PASO 1 — EXPLICA+ · Preparación y unificación de datos (con pandas)
Hackathon AI Telecom Challenge (Movistar x Universidad de Lima)

Qué hace este script:
1. Carga los 8 CSV entregados con pandas (cada uno con su delimitador real;
   el dataset trae una mezcla de ';' y ',' según el archivo).
2. Normaliza las llaves de cuenta (distintas fuentes usan distinto nombre
   de columna para lo que en el fondo es la misma cuenta financiera).
3. Construye la TABLA MAESTRA DE EVENTOS: un registro por (cuenta, ciclo)
   con el total facturado, la cantidad de cargos, los GRUPO presentes y las
   causas detectadas al cruzar (merge) contra las 4 tablas Brainy, Notas de
   Crédito y Órdenes.
4. Exporta la tabla maestra a salida/tabla_maestra_eventos.csv y selecciona
   5 cuentas reales (una por escenario crítico) para usarlas como casos de
   prueba en Dify (sección 11 de la propuesta).

Este es el insumo directo para el PASO 2 (motor de diffing).
"""

import os
import pandas as pd

# BASE_DIR: la carpeta donde vive este script (asumimos que está en scripts/).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DATA_DIR: carpeta donde están los 8 CSV originales, un nivel arriba de
# scripts/ y dentro de datos_originales/. Ajusta esta ruta si tu estructura
# de carpetas es distinta.
DATA_DIR = os.path.join(BASE_DIR, "..", "datos")

# OUT_DIR: carpeta donde vamos a guardar los CSV que generemos.
# exist_ok=True evita error si la carpeta ya existe.
OUT_DIR = os.path.join(BASE_DIR, "..", "salida_paso1")
os.makedirs(OUT_DIR, exist_ok=True)

pd.set_option("display.width", 120)


def detectar_delimitador(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        primera_linea = f.readline()
    return ";" if primera_linea.count(";") > primera_linea.count(",") else ","


def cargar_csv(nombre_archivo):
    path = os.path.join(DATA_DIR, nombre_archivo)
    delim = detectar_delimitador(path)
    df = pd.read_csv(path, delimiter=delim, encoding="utf-8", dtype=str, on_bad_lines="skip")
    print(f"  · {nombre_archivo}: {len(df):,} filas, {len(df.columns)} columnas (delimitador '{delim}')")
    return df


print("=" * 70)
print("PASO 1 — Cargando los 8 archivos del dataset con pandas")
print("=" * 70)

facturacion = cargar_csv("FACTURACION-CLIENTES.csv")
planta = cargar_csv("PLANTA CLIENTES.csv")
ordenes = cargar_csv("Ordenes.csv")
notas_credito = cargar_csv("NOTAS_CREDITO.csv")
prorrateo = cargar_csv("BRAINY_PRORRATEO_ALTASV3.csv")
reconexiones = cargar_csv("BRAINY_RECONEXIONESV3.csv")
descuentos = cargar_csv("BRAINY_DESCUENTOS_CUOTAS.csv")
catalogo = cargar_csv("CATALOGO-OFERTAS.csv")

# Tipos numéricos que sí necesitamos como número, no como texto
facturacion["CHARGE_TOTAL_AMOUNT"] = pd.to_numeric(
    facturacion["CHARGE_TOTAL_AMOUNT"], errors="coerce"
).fillna(0.0)

print()
print("=" * 70)
print("PASO 1 — Normalizando llaves de cuenta en cada tabla")
print("=" * 70)

# Cada tabla Brainy usa un nombre de columna distinto para la cuenta financiera.
# Se crea una columna uniforme "cuenta_financiera" en cada una para poder
# hacer merge directo contra FACTURACION-CLIENTES.
facturacion["cuenta_financiera"] = facturacion["FINANCIAL_ACCOUNT_KEY"].str.strip()
prorrateo["cuenta_financiera"] = prorrateo["CuentaFinanciera"].str.strip()
reconexiones["cuenta_financiera"] = reconexiones["CuentaFinanciera"].str.strip()
descuentos["cuenta_financiera"] = descuentos["cuentafinanciera"].str.strip()
notas_credito["cuenta_financiera"] = notas_credito["BA_NO"].str.strip()

# Nota importante de llaves: Ordenes.csv identifica al cliente por CUSTOMER_KEY,
# NO por cuenta financiera. Para cruzarlo contra Facturación hay que pasar
# primero por el CUSTOMER_KEY que trae FACTURACION-CLIENTES.csv.
ordenes["customer_key"] = ordenes["CUSTOMER_KEY"].str.strip()
facturacion["customer_key"] = facturacion["CUSTOMER_KEY"].str.strip()

print("  · Columna 'cuenta_financiera' creada en: facturación, prorrateo, "
      "reconexiones, descuentos, notas de crédito.")
print("  · Columna 'customer_key' creada en: facturación, órdenes "
      "(Ordenes se cruza por cliente, no por cuenta).")

print()
print("=" * 70)
print("PASO 1 — Agrupando FACTURACION-CLIENTES por (cuenta, ciclo)")
print("=" * 70)

resumen_ciclo = (
    facturacion.groupby(["cuenta_financiera", "ciclo"])
    .agg(
        total_ciclo_soles=("CHARGE_TOTAL_AMOUNT", "sum"),
        cantidad_cargos=("CHARGE_TOTAL_AMOUNT", "count"),
        grupos_presentes=("GRUPO", lambda s: " | ".join(sorted(s.dropna().unique()))),
        customer_key=("customer_key", "first"),
    )
    .reset_index()
)
resumen_ciclo["total_ciclo_soles"] = resumen_ciclo["total_ciclo_soles"].round(2)

print(f"  · Combinaciones (cuenta, ciclo) únicas: {len(resumen_ciclo):,}")

print()
print("=" * 70)
print("PASO 1 — Cruzando (merge) contra las 4 tablas Brainy + Notas + Órdenes")
print("=" * 70)

cuentas_prorrateo = set(prorrateo["cuenta_financiera"].dropna())
cuentas_reconexion = set(reconexiones["cuenta_financiera"].dropna())
cuentas_descuento = set(descuentos["cuenta_financiera"].dropna())
cuentas_notas = set(notas_credito["cuenta_financiera"].dropna())
clientes_con_ordenes = set(ordenes["customer_key"].dropna())

print(f"  · Cuentas con prorrateo:      {len(cuentas_prorrateo):,}")
print(f"  · Cuentas con reconexión:     {len(cuentas_reconexion):,}")
print(f"  · Cuentas con descuentos:     {len(cuentas_descuento):,}")
print(f"  · Cuentas con notas cred.:    {len(cuentas_notas):,}")
print(f"  · Clientes con órdenes:       {len(clientes_con_ordenes):,}")


def detectar_causas(row):
    causas = []
    if row["cuenta_financiera"] in cuentas_prorrateo:
        causas.append("PRORRATEO")
    if row["cuenta_financiera"] in cuentas_reconexion:
        causas.append("RECONEXION")
    if row["cuenta_financiera"] in cuentas_descuento:
        causas.append("DESCUENTO/FINANCIAMIENTO")
    if row["cuenta_financiera"] in cuentas_notas:
        causas.append("NOTA_CREDITO_DEBITO")
    if row["customer_key"] in clientes_con_ordenes:
        causas.append("CAMBIO_PLAN/ORDEN")
    return " | ".join(causas) if causas else "SIN_CAUSA_ESPECIAL"


resumen_ciclo["causas_detectadas"] = resumen_ciclo.apply(detectar_causas, axis=1)

tabla_maestra = resumen_ciclo[
    ["cuenta_financiera", "ciclo", "total_ciclo_soles", "cantidad_cargos",
     "grupos_presentes", "causas_detectadas"]
]

out_path = os.path.join(OUT_DIR, "tabla_maestra_eventos.csv")
tabla_maestra.to_csv(out_path, index=False, encoding="utf-8")
print(f"  · Tabla maestra exportada a: {out_path}  ({len(tabla_maestra):,} filas)")

print()
print("=" * 70)
print("PASO 1 — Seleccionando 5 casos de prueba reales (uno por escenario)")
print("=" * 70)

grupos_por_cuenta_ciclo = (
    facturacion.groupby(["cuenta_financiera", "ciclo"])["GRUPO"]
    .apply(lambda s: set(s.dropna()))
)

casos = {}


def primer_caso(mask, nombre):
    if nombre in casos:
        return
    candidatos = resumen_ciclo[mask]
    if not candidatos.empty:
        fila = candidatos.iloc[0]
        casos[nombre] = (fila["cuenta_financiera"], fila["ciclo"])


primer_caso(resumen_ciclo["cuenta_financiera"].isin(cuentas_prorrateo), "a_prorrateo")
primer_caso(resumen_ciclo["cuenta_financiera"].isin(cuentas_descuento), "b_financiamiento")

# c) Reconexión: además de estar en la tabla Brainy, confirmamos el GRUPO real
reconexion_mask = resumen_ciclo.apply(
    lambda r: "CARGO POR RECONEXION" in grupos_por_cuenta_ciclo.get((r["cuenta_financiera"], r["ciclo"]), set()),
    axis=1,
)
primer_caso(reconexion_mask, "c_reconexion")

# d) Fin de descuento: cuentas en BRAINY_DESCUENTOS_CUOTAS con FechaFin informada
cuentas_fin_descuento = set(descuentos.loc[descuentos["FechaFin"].notna(), "cuenta_financiera"])
primer_caso(resumen_ciclo["cuenta_financiera"].isin(cuentas_fin_descuento), "d_fin_descuento")

primer_caso(resumen_ciclo["customer_key"].isin(clientes_con_ordenes), "e_cambio_plan")

casos_df = pd.DataFrame(
    [{"escenario": k, "cuenta_financiera": v[0], "ciclo": v[1]} for k, v in casos.items()]
)
casos_path = os.path.join(OUT_DIR, "casos_prueba_por_escenario.csv")
casos_df.to_csv(casos_path, index=False, encoding="utf-8")

for _, r in casos_df.iterrows():
    print(f"  · {r['escenario']}: cuenta {r['cuenta_financiera']}, ciclo {r['ciclo']}")
print(f"  · Exportado a: {casos_path}")

print()
print("=" * 70)
print("PASO 1 completado. Insumos listos para el PASO 2 (motor de diffing).")
print("=" * 70)
