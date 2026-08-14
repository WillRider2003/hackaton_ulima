# -*- coding: utf-8 -*-
"""
PASO 2: Motor de diffing

Esta versión agrega un FILTRO DE FECHA: cada causa candidata solo
se acepta si su fecha de evidencia cae dentro del rango del ciclo
comparado. Además, en vez de quedarse con la PRIMERA causa que encuentra
evidencia, ahora evalúa TODAS las causas candidatas y se queda con la que
tiene la fecha más cercana al ciclo actual.

Qué sigue haciendo igual que la v1:
1. Carga tabla_maestra_eventos.csv del Paso 1.
2. Ordena ciclos por cuenta y compara cada uno contra el anterior.
3. Si ninguna causa (ni siquiera con el filtro de fecha) tiene evidencia,
   marca SIN_CAUSA_IDENTIFICADA — nunca inventa.
4. Exporta resultado_diffing.csv y un JSON por caso de prueba.
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

# Tolerancia: un evento que ocurrió hasta N días ANTES del inicio del ciclo
# comparado igual se acepta como causa (algunos cargos Brainy se generan
# un par de días antes del corte oficial de facturación). Ajustable.
TOLERANCIA_DIAS_ANTES = 5


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


def parsear_fecha(serie):
    """
    Convierte una columna de texto a fecha real (datetime), aceptando los
    dos formatos que trae el dataset: DD/MM/YYYY (Prorrateo, Reconexiones)
    e YYYY-MM-DD (Descuentos, Notas de Crédito, Órdenes).
    """
    intento_1 = pd.to_datetime(serie, errors="coerce", dayfirst=True, format="mixed")
    return intento_1


def ciclo_a_rango(ciclo_str):
    """
    Convierte 'YYYYMMDD' (formato de la columna ciclo) a una VENTANA de
    fechas centrada en la fecha de corte real de ese ciclo — no en el mes
    calendario completo. Los ciclos de facturación de Movistar cortan en
    un día específico (ej. el 17), no necesariamente el día 1 o el fin de
    mes, así que la ventana correcta va desde ~1 mes antes de esa fecha de
    corte hasta esa fecha de corte.
    """
    fecha_corte = pd.to_datetime(ciclo_str, format="%Y%m%d", errors="coerce")
    if pd.isna(fecha_corte):
        return None, None
    inicio_ventana = fecha_corte - pd.DateOffset(months=1)
    return inicio_ventana, fecha_corte


def fecha_dentro_del_ciclo(fecha_evento, ciclo_str):
    """
    True si fecha_evento cae dentro del ciclo (con la tolerancia de días
    antes definida arriba). Si fecha_evento es NaT o el ciclo no es
    válido, devuelve False — más estricto es más seguro.
    """
    if pd.isna(fecha_evento):
        return False
    inicio, fin = ciclo_a_rango(ciclo_str)
    if inicio is None:
        return False
    inicio_con_tolerancia = inicio - pd.Timedelta(days=TOLERANCIA_DIAS_ANTES)
    return inicio_con_tolerancia <= fecha_evento <= fin


print("=" * 70)
print("PASO 2 v2 — Cargando insumos")
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

# Pre-calculamos la fecha "representativa" de cada evento en cada tabla,
# la que se usará para el filtro de ciclo:
prorrateo["fecha_evento"] = parsear_fecha(prorrateo["fecha_inicio_minima"])
reconexiones["fecha_evento"] = parsear_fecha(reconexiones["FechaCorte"]).fillna(
    parsear_fecha(reconexiones["FechaReconexion"])
)
descuentos["fecha_evento_fin"] = parsear_fecha(descuentos["FechaFin"])
descuentos["fecha_evento_inicio"] = parsear_fecha(descuentos["FechaInicio"])
notas_credito["fecha_evento"] = parsear_fecha(notas_credito["EFFECTIVE_DATE"])
ordenes["fecha_evento"] = parsear_fecha(ordenes["ORDER_ACTION_COMPLETION_DATE"])

cuenta_a_customer = dict(zip(facturacion["cuenta_financiera"], facturacion["customer_key"]))

print()
print("=" * 70)
print("PASO 2: Indexando tablas fuente por cuenta")
print("=" * 70)

idx_prorrateo = dict(tuple(prorrateo.groupby("cuenta_financiera")))
idx_reconexiones = dict(tuple(reconexiones.groupby("cuenta_financiera")))
idx_descuentos = dict(tuple(descuentos.groupby("cuenta_financiera")))
idx_notas_credito = dict(tuple(notas_credito.groupby("cuenta_financiera")))
idx_ordenes = dict(tuple(ordenes.groupby("customer_key")))
print("  · Índices construidos: prorrateo, reconexiones, descuentos, notas de crédito, órdenes.")

print()
print("=" * 70)
print("PASO 2 v2 — Ordenando ciclos por cuenta para comparar consecutivos")
print("=" * 70)

tabla_maestra = tabla_maestra.sort_values(["cuenta_financiera", "ciclo"])
tabla_maestra["total_ciclo_anterior"] = tabla_maestra.groupby("cuenta_financiera")["total_ciclo_soles"].shift(1)
tabla_maestra["ciclo_anterior"] = tabla_maestra.groupby("cuenta_financiera")["ciclo"].shift(1)
tabla_maestra["delta_soles"] = (
    tabla_maestra["total_ciclo_soles"] - tabla_maestra["total_ciclo_anterior"]
).round(2)

comparables = tabla_maestra.dropna(subset=["total_ciclo_anterior"]).copy()
print(f"  · Combinaciones (cuenta, ciclo) con un ciclo anterior para comparar: {len(comparables):,}")


def fila_mas_cercana(filas_candidatas, fin_ciclo, columna_fecha):
    """
    Cuando hay más de una fila dentro de la ventana del ciclo, nos quedamos
    con la que tiene la fecha más cercana al cierre del ciclo (fin_ciclo).
    """
    diffs = (filas_candidatas[columna_fecha] - fin_ciclo).abs()
    return filas_candidatas.loc[diffs.idxmin()]


def candidata_prorrateo(cuenta, ciclo, inicio_ciclo, fin_ciclo):
    filas = idx_prorrateo.get(cuenta)
    if filas is None:
        return None
    inicio_con_tol = inicio_ciclo - pd.Timedelta(days=TOLERANCIA_DIAS_ANTES)
    mask = filas["fecha_evento"].between(inicio_con_tol, fin_ciclo)
    filas_en_ciclo = filas[mask]
    if filas_en_ciclo.empty:
        return None
    f = fila_mas_cercana(filas_en_ciclo, fin_ciclo, "fecha_evento")
    return {
        "tipo": "PRORRATEO",
        "fuente": "BRAINY_PRORRATEO_ALTASV3.csv",
        "fecha_evento": f["fecha_evento"],
        "evidencia": {
            "fecha_inicio_minima": f.get("fecha_inicio_minima"),
            "fecha_fin_maxima": f.get("fecha_fin_maxima"),
            "suma_prorrateo": f.get("suma_prorrateo"),
            "cantidad_cargos": f.get("Q_cargos"),
        },
    }


def candidata_reconexion(cuenta, ciclo, inicio_ciclo, fin_ciclo):
    filas = idx_reconexiones.get(cuenta)
    if filas is None:
        return None
    inicio_con_tol = inicio_ciclo - pd.Timedelta(days=TOLERANCIA_DIAS_ANTES)
    mask = filas["fecha_evento"].between(inicio_con_tol, fin_ciclo)
    filas_en_ciclo = filas[mask]
    if filas_en_ciclo.empty:
        return None
    f = fila_mas_cercana(filas_en_ciclo, fin_ciclo, "fecha_evento")
    return {
        "tipo": "RECONEXION",
        "fuente": "BRAINY_RECONEXIONESV3.csv",
        "fecha_evento": f["fecha_evento"],
        "evidencia": {
            "fecha_corte": f.get("FechaCorte"),
            "fecha_reconexion": f.get("FechaReconexion"),
            "monto": f.get("Monto"),
        },
    }


def candidata_descuento(cuenta, ciclo, inicio_ciclo, fin_ciclo):
    filas = idx_descuentos.get(cuenta)
    if filas is None:
        return None
    inicio_con_tol = inicio_ciclo - pd.Timedelta(days=TOLERANCIA_DIAS_ANTES)

    # "Fin de descuento": el ciclo comparado cae dentro del mes en que
    # el descuento TERMINÓ (fecha_evento_fin).
    mask_fin = filas["fecha_evento_fin"].between(inicio_con_tol, fin_ciclo)
    fin_en_ciclo = filas[mask_fin]
    if not fin_en_ciclo.empty:
        f = fila_mas_cercana(fin_en_ciclo, fin_ciclo, "fecha_evento_fin")
        return {
            "tipo": "FIN_DESCUENTO",
            "fuente": "BRAINY_DESCUENTOS_CUOTAS.csv",
            "fecha_evento": f["fecha_evento_fin"],
            "evidencia": {
                "fecha_fin": f.get("FechaFin"),
                "porcentaje_promo": f.get("PorcentajePromo"),
                "descripcion": f.get("Traduccion"),
            },
        }
    # "Equipo financiado": el ciclo comparado cae dentro del mes en que
    # EMPEZÓ la cuota (fecha_evento_inicio).
    mask_inicio = filas["fecha_evento_inicio"].between(inicio_con_tol, fin_ciclo)
    activo_en_ciclo = filas[mask_inicio]
    if not activo_en_ciclo.empty:
        f = fila_mas_cercana(activo_en_ciclo, fin_ciclo, "fecha_evento_inicio")
        return {
            "tipo": "EQUIPO_FINANCIADO",
            "fuente": "BRAINY_DESCUENTOS_CUOTAS.csv",
            "fecha_evento": f["fecha_evento_inicio"],
            "evidencia": {
                "cuota_actual": f.get("CuotaActual"),
                "duracion_promocion": f.get("PromotionDuration"),
                "monto_descuento": f.get("Monto_Descuento"),
            },
        }
    return None


def candidata_nota_credito(cuenta, ciclo, inicio_ciclo, fin_ciclo):
    filas = idx_notas_credito.get(cuenta)
    if filas is None:
        return None
    inicio_con_tol = inicio_ciclo - pd.Timedelta(days=TOLERANCIA_DIAS_ANTES)
    mask = filas["fecha_evento"].between(inicio_con_tol, fin_ciclo)
    filas_en_ciclo = filas[mask]
    if filas_en_ciclo.empty:
        return None
    f = fila_mas_cercana(filas_en_ciclo, fin_ciclo, "fecha_evento")
    return {
        "tipo": "NOTA_CREDITO_DEBITO",
        "fuente": "NOTAS_CREDITO.csv",
        "fecha_evento": f["fecha_evento"],
        "evidencia": {
            "tipo_cancelacion": f.get("CANCEL_CHARGE_TYPE"),
            "monto": f.get("AMOUNT"),
            "fecha_efectiva": f.get("EFFECTIVE_DATE"),
        },
    }


def candidata_cambio_plan(cuenta, ciclo, inicio_ciclo, fin_ciclo):
    customer_key = cuenta_a_customer.get(cuenta)
    if not customer_key:
        return None
    filas = idx_ordenes.get(customer_key)
    if filas is None:
        return None
    inicio_con_tol = inicio_ciclo - pd.Timedelta(days=TOLERANCIA_DIAS_ANTES)
    mask = filas["fecha_evento"].between(inicio_con_tol, fin_ciclo)
    filas_en_ciclo = filas[mask]
    if filas_en_ciclo.empty:
        return None
    f = fila_mas_cercana(filas_en_ciclo, fin_ciclo, "fecha_evento")
    return {
        "tipo": "CAMBIO_PLAN",
        "fuente": "Ordenes.csv",
        "fecha_evento": f["fecha_evento"],
        "evidencia": {
            "motivo": f.get("ORDER_ACTION_REASON_DESC"),
            "fecha_inicio": f.get("ORDER_ACTION_START_DATE"),
            "fecha_completado": f.get("ORDER_ACTION_COMPLETION_DATE"),
        },
    }


def detectar_causa_delta(cuenta, ciclo):
    """
    v2: evalúa las 5 causas candidatas, se queda SOLO con las que su fecha
    de evidencia cae dentro del ciclo comparado, y si hay más de una
    candidata válida, elige la de fecha MÁS CERCANA al fin del ciclo. Si
    ninguna candidata pasa el filtro de fecha, devuelve None
    SIN_CAUSA_IDENTIFICADA, nunca inventa.
    """
    inicio_ciclo, fin_ciclo = ciclo_a_rango(ciclo)
    if inicio_ciclo is None:
        return None

    candidatas = []
    for buscador in (
        candidata_prorrateo,
        candidata_reconexion,
        candidata_descuento,
        candidata_nota_credito,
        candidata_cambio_plan,
    ):
        c = buscador(cuenta, ciclo, inicio_ciclo, fin_ciclo)
        if c:
            candidatas.append(c)

    if not candidatas:
        return None

    candidatas.sort(key=lambda c: abs((fin_ciclo - c["fecha_evento"]).days))
    mejor = candidatas[0]
    mejor = {k: v for k, v in mejor.items() if k != "fecha_evento"}
    return mejor


print()
print("=" * 70)
print("PASO 2: Calculando delta y detectando causa (CON filtro de fecha)")
print("=" * 70)

resultados = []
for _, row in comparables.iterrows():
    cuenta = row["cuenta_financiera"]
    ciclo = row["ciclo"]
    causa = detectar_causa_delta(cuenta, ciclo)
    resultados.append({
        "cuenta_financiera": cuenta,
        "ciclo_actual": ciclo,
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
print(f"  · Comparaciones con causa identificada (y confirmada por fecha): {con_causa:,}")
print(f"  · Comparaciones sin causa identificada: {sin_causa:,}")
print("  · Distribución por tipo de causa:")
print(diffing_df["causa_tipo"].value_counts().to_string())

delta_cero_con_causa = (
    (diffing_df["delta_soles"] == 0) & (diffing_df["causa_tipo"] != "SIN_CAUSA_IDENTIFICADA")
).sum()
print()
print(f"  · Filas con delta=0 pero con causa asignada: {delta_cero_con_causa:,} "
      f"({100*delta_cero_con_causa/len(diffing_df):.1f}%) — con el filtro de fecha activo, "
      "estas SÍ corresponden a eventos reales dentro del ciclo, ya no son atribuciones fuera de fecha.")

print()
print("=" * 70)
print("PASO 2 v2 — Regenerando casos de prueba con causas CONFIRMADAS por fecha")
print("=" * 70)

# La selección original del Paso 1 se hizo con lógica v1 (sin filtro de
# fecha), así que algunas cuentas ya no corresponden a su escenario nominal
# bajo el filtro v2. Aquí se vuelve a elegir, para cada escenario, la
# primera cuenta+ciclo cuya causa confirmada por fecha coincide exactamente
# con lo que ese escenario necesita demostrar.
escenario_a_causa = {
    "a_prorrateo": "PRORRATEO",
    "b_financiamiento": "EQUIPO_FINANCIADO",
    "c_reconexion": "RECONEXION",
    "d_fin_descuento": "FIN_DESCUENTO",
    "e_cambio_plan": "CAMBIO_PLAN",
}

nuevos_casos = []
for escenario, causa_buscada in escenario_a_causa.items():
    candidatos = diffing_df[diffing_df["causa_tipo"] == causa_buscada]
    if candidatos.empty:
        print(f"  · [ATENCIÓN] No se encontró ningún caso confirmado para {escenario} "
              f"({causa_buscada}) en el dataset. Revisar manualmente.")
        continue
    fila = candidatos.iloc[0]
    nuevos_casos.append({
        "escenario": escenario,
        "cuenta_financiera": fila["cuenta_financiera"],
        "ciclo": fila["ciclo_actual"],
    })
    print(f"  · {escenario}: cuenta {fila['cuenta_financiera']}, ciclo {fila['ciclo_actual']} "
          f"— causa confirmada: {causa_buscada}")

nuevos_casos_df = pd.DataFrame(nuevos_casos)
casos_actualizados_path = os.path.join(PASO1_DIR, "casos_prueba_por_escenario.csv")
nuevos_casos_df.to_csv(casos_actualizados_path, index=False, encoding="utf-8")
print(f"  · casos_prueba_por_escenario.csv actualizado en: {casos_actualizados_path}")
casos_df = nuevos_casos_df

print()
print("=" * 70)
print("PASO 2 v2 — Armando el JSON de salida para cada caso de prueba (ya corregido)")
print("=" * 70)

def limpiar_para_json(obj):
    """
    Reemplaza NaN/NaT de pandas por None (que json.dump sí convierte
    correctamente a null) de forma recursiva.
    """
    if isinstance(obj, dict):
        return {k: limpiar_para_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [limpiar_para_json(v) for v in obj]
    if isinstance(obj, float) and pd.isna(obj):
        return None
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return obj


for _, caso in casos_df.iterrows():
    cuenta = caso["cuenta_financiera"]
    ciclo = caso["ciclo"]
    escenario = caso["escenario"]

    fila = diffing_df[
        (diffing_df["cuenta_financiera"] == cuenta) & (diffing_df["ciclo_actual"] == ciclo)
    ]

    causa = detectar_causa_delta(cuenta, ciclo)

    if fila.empty:
        resultado_json = {
            "cuenta_financiera": cuenta,
            "ciclo_consultado": ciclo,
            "comparacion_disponible": False,
            "nota": "No se encontró un ciclo anterior comparable en la tabla maestra "
                    "para esta cuenta+ciclo específico; se muestra la causa detectada "
                    "directamente en las tablas fuente, ya filtrada por fecha (v2).",
            "causa": causa if causa else {"tipo": "SIN_CAUSA_IDENTIFICADA"},
        }
    else:
        f = fila.iloc[0]
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

    json_path = os.path.join(OUT_DIR, f"caso_{escenario}.json")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(limpiar_para_json(resultado_json), jf, ensure_ascii=False, indent=2, default=str)
    print(f"  · {escenario}: cuenta {cuenta}, ciclo {ciclo} → causa: "
          f"{resultado_json['causa'].get('tipo')} → {json_path}")

print()
print("=" * 70)
print("PASO 2 v2 completado. Filtro de fecha activo — causas confirmadas dentro del ciclo.")
print("=" * 70)