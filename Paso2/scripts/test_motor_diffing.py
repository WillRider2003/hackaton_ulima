# -*- coding: utf-8 -*-
"""
PASO 2 — Suite de pruebas automatizadas del motor de diffing.

Responde la pregunta "¿esto está bien o no?" con hechos verificables,
no con inspección visual. Corresponde a la sección 10.1 (pruebas del
motor de diffing) y a las 5 pruebas obligatorias de la sección 11.5 de
la propuesta.

Qué se prueba:
  1. Los 5 escenarios críticos detectan la causa correcta (contra las
     cuentas reales verificadas en casos_prueba_corregidos.csv).
  2. Caso de control: una cuenta SIN variación real entre ciclos no debe
     generar ninguna línea ni forzar una explicación.
  3. Integridad matemática: la suma de los deltas de línea reportados
     coincide con el delta total del recibo (si no coincide, hay un
     error de agrupación o un cargo que se está perdiendo silenciosamente).
  4. Cuenta inexistente: el motor debe fallar explícitamente, nunca
     inventar datos para una cuenta que no existe.
  5. Anti-alucinación: cada monto que aparece en el "sustento" de una
     línea existe LITERALMENTE en la tabla Brainy correspondiente (se
     verifica leyendo la fila cruda del CSV, no solo confiando en lo que
     el motor dice que encontró).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paso2_motor_diffing import DatosReales, MotorDiffingReal

OK = "✓ PASS"
FAIL = "✗ FAIL"

resultados = []  # (nombre_prueba, ok: bool, detalle: str)


def check(nombre, condicion, detalle=""):
    resultados.append((nombre, bool(condicion), detalle))
    marca = OK if condicion else FAIL
    print(f"  {marca}  {nombre}" + (f"  -- {detalle}" if detalle and not condicion else ""))


print("=" * 70)
print("Cargando datos y motor...")
print("=" * 70)
datos = DatosReales()
motor = MotorDiffingReal(datos)

# --------------------------------------------------------------------- #
print()
print("PRUEBA 0 — Historial de hasta cinco ciclos previos")
print("-" * 70)

r_historial = motor.comparar("100001124", "20260715")
historial = r_historial["historial_5_ciclos"]
check(
    "Historial: devuelve los cinco ciclos previos disponibles",
    len(historial) == 5,
    f"cantidad obtenida: {len(historial)}",
)
check(
    "Historial: excluye el ciclo actual y esta ordenado del mas reciente al mas antiguo",
    [fila["ciclo"] for fila in historial] == ["20260615", "20260515", "20260415", "20260315", "20260215"],
    f"ciclos obtenidos: {[fila['ciclo'] for fila in historial]}",
)
check(
    "Historial: cada fila contiene total y delta contra su ciclo anterior",
    all({"ciclo", "total", "delta_vs_ciclo_anterior"} <= set(fila) for fila in historial),
)

# --------------------------------------------------------------------- #
print()
print("PRUEBA 1 — Los 5 escenarios criticos detectan la causa esperada")
print("-" * 70)

CASOS_ESPERADOS = [
    ("a_prorrateo", "716389015", "20260417", {"prorrateo"}),
    ("b_financiamiento", "757869240", "20260605", {"equipo_financiado", "reconexion", "no_explicado"}),
    ("c_reconexion", "100032914", "20260415", {"reconexion", "fin_prorrateo_anterior"}),
    ("d_fin_descuento", "758420349", "20260505", {"fin_descuento"}),
    ("e_cambio_plan", "100706563", "20260415", {"cambio_plan", "fin_descuento"}),
]

for nombre, cuenta, ciclo, causas_esperadas in CASOS_ESPERADOS:
    r = motor.comparar(cuenta, ciclo)
    causas_obtenidas = {l["causa"] for l in r["lineas"]}
    # el escenario "titular" de cada caso debe estar presente en las causas
    causa_titular = {
        "a_prorrateo": "prorrateo", "b_financiamiento": "equipo_financiado",
        "c_reconexion": "reconexion", "d_fin_descuento": "fin_descuento", "e_cambio_plan": "cambio_plan",
    }[nombre]
    check(
        f"{nombre}: causa '{causa_titular}' detectada (cuenta {cuenta}, ciclo {ciclo})",
        causa_titular in causas_obtenidas,
        f"causas obtenidas: {causas_obtenidas}",
    )
    # ninguna causa inesperada (que no este en el set permitido)
    inesperadas = causas_obtenidas - causas_esperadas
    check(
        f"{nombre}: sin causas fuera de lo esperado",
        len(inesperadas) == 0,
        f"causas no previstas: {inesperadas}",
    )

# --------------------------------------------------------------------- #
print()
print("PRUEBA 1.5 — Trazabilidad por linea")
print("-" * 70)

r_trazabilidad = motor.comparar("100032914", "20260415")
linea_trazable = next(linea for linea in r_trazabilidad["lineas"] if linea["causa"] == "reconexion")
trazabilidad = linea_trazable["trazabilidad"]
check(
    "Reconexión: trazabilidad incluye tabla, llave y campos usados",
    {"tabla", "llave_fuente", "campos_usados"} <= set(trazabilidad),
)
check(
    "Reconexión: trazabilidad identifica la fila fuente exacta",
    trazabilidad["llave_fuente"] == {"CuentaFinanciera": "100032914", "Ciclica": "15/04/2026"},
    f"llave obtenida: {trazabilidad['llave_fuente']}",
)
check(
    "Reconexión: trazabilidad conserva el monto usado como evidencia",
    trazabilidad["campos_usados"].get("Monto") == linea_trazable["sustento"]["monto_sustento"],
)

# --------------------------------------------------------------------- #
print()
print("PRUEBA 1.6 — Conciliacion de notas de credito")
print("-" * 70)

nota_ejemplo = datos.notas_credito[
    (datos.notas_credito["cuenta_financiera"] == "369862062")
    & (datos.notas_credito["ciclo_norm"] == "20260715")
].iloc[0]
monto_nota = float(nota_ejemplo["AMOUNT"])
nota_conciliada = motor._buscar_nota_credito_conciliada("369862062", "20260715", monto_nota)
check(
    "Nota de credito: encuentra una fila cuyo importe coincide con el delta",
    nota_conciliada is not None and nota_conciliada["tipo"] == "fila_exacta",
)
nota_no_conciliada = motor._buscar_nota_credito_conciliada("369862062", "20260715", monto_nota + 0.37)
check(
    "Nota de credito: no atribuye la causa si el importe no concilia",
    nota_no_conciliada is None,
)

# --------------------------------------------------------------------- #
print()
print("PRUEBA 1.7 — Estado de conciliacion de importes")
print("-" * 70)

check(
    "Conciliacion: delta y sustento iguales se marcan como exactos",
    motor._conciliacion_importe(4.58, 4.58)["estado"] == "exacta",
)
check(
    "Conciliacion: diferencia de importe se marca como parcial",
    motor._conciliacion_importe(8.75, 7.44)["estado"] == "parcial",
)
check(
    "Conciliacion: evidencia sin importe comparable se marca como no conciliada",
    motor._conciliacion_importe(8.75, None)["estado"] == "no_conciliada",
)
r_conciliacion = motor.comparar("100032914", "20260415")
linea_conciliada = next(linea for linea in r_conciliacion["lineas"] if linea["causa"] == "reconexion")
check(
    "Reconexión: expone el estado de conciliacion junto al sustento",
    linea_conciliada["sustento"]["conciliacion_importe"]["estado"] in {"exacta", "parcial", "no_conciliada"},
)

# --------------------------------------------------------------------- #
print()
print("PRUEBA 1.8 — Estado de resolucion")
print("-" * 70)

check(
    "Estado: primer recibo se marca sin_ciclo_previo",
    motor.comparar("716389015", "20260417")["estado_resultado"] == "sin_ciclo_previo",
)
check(
    "Estado: recibo sin diferencia se marca sin_variacion",
    motor.comparar("100001124", "20260415")["estado_resultado"] == "sin_variacion",
)
check(
    "Estado: causas completamente sustentadas se marcan resuelto",
    motor.comparar("100032914", "20260415")["estado_resultado"] == "resuelto",
)
check(
    "Estado: delta no sustentado se marca requiere_revision",
    motor.comparar("757869240", "20260605")["estado_resultado"] == "requiere_revision",
)

# --------------------------------------------------------------------- #
print()
print("PRUEBA 1.9 — Casos limite del motor")
print("-" * 70)

r_multiple = motor.comparar("100706563", "20260415")
causas_multiple = {linea["causa"] for linea in r_multiple["lineas"]}
check(
    "Causa multiple: conserva cambio de plan y fin de descuento por separado",
    {"cambio_plan", "fin_descuento"} <= causas_multiple,
    f"causas obtenidas: {causas_multiple}",
)
r_fin_reconexion = motor.comparar("100032914", "20260515")
causas_fin_reconexion = {linea["causa"] for linea in r_fin_reconexion["lineas"]}
check(
    "Reconexión que desaparece: se explica como fin_reconexion_anterior",
    "fin_reconexion_anterior" in causas_fin_reconexion,
    f"causas obtenidas: {causas_fin_reconexion}",
)
check(
    "Reconexión que desaparece: no se degrada a no_explicado",
    "no_explicado" not in causas_fin_reconexion,
    f"causas obtenidas: {causas_fin_reconexion}",
)

# --------------------------------------------------------------------- #
print()
print("PRUEBA 2 — Caso de control: cuenta SIN variacion real")
print("-" * 70)

# cuenta 100001124: total identico (S/ 82.90) en los 6 ciclos disponibles
# (verificado por calculo directo sobre el CSV, ver README de Paso2)
r_control = motor.comparar("100001124", "20260415")
check(
    "Cuenta de control (100001124): hay_variacion == False",
    r_control["hay_variacion"] == False,  # noqa: E712 (numpy.bool_ vs bool, "is" no sirve aqui)
    f"delta_total obtenido: {r_control['delta_total']}",
)
check(
    "Cuenta de control (100001124): no genera lineas forzadas",
    len(r_control["lineas"]) == 0,
    f"lineas generadas: {[l['causa'] for l in r_control['lineas']]}",
)

# --------------------------------------------------------------------- #
print()
print("PRUEBA 3 — Integridad matematica: suma de lineas == delta total")
print("-" * 70)

for nombre, cuenta, ciclo, _ in CASOS_ESPERADOS:
    r = motor.comparar(cuenta, ciclo)
    if r.get("sin_ciclo_previo"):
        continue  # no aplica, no hay delta_total que verificar
    suma_lineas = round(sum(l["delta"] for l in r["lineas"]), 2)
    check(
        f"{nombre}: suma de deltas de linea (S/ {suma_lineas}) == delta total (S/ {r['delta_total']})",
        abs(suma_lineas - r["delta_total"]) < 0.02,
        f"diferencia: {round(suma_lineas - r['delta_total'], 2)}",
    )

# --------------------------------------------------------------------- #
print()
print("PRUEBA 4 — Cuenta inexistente: debe fallar explicitamente, no inventar")
print("-" * 70)

try:
    motor.comparar("CUENTA_QUE_NO_EXISTE_999999", None)
    check("Cuenta inexistente lanza ValueError", False, "no se lanzo ninguna excepcion")
except ValueError:
    check("Cuenta inexistente lanza ValueError", True)

try:
    motor.comparar("100001124", "20990101")
    check("Ciclo inexistente lanza ValueError descriptivo", False, "no se lanzo ninguna excepcion")
except ValueError as e:
    mensaje = str(e)
    check(
        "Ciclo inexistente lanza ValueError descriptivo",
        "Ciclo 20990101 no encontrado para la cuenta 100001124" in mensaje
        and "Ciclos disponibles:" in mensaje,
        mensaje,
    )

# --------------------------------------------------------------------- #
print()
print("PRUEBA 5 — Anti-alucinacion: el sustento coincide LITERALMENTE con la fila cruda del CSV")
print("-" * 70)

# a) Prorrateo: el monto_sustento debe ser exactamente igual a suma_prorrateo
#    en BRAINY_PRORRATEO_ALTASV3.csv para esa cuenta+ciclo (lectura directa,
#    sin pasar por el motor).
fila_cruda = datos.prorrateo[
    (datos.prorrateo["cuenta_financiera"] == "716389015") & (datos.prorrateo["ciclo_norm"] == "20260417")
].iloc[0]
r = motor.comparar("716389015", "20260417")
linea_prorrateo = next(l for l in r["lineas"] if l["causa"] == "prorrateo")
check(
    "Prorrateo: monto_sustento == valor literal en BRAINY_PRORRATEO_ALTASV3.csv",
    abs(linea_prorrateo["sustento"]["monto_sustento"] - float(fila_cruda["suma_prorrateo"])) < 0.001,
    f"motor={linea_prorrateo['sustento']['monto_sustento']} vs csv={fila_cruda['suma_prorrateo']}",
)

# b) Reconexion: el monto_sustento debe ser exactamente igual a Monto en
#    BRAINY_RECONEXIONESV3.csv para esa cuenta+ciclo.
fila_cruda_rx = datos.reconexiones[
    (datos.reconexiones["cuenta_financiera"] == "100032914") & (datos.reconexiones["ciclo_norm"] == "20260415")
].iloc[0]
r2 = motor.comparar("100032914", "20260415")
linea_rx = next(l for l in r2["lineas"] if l["causa"] == "reconexion")
check(
    "Reconexion: monto_sustento == valor literal en BRAINY_RECONEXIONESV3.csv",
    abs(linea_rx["sustento"]["monto_sustento"] - float(fila_cruda_rx["Monto"])) < 0.001,
    f"motor={linea_rx['sustento']['monto_sustento']} vs csv={fila_cruda_rx['Monto']}",
)

# c) Fin de descuento: el porcentaje_promo debe ser exactamente igual a
#    PorcentajePromo en BRAINY_DESCUENTOS_CUOTAS.csv.
fila_cruda_desc = datos.descuentos[
    (datos.descuentos["cuenta_financiera"] == "758420349") & (datos.descuentos["ciclo_norm"] == "20260405")
]
r3 = motor.comparar("758420349", "20260505")
linea_desc = next(l for l in r3["lineas"] if l["causa"] == "fin_descuento")
porcentaje_csv = float(fila_cruda_desc.iloc[0]["PorcentajePromo"]) if not fila_cruda_desc.empty else None
check(
    "Fin de descuento: porcentaje_promo == valor literal en BRAINY_DESCUENTOS_CUOTAS.csv",
    porcentaje_csv is not None and abs(linea_desc["sustento"]["porcentaje_promo"] - porcentaje_csv) < 0.001,
    f"motor={linea_desc['sustento']['porcentaje_promo']} vs csv={porcentaje_csv}",
)

# La respuesta completa debe poder entregarse directamente a una API/Dify.
import json
r_json = motor.comparar("100032914", "20260415")
try:
    json.dumps(r_json, ensure_ascii=False)
    check("Salida del motor es serializable a JSON", True)
except (TypeError, ValueError) as e:
    check("Salida del motor es serializable a JSON", False, str(e))

# --------------------------------------------------------------------- #
print()
print("=" * 70)
total = len(resultados)
pasadas = sum(1 for _, ok, _ in resultados if ok)
print(f"RESUMEN: {pasadas}/{total} pruebas OK")
if pasadas < total:
    print()
    print("Pruebas que fallaron:")
    for nombre, ok, detalle in resultados:
        if not ok:
            print(f"  - {nombre}  ({detalle})")
    sys.exit(1)
print("=" * 70)
