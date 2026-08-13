# -*- coding: utf-8 -*-
"""
PASO 1: Preparación y unificación de datos

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

# Primero configuramos las rutas:
# BASE_DIR: la carpeta donde vive este script (asumimos que está en scripts/).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DATA_DIR: carpeta donde están los 8 CSV originales, un nivel arriba de
# scripts/ y dentro de datos/.
DATA_DIR = os.path.join(BASE_DIR, "..", "datos")

# OUT_DIR: carpeta donde vamos a guardar los CSV que generemos.
# exist_ok=True evita error si la carpeta ya existe.
OUT_DIR = os.path.join(BASE_DIR, "..", "salida_paso1")
os.makedirs(OUT_DIR, exist_ok=True)

# Solo estético: que los DataFrames impresos en consola no se corten feo.
pd.set_option("display.width", 120)

def detectar_delimitador(path):
    """
    El dataset mezcla archivos separados por ';' y por ','.
    En vez de asumir uno fijo, leemos la primera línea (el encabezado)
    y contamos cuál símbolo aparece más veces, ese es el delimitador real.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        primera_linea = f.readline()
    return ";" if primera_linea.count(";") > primera_linea.count(",") else ","

def cargar_csv(nombre_archivo):
    """
    Carga un CSV con pandas usando el delimitador correcto.
    dtype=str: forzamos que TODO se lea como texto (no como número/fecha).
        Esto es a propósito: muchos IDs de cuenta parecen números pero no
        deben tratarse como tales (perderíamos ceros a la izquierda, o
        pandas podría convertirlos a notación científica). Convertimos a
        número solo las columnas que sí vamos a calcular (más abajo).
    on_bad_lines="skip": si alguna fila viene mal formada en el CSV,
        la salta en vez de romper todo el script.
    """
    path = os.path.join(DATA_DIR, nombre_archivo)
    delim = detectar_delimitador(path)
    df = pd.read_csv(path, delimiter=delim, encoding="utf-8", dtype=str, on_bad_lines="skip")
    print(f"  · {nombre_archivo}: {len(df):,} filas, {len(df.columns)} columnas (delimitador '{delim}')")
    return df

print("=" * 70)
print("PASO 1 — Cargando los 8 archivos del dataset con pandas")
print("=" * 70)

# Cargamos las 8 tablas. Cada una queda como un DataFrame independiente
# en memoria piensa en cada uno como una "hoja de Excel" con sus propias
# columnas y filas.
facturacion = cargar_csv("FACTURACION-CLIENTES_.csv")
planta = cargar_csv("PLANTA CLIENTES.csv")
ordenes = cargar_csv("Ordenes.csv")
notas_credito = cargar_csv("NOTAS_CREDITO.csv")
prorrateo = cargar_csv("BRAINY_PRORRATEO_ALTASV3.csv")
reconexiones = cargar_csv("BRAINY_RECONEXIONESV3.csv")
descuentos = cargar_csv("BRAINY_DESCUENTOS_CUOTAS.csv")
catalogo = cargar_csv("CATALOGO-OFERTAS.csv")

# Ahora sí convertimos a número la ÚNICA columna que vamos a sumar:
# el monto de cada cargo. pd.to_numeric con errors="coerce" convierte
# cualquier valor no numérico en NaN (en vez de tirar error), y luego
# fillna(0.0) reemplaza esos NaN por 0 para que no rompan la suma.
facturacion["CHARGE_TOTAL_AMOUNT"] = pd.to_numeric(
    facturacion["CHARGE_TOTAL_AMOUNT"], errors="coerce"
).fillna(0.0)

print()
print("=" * 70)
print("PASO 1 — Normalizando llaves de cuenta en cada tabla")
print("=" * 70)

# PROBLEMA REAL DEL DATASET: cada tabla usa un nombre distinto de columna
# para referirse a "la misma cuenta financiera del cliente":
#   FACTURACION-CLIENTES -> FINANCIAL_ACCOUNT_KEY
#   BRAINY_PRORRATEO / RECONEXIONES -> CuentaFinanciera
#   BRAINY_DESCUENTOS -> cuentafinanciera (todo minúscula)
#   NOTAS_CREDITO -> BA_NO
# SOLUCIÓN: creamos en cada tabla una columna con el MISMO nombre
# ("cuenta_financiera") apuntando al valor real. Así, más adelante,
# podemos comparar/cruzar tablas sin acordarnos de estas diferencias.
# .str.strip() quita espacios en blanco accidentales al inicio/final
# (causa clásica de que dos IDs "iguales" no crucen por un espacio de más).
facturacion["cuenta_financiera"] = facturacion["FINANCIAL_ACCOUNT_KEY"].str.strip()
prorrateo["cuenta_financiera"] = prorrateo["CuentaFinanciera"].str.strip()
reconexiones["cuenta_financiera"] = reconexiones["CuentaFinanciera"].str.strip()
descuentos["cuenta_financiera"] = descuentos["cuentafinanciera"].str.strip()
notas_credito["cuenta_financiera"] = notas_credito["BA_NO"].str.strip()

# CASO ESPECIAL: Ordenes.csv NO tiene cuenta financiera, tiene CUSTOMER_KEY
# (identifica al cliente, no a la cuenta). Para poder cruzarla más adelante,
# también le sacamos el customer_key a la tabla de facturación, así ambas
# tablas comparten esa llave.
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

# groupby(["cuenta_financiera", "ciclo"]): agrupa todas las filas que
# comparten la misma cuenta Y el mismo ciclo de facturación (mismo recibo).
# .agg({...}) define qué hacer con cada columna dentro de cada grupo:
#   - total_ciclo_soles: sumar todos los montos del grupo -> total del recibo
#   - cantidad_cargos: contar cuántas filas (cargos) tiene ese recibo
#   - grupos_presentes: juntar en un solo texto todos los tipos de cargo
#     distintos (GRUPO) que aparecen en ese recibo, sin duplicados y ordenados
#   - customer_key: nos quedamos con el primero (es el mismo en todo el grupo)
# .reset_index(): convierte cuenta_financiera y ciclo de "índice" a columnas
# normales, para que quede como una tabla plana fácil de exportar.
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

# Convertimos cada columna de cuenta a un SET (conjunto).
# ¿Por qué un set y no un merge normal de pandas? Porque aquí solo nos
# interesa una pregunta binaria: "¿esta cuenta APARECE en esta tabla sí o no?"
# — no necesitamos traer columnas adicionales de esas tablas todavía.
# Buscar "¿está este valor en el set?" es muchísimo más rápido que buscar
# en una lista o hacer un merge completo, sobre todo con miles de filas.
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
    """
    Recibe una fila (un registro cuenta+ciclo) y revisa, una por una,
    si esa cuenta aparece en cada uno de los 5 sets que armamos arriba.
    Por cada coincidencia, agrega una etiqueta de causa a la lista.
    Si no coincide con ninguna, devuelve "SIN_CAUSA_ESPECIAL" — así el
    dato queda explícito en vez de dejarlo vacío/ambiguo.
    """
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


# .apply(detectar_causas, axis=1): ejecuta la función fila por fila
# (axis=1 = "recorre filas", axis=0 sería "recorre columnas").
# El resultado se guarda como una columna nueva.
resumen_ciclo["causas_detectadas"] = resumen_ciclo.apply(detectar_causas, axis=1)

# Nos quedamos solo con las columnas finales que queremos exportar,
# en el orden que queremos que aparezcan en el CSV de salida.
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

# Para el escenario de "reconexión" necesitamos algo más específico que
# solo "aparece en la tabla Brainy": queremos confirmar que el GRUPO real
# del cargo diga literalmente "CARGO POR RECONEXION". Por eso armamos un
# diccionario aparte: para cada (cuenta, ciclo), qué GRUPOS distintos tiene.
grupos_por_cuenta_ciclo = (
    facturacion.groupby(["cuenta_financiera", "ciclo"])["GRUPO"]
    .apply(lambda s: set(s.dropna()))
)

# Aquí vamos guardando los casos encontrados: {"a_prorrateo": (cuenta, ciclo), ...}
casos = {}


def primer_caso(mask, nombre):
    """
    Recibe una "máscara" booleana (una columna de True/False, una por fila,
    que dice si esa fila cumple cierta condición) y el nombre del escenario.
    Si ya tenemos un caso guardado para ese nombre, no hace nada (evita
    sobreescribir). Si no, filtra resumen_ciclo con esa máscara y, si hay
    al menos un resultado, guarda el PRIMERO como caso de ejemplo.
    """
    if nombre in casos:
        return
    candidatos = resumen_ciclo[mask]
    if not candidatos.empty:
        fila = candidatos.iloc[0]  # iloc[0] = primera fila del resultado
        casos[nombre] = (fila["cuenta_financiera"], fila["ciclo"])


# .isin(set): devuelve True/False por cada fila, según si el valor de esa
# columna está dentro del set dado. Es la versión "vectorizada" (rápida)
# de recorrer fila por fila preguntando "¿está en el set?".
primer_caso(resumen_ciclo["cuenta_financiera"].isin(cuentas_prorrateo), "a_prorrateo")
primer_caso(resumen_ciclo["cuenta_financiera"].isin(cuentas_descuento), "b_financiamiento")

# c) Reconexión: condición más específica, por eso usamos .apply() en vez
# de .isin() necesitamos consultar el diccionario grupos_por_cuenta_ciclo
# fila por fila, no solo comparar contra un set fijo.
reconexion_mask = resumen_ciclo.apply(
    lambda r: "CARGO POR RECONEXION" in grupos_por_cuenta_ciclo.get((r["cuenta_financiera"], r["ciclo"]), set()),
    axis=1,
)
primer_caso(reconexion_mask, "c_reconexion")

# d) Fin de descuento: de la tabla de descuentos, nos quedamos solo con las
# cuentas donde la columna FechaFin SÍ tiene un valor (.notna() = "no es
# nulo/vacío"). Esas son las que tienen un descuento con fecha de vencimiento.
cuentas_fin_descuento = set(descuentos.loc[descuentos["FechaFin"].notna(), "cuenta_financiera"])
primer_caso(resumen_ciclo["cuenta_financiera"].isin(cuentas_fin_descuento), "d_fin_descuento")

primer_caso(resumen_ciclo["customer_key"].isin(clientes_con_ordenes), "e_cambio_plan")

# Convertimos el diccionario "casos" en un DataFrame para poder exportarlo
# como CSV igual que los demás resultados.
casos_df = pd.DataFrame(
    [{"escenario": k, "cuenta_financiera": v[0], "ciclo": v[1]} for k, v in casos.items()]
)
casos_path = os.path.join(OUT_DIR, "casos_prueba_por_escenario.csv")
casos_df.to_csv(casos_path, index=False, encoding="utf-8")

# .iterrows(): recorre el DataFrame fila por fila para poder imprimir
# cada caso encontrado (solo para mostrar en consola, no afecta el CSV).
for _, r in casos_df.iterrows():
    print(f"  · {r['escenario']}: cuenta {r['cuenta_financiera']}, ciclo {r['ciclo']}")
print(f"  · Exportado a: {casos_path}")

print()
print("=" * 70)
print("PASO 1 completado. Insumos listos para el PASO 2 (motor de diffing).")
print("=" * 70)