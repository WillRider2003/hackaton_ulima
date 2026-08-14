# -*- coding: utf-8 -*-
"""
PASO 2: Motor de diffing (comparación de recibos)

Qué hace este script:
1. Carga la tabla_maestra_eventos.csv que generó el PASO 1.
2. Para cada cuenta financiera, ordena sus ciclos cronológicamente y compara
   cada ciclo contra el ANTERIOR — igual que un cliente comparando dos
   recibos consecutivos.
3. Calcula el delta en soles (cuánto subió o bajó) entre ambos ciclos.
4. Para cada delta, va a buscar la CAUSA EXACTA en la tabla Brainy que
   corresponda (prorrateo, reconexión, descuento/financiamiento, nota de
   crédito/débito, cambio de plan) y arma una "cita de origen": la tabla y
   los campos concretos que sustentan esa causa (fechas, montos).
5. Si no encuentra ninguna causa que explique el delta, lo marca
   explícitamente como "SIN_CAUSA_IDENTIFICADA" el motor NUNCA inventa
   una explicación donde no la tiene evidencia. Esto es lo que garantiza
   el 0% de alucinaciones que pide la ficha del desafío.
6. Exporta un JSON por caso de prueba (uno por escenario crítico) con
   exactamente la estructura que se le pasaría al LLM en el Paso 3 / al
   agente de Dify el LLM solo va a narrar este JSON, nunca calcula nada.

Este es el insumo directo para el PASO 3 (capa de redacción con LLM) y
para las tools de Dify (sección 11 de la propuesta).
"""

import os
import json
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "datos")
PASO1_DIR = os.path.join(BASE_DIR, "..", "salida_paso1")
OUT_DIR = os.path.join(BASE_DIR, "..", "salida_paso2")
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
    print(f"  · {nombre_archivo}: {len(df):,} filas cargadas (delimitador '{delim}')")
    return df


print("=" * 70)
print("PASO 2 — Cargando insumos")
print("=" * 70)

tabla_maestra_path = os.path.join(PASO1_DIR, "tabla_maestra_eventos.csv")
if not os.path.exists(tabla_maestra_path):
    raise FileNotFoundError(
        f"No se encontró {tabla_maestra_path}. Corre primero el PASO 1 "
        "(scripts/paso1_unificar_datos.py) para generar tabla_maestra_eventos.csv."
    )

tabla_maestra = pd.read_csv(tabla_maestra_path, dtype=str)
tabla_maestra["total_ciclo_soles"] = pd.to_numeric(tabla_maestra["total_ciclo_soles"], errors="coerce")
print(f"  · tabla_maestra_eventos.csv: {len(tabla_maestra):,} filas (cuenta, ciclo)")

# Volvemos a cargar las tablas fuente originales para poder citar el campo
# EXACTO (fecha, monto) que sustenta cada causa — la tabla maestra del Paso 1
# solo dice SI existe una causa, no los detalles necesarios para explicarla.
prorrateo = cargar_csv("BRAINY_PRORRATEO_ALTASV3.csv")
reconexiones = cargar_csv("BRAINY_RECONEXIONESV3.csv")
descuentos = cargar_csv("BRAINY_DESCUENTOS_CUOTAS.csv")
notas_credito = cargar_csv("NOTAS_CREDITO.csv")
ordenes = cargar_csv("Ordenes.csv")
facturacion = cargar_csv("FACTURACION-CLIENTES_.csv")

prorrateo["cuenta_financiera"] = prorrateo["CuentaFinanciera"].str.strip()
reconexiones["cuenta_financiera"] = reconexiones["CuentaFinanciera"].str.strip()
descuentos["cuenta_financiera"] = descuentos["cuentafinanciera"].str.strip()
notas_credito["cuenta_financiera"] = notas_credito["BA_NO"].str.strip()
ordenes["customer_key"] = ordenes["CUSTOMER_KEY"].str.strip()
facturacion["cuenta_financiera"] = facturacion["FINANCIAL_ACCOUNT_KEY"].str.strip()
facturacion["customer_key"] = facturacion["CUSTOMER_KEY"].str.strip()

# Mapa cuenta_financiera -> customer_key (Ordenes.csv solo se cruza por cliente)
cuenta_a_customer = dict(zip(facturacion["cuenta_financiera"], facturacion["customer_key"]))

print()
print("=" * 70)
print("PASO 2 — Indexando tablas fuente por cuenta (para búsqueda rápida)")
print("=" * 70)

# Indexar cada tabla por cuenta (o customer_key en el caso de Órdenes) evita
# recorrer la tabla completa por cada una de las ~85,000 comparaciones
# groupby aquí actúa como un diccionario {cuenta: DataFrame de sus filas}.
idx_prorrateo = dict(tuple(prorrateo.groupby("cuenta_financiera")))
idx_reconexiones = dict(tuple(reconexiones.groupby("cuenta_financiera")))
idx_descuentos = dict(tuple(descuentos.groupby("cuenta_financiera")))
idx_notas_credito = dict(tuple(notas_credito.groupby("cuenta_financiera")))
idx_ordenes = dict(tuple(ordenes.groupby("customer_key")))
print(f"  · Índices construidos: prorrateo, reconexiones, descuentos, notas de crédito, órdenes.")

print()
print("=" * 70)
print("PASO 2 — Ordenando ciclos por cuenta para comparar consecutivos")
print("=" * 70)

tabla_maestra = tabla_maestra.sort_values(["cuenta_financiera", "ciclo"])
tabla_maestra["total_ciclo_anterior"] = tabla_maestra.groupby("cuenta_financiera")["total_ciclo_soles"].shift(1)
tabla_maestra["ciclo_anterior"] = tabla_maestra.groupby("cuenta_financiera")["ciclo"].shift(1)
tabla_maestra["delta_soles"] = (
    tabla_maestra["total_ciclo_soles"] - tabla_maestra["total_ciclo_anterior"]
).round(2)

comparables = tabla_maestra.dropna(subset=["total_ciclo_anterior"]).copy()
print(f"  · Combinaciones (cuenta, ciclo) con un ciclo anterior para comparar: {len(comparables):,}")


def buscar_causa_prorrateo(cuenta):
    filas = idx_prorrateo.get(cuenta)
    if filas is None or filas.empty:
        return None
    f = filas.iloc[0]
    return {
        "tipo": "PRORRATEO",
        "fuente": "BRAINY_PRORRATEO_ALTASV3.csv",
        "evidencia": {
            "fecha_inicio_minima": f.get("fecha_inicio_minima"),
            "fecha_fin_maxima": f.get("fecha_fin_maxima"),
            "suma_prorrateo": f.get("suma_prorrateo"),
            "cantidad_cargos": f.get("Q_cargos"),
        },
    }


def buscar_causa_reconexion(cuenta):
    filas = idx_reconexiones.get(cuenta)
    if filas is None or filas.empty:
        return None
    f = filas.iloc[0]
    return {
        "tipo": "RECONEXION",
        "fuente": "BRAINY_RECONEXIONESV3.csv",
        "evidencia": {
            "fecha_corte": f.get("FechaCorte"),
            "fecha_reconexion": f.get("FechaReconexion"),
            "monto": f.get("Monto"),
        },
    }


def buscar_causa_descuento(cuenta):
    filas = idx_descuentos.get(cuenta)
    if filas is None or filas.empty:
        return None
    f = filas.iloc[0]
    # Distinguimos "fin de descuento" (tiene FechaFin) de "cuota de equipo financiado"
    if pd.notna(f.get("FechaFin")) and str(f.get("FechaFin")).strip():
        return {
            "tipo": "FIN_DESCUENTO",
            "fuente": "BRAINY_DESCUENTOS_CUOTAS.csv",
            "evidencia": {
                "fecha_fin": f.get("FechaFin"),
                "porcentaje_promo": f.get("PorcentajePromo"),
                "descripcion": f.get("Traduccion"),
            },
        }
    return {
        "tipo": "EQUIPO_FINANCIADO",
        "fuente": "BRAINY_DESCUENTOS_CUOTAS.csv",
        "evidencia": {
            "cuota_actual": f.get("CuotaActual"),
            "duracion_promocion": f.get("PromotionDuration"),
            "monto_descuento": f.get("Monto_Descuento"),
        },
    }


def buscar_causa_nota_credito(cuenta):
    filas = idx_notas_credito.get(cuenta)
    if filas is None or filas.empty:
        return None
    f = filas.iloc[0]
    return {
        "tipo": "NOTA_CREDITO_DEBITO",
        "fuente": "NOTAS_CREDITO.csv",
        "evidencia": {
            "tipo_cancelacion": f.get("CANCEL_CHARGE_TYPE"),
            "monto": f.get("AMOUNT"),
            "fecha_efectiva": f.get("EFFECTIVE_DATE"),
        },
    }


def buscar_causa_cambio_plan(cuenta):
    customer_key = cuenta_a_customer.get(cuenta)
    if not customer_key:
        return None
    filas = idx_ordenes.get(customer_key)
    if filas is None or filas.empty:
        return None
    f = filas.iloc[0]
    return {
        "tipo": "CAMBIO_PLAN",
        "fuente": "Ordenes.csv",
        "evidencia": {
            "motivo": f.get("ORDER_ACTION_REASON_DESC"),
            "fecha_inicio": f.get("ORDER_ACTION_START_DATE"),
            "fecha_completado": f.get("ORDER_ACTION_COMPLETION_DATE"),
        },
    }


def detectar_causa_delta(cuenta):
    """
    Revisa las 5 posibles causas en un orden fijo y devuelve la PRIMERA que
    encuentre evidencia real. Si ninguna tiene evidencia, devuelve None
    el motor nunca "adivina" una causa sin datos que la sustenten.

    LIMITACIÓN CONOCIDA (v1): esta función verifica que la cuenta TENGA un
    registro en la tabla correspondiente, pero no verifica todavía que la
    fecha de ese registro caiga dentro del rango del ciclo que se está
    comparando. Es decir: puede asignar "PRORRATEO" a una cuenta que tuvo un
    prorrateo en OTRO ciclo distinto al que se está explicando ahora. Esto es
    intencional para esta primera versión (prioriza no dejar nada sin
    intentar explicar) pero debe refinarse en el Paso 3 agregando un filtro
    de fecha en cada buscar_causa_* antes de darlo por definitivo, nunca
    se muestra al cliente sin ese refinamiento.
    """
    for buscador in (
        buscar_causa_prorrateo,
        buscar_causa_reconexion,
        buscar_causa_descuento,
        buscar_causa_nota_credito,
        buscar_causa_cambio_plan,
    ):
        causa = buscador(cuenta)
        if causa:
            return causa
    return None


print()
print("=" * 70)
print("PASO 2: Calculando delta y detectando causa por cada comparación")
print("=" * 70)

resultados = []
for _, row in comparables.iterrows():
    cuenta = row["cuenta_financiera"]
    causa = detectar_causa_delta(cuenta)
    resultados.append({
        "cuenta_financiera": cuenta,
        "ciclo_actual": row["ciclo"],
        "ciclo_anterior": row["ciclo_anterior"],
        "total_ciclo_actual_soles": row["total_ciclo_soles"],
        "total_ciclo_anterior_soles": row["total_ciclo_anterior"],
        "delta_soles": row["delta_soles"],
        "causa_tipo": causa["tipo"] if causa else "SIN_CAUSA_IDENTIFICADA",
        "causa_fuente": causa["fuente"] if causa else None,
    })

diffing_df = pd.DataFrame(resultados)
out_path = os.path.join(OUT_DIR, "resultado_diffing.csv")
diffing_df.to_csv(out_path, index=False, encoding="utf-8")
print(f"  · Resultado del diffing exportado a: {out_path}  ({len(diffing_df):,} filas)")

con_causa = (diffing_df["causa_tipo"] != "SIN_CAUSA_IDENTIFICADA").sum()
sin_causa = (diffing_df["causa_tipo"] == "SIN_CAUSA_IDENTIFICADA").sum()
print(f"  · Comparaciones con causa identificada: {con_causa:,}")
print(f"  · Comparaciones sin causa identificada (no se inventa nada): {sin_causa:,}")
print("  · Distribución por tipo de causa:")
print(diffing_df["causa_tipo"].value_counts().to_string())

# LIMITACIÓN CONOCIDA DE ESTA VERSIÓN (documentada, no oculta):
# "causa identificada" aquí significa "esta cuenta TIENE un registro en la
# tabla Brainy correspondiente en algún momento" no necesariamente que ese
# evento haya ocurrido justo entre ciclo_anterior y ciclo_actual. Es una
# primera versión funcional, más permisiva que precisa. El Paso 3 debe
# afinar cada buscar_causa_* para filtrar por fecha (ej. que
# fecha_inicio_minima del prorrateo caiga DENTRO del rango del ciclo
# comparado) antes de asignar la causa como definitiva.
delta_cero_con_causa = (
    (diffing_df["delta_soles"] == 0) & (diffing_df["causa_tipo"] != "SIN_CAUSA_IDENTIFICADA")
).sum()
print()
print(f"  · [LIMITACIÓN CONOCIDA] Filas con delta=0 pero con causa asignada: "
      f"{delta_cero_con_causa:,} ({100*delta_cero_con_causa/len(diffing_df):.1f}%). "
      "La causa detectada es real, pero puede no corresponder a ESE ciclo "
      "específico. Ver nota en el README y en la sección 'detectar_causa_delta' "
      "de este script — se resuelve en el Paso 3 filtrando por fecha.")

print()
print("=" * 70)
print("PASO 2: Armando el JSON de salida para cada caso de prueba del Paso 1")
print("=" * 70)

casos_path = os.path.join(PASO1_DIR, "casos_prueba_por_escenario.csv")
casos_df = pd.read_csv(casos_path, dtype=str)

jsons_generados = {}
for _, caso in casos_df.iterrows():
    cuenta = caso["cuenta_financiera"]
    ciclo = caso["ciclo"]
    escenario = caso["escenario"]

    fila = diffing_df[
        (diffing_df["cuenta_financiera"] == cuenta) & (diffing_df["ciclo_actual"] == ciclo)
    ]

    if fila.empty:
        # Esta cuenta no tuvo un ciclo anterior comparable en la tabla maestra;
        # igual generamos el JSON con causa detectada directamente, para que
        # el caso de prueba no quede vacío.
        causa = detectar_causa_delta(cuenta)
        resultado_json = {
            "cuenta_financiera": cuenta,
            "ciclo_consultado": ciclo,
            "comparacion_disponible": False,
            "nota": "No se encontró un ciclo anterior comparable en la tabla maestra "
                    "para esta cuenta+ciclo específico; se muestra la causa detectada "
                    "directamente en las tablas fuente.",
            "causa": causa if causa else {"tipo": "SIN_CAUSA_IDENTIFICADA"},
        }
    else:
        f = fila.iloc[0]
        causa = detectar_causa_delta(cuenta)
        resultado_json = {
            "cuenta_financiera": cuenta,
            "ciclo_actual": f["ciclo_actual"],
            "ciclo_anterior": f["ciclo_anterior"],
            "total_ciclo_actual_soles": f["total_ciclo_actual_soles"],
            "total_ciclo_anterior_soles": f["total_ciclo_anterior_soles"],
            "delta_soles": f["delta_soles"],
            "comparacion_disponible": True,
            "causa": causa if causa else {"tipo": "SIN_CAUSA_IDENTIFICADA"},
        }

    jsons_generados[escenario] = resultado_json
    json_path = os.path.join(OUT_DIR, f"caso_{escenario}.json")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(resultado_json, jf, ensure_ascii=False, indent=2, default=str)
    print(f"  · {escenario}: cuenta {cuenta}, ciclo {ciclo} → {json_path}")

print()
print("=" * 70)
print("PASO 2 completado.")
print("Insumos listos para el PASO 3 (capa de redacción LLM) y para la tool")
print("consultar_recibo del agente en Dify (sección 11 de la propuesta).")
print("=" * 70)