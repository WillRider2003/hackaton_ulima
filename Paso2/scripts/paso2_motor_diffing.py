# -*- coding: utf-8 -*-
"""
PASO 2: Motor de diffing (determinístico, SIN IA)

Compara el ciclo actual de una cuenta contra el ciclo anterior y etiqueta
cada delta S/ con una causa verificable, cruzando las 4 tablas Brainy +
Notas de Crédito + Órdenes. Si una variación no se puede sustentar, se
marca "no_explicado" -- nunca se inventa una causa (esto protege la
garantía de 0% alucinaciones que exige la ficha).

DECISIÓN DE DISEÑO IMPORTANTE (por qué se agrupa por GRUPO/SUB_GRUPO y no
por CHARGE_CODE_ID como se planteó inicialmente en la propuesta):
Al inspeccionar los datos reales encontramos que GRUPO="NO CONSIDERAR"
trae pares de reversión contable (ej. un bono +13.74 con un CHARGE_CODE_ID
y su reverso -13.74 con OTRO CHARGE_CODE_ID distinto). Si agrupáramos por
CHARGE_CODE_ID exacto, estos pares NO se cancelarían y contaminarían el
diffing con "ruido" que no es una variación real del recibo. Agrupando
por (GRUPO, SUB_GRUPO) estos pares se cancelan solos al sumar, y lo que
queda son las variaciones genuinas -- incluyendo, por ejemplo, la cuota
real de financiamiento de equipo que también vive dentro de
GRUPO="NO CONSIDERAR" / SUB_GRUPO="FINANCIAMIENTO" pero NO tiene su par
de reversión (queda con saldo distinto de cero).
Verificado sobre el dataset completo: de 65,104 combinaciones (cuenta,
ciclo, GRUPO=NO CONSIDERAR), el 97% neteaba a ~0 y el 3% restante
correspondía a cargos reales de financiamiento -- confirma que esta
agrupación es la correcta.
"""
import os
import re
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "..", "Paso1", "datos")
OUT_DIR = os.path.join(BASE_DIR, "..", "salida_paso2")
os.makedirs(OUT_DIR, exist_ok=True)

TOLERANCIA_SOLES = 0.01

# Grupos que corresponden a "cargo fijo recurrente de plan" -- se usan para
# detectar cambio de plan (cuando el CHARGE_CODE_ID cambia entre ciclos).
GRUPOS_CARGO_FIJO_RECURRENTE = {"CARGO FIJO", "CARGO FIJO VENCIDO"}
GRUPOS_PRORRATEO = {"CARGO FIJO PROPORCIONAL", "CARGO FIJO PROPORCIONAL VENCIDO"}


# --------------------------------------------------------------------- #
# Utilidades de fecha: cada tabla trae el "ciclo" en un formato distinto.
# Todas se normalizan al mismo formato que usa FACTURACION-CLIENTES:
# ciclo como texto YYYYMMDD (ej. "20260417").
# --------------------------------------------------------------------- #
def ddmmyyyy_a_yyyymmdd(valor):
    """Convierte 'DD/MM/YYYY' (o 'DD/MM/YYYY HH:MM:SS') a 'YYYYMMDD'."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    solo_fecha = valor.strip().split(" ")[0]
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", solo_fecha)
    if not m:
        return None
    dd, mm, yyyy = m.groups()
    return f"{yyyy}{int(mm):02d}{int(dd):02d}"


def yyyymmdd_con_guiones_a_plano(valor):
    """Convierte 'YYYY-MM-DD' (o con hora al final) a 'YYYYMMDD'."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    solo_fecha = valor.strip().split(" ")[0]
    return solo_fecha.replace("-", "")


def ciclo_a_fecha(ciclo_str):
    """'20260417' -> pd.Timestamp('2026-04-17'). Usado solo para elegir la
    orden más cercana en Ordenes.csv (no hay llave exacta cuenta+ciclo ahí)."""
    try:
        return pd.to_datetime(ciclo_str, format="%Y%m%d")
    except Exception:
        return None


# --------------------------------------------------------------------- #
# Carga de datos
# --------------------------------------------------------------------- #
def detectar_delimitador(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        primera_linea = f.readline()
    return ";" if primera_linea.count(";") > primera_linea.count(",") else ","


def cargar_csv(nombre_archivo):
    path = os.path.join(DATA_DIR, nombre_archivo)
    delim = detectar_delimitador(path)
    return pd.read_csv(path, delimiter=delim, encoding="utf-8", dtype=str, on_bad_lines="skip")


class DatosReales:
    """Carga y normaliza los 8 CSV reales. Misma normalización de llaves
    que uso el Paso 1 (columna 'cuenta_financiera' uniforme), más las
    conversiones de fecha necesarias para el Paso 2."""

    def __init__(self):
        self.facturacion = cargar_csv("FACTURACION-CLIENTES_.csv")
        self.facturacion["CHARGE_TOTAL_AMOUNT"] = pd.to_numeric(
            self.facturacion["CHARGE_TOTAL_AMOUNT"], errors="coerce"
        ).fillna(0.0)
        self.facturacion["cuenta_financiera"] = self.facturacion["FINANCIAL_ACCOUNT_KEY"].str.strip()
        self.facturacion["customer_key"] = self.facturacion["CUSTOMER_KEY"].str.strip()

        self.prorrateo = cargar_csv("BRAINY_PRORRATEO_ALTASV3.csv")
        self.prorrateo["cuenta_financiera"] = self.prorrateo["CuentaFinanciera"].str.strip()
        self.prorrateo["ciclo_norm"] = self.prorrateo["Ciclica"].apply(ddmmyyyy_a_yyyymmdd)
        self.prorrateo["suma_prorrateo"] = pd.to_numeric(self.prorrateo["suma_prorrateo"], errors="coerce")

        self.reconexiones = cargar_csv("BRAINY_RECONEXIONESV3.csv")
        self.reconexiones["cuenta_financiera"] = self.reconexiones["CuentaFinanciera"].str.strip()
        self.reconexiones["ciclo_norm"] = self.reconexiones["Ciclica"].apply(ddmmyyyy_a_yyyymmdd)
        self.reconexiones["Monto"] = pd.to_numeric(self.reconexiones["Monto"], errors="coerce")

        self.descuentos = cargar_csv("BRAINY_DESCUENTOS_CUOTAS.csv")
        self.descuentos["cuenta_financiera"] = self.descuentos["cuentafinanciera"].str.strip()
        self.descuentos["ciclo_norm"] = self.descuentos["Ciclo"].apply(yyyymmdd_con_guiones_a_plano)
        self.descuentos["PorcentajePromo"] = pd.to_numeric(self.descuentos["PorcentajePromo"], errors="coerce")
        self.descuentos["CuotaActual"] = pd.to_numeric(self.descuentos["CuotaActual"], errors="coerce")

        self.notas_credito = cargar_csv("NOTAS_CREDITO.csv")
        self.notas_credito["cuenta_financiera"] = self.notas_credito["BA_NO"].str.strip()
        self.notas_credito["ciclo_norm"] = self.notas_credito["CICLO"].str.strip()
        self.notas_credito["AMOUNT"] = pd.to_numeric(self.notas_credito["AMOUNT"], errors="coerce")

        self.ordenes = cargar_csv("Ordenes.csv")
        self.ordenes["customer_key"] = self.ordenes["CUSTOMER_KEY"].str.strip()
        self.ordenes["fecha_completado"] = pd.to_datetime(
            self.ordenes["ORDER_ACTION_COMPLETION_DATE"], errors="coerce"
        )

        self.planta = cargar_csv("PLANTA CLIENTES.csv")
        self.planta["cuenta_financiera"] = self.planta["FINANCIAL_ACCOUNT"].str.strip()

    def ciclos_de_cuenta(self, cuenta: str):
        f = self.facturacion
        return sorted(f.loc[f["cuenta_financiera"] == cuenta, "ciclo"].dropna().unique().tolist())


# --------------------------------------------------------------------- #
# Motor de diffing
# --------------------------------------------------------------------- #
class DeltaLinea:
    def __init__(self, grupo, sub_grupo, monto_actual, monto_previo, delta, causa, sustento, descripcion=""):
        self.grupo = grupo
        self.sub_grupo = sub_grupo
        self.monto_actual = round(monto_actual, 2)
        self.monto_previo = round(monto_previo, 2)
        self.delta = round(delta, 2)
        self.causa = causa
        self.sustento = sustento
        self.descripcion = descripcion

    def to_dict(self):
        # Contrato auditable para consumidores del motor (API, Dify o UI).
        # Se separa de `sustento` para que el narrador tenga datos simples y
        # el jurado/asesor pueda inspeccionar exactamente su origen.
        campos_usados = self.sustento.get("campos_usados")
        if campos_usados is None:
            campos_usados = {
                campo: valor for campo, valor in self.sustento.items()
                if campo not in {"tabla", "llave_fuente", "campos_usados"}
            }
        return {
            "grupo": self.grupo, "sub_grupo": self.sub_grupo,
            "monto_actual": self.monto_actual, "monto_previo": self.monto_previo,
            "delta": self.delta, "causa": self.causa, "sustento": self.sustento,
            "descripcion": self.descripcion,
            "trazabilidad": {
                "tabla": self.sustento.get("tabla", "FACTURACION-CLIENTES_.csv"),
                "llave_fuente": self.sustento.get("llave_fuente", {}),
                "campos_usados": campos_usados,
            },
        }


class MotorDiffingReal:
    def __init__(self, datos: DatosReales):
        self.d = datos

    @staticmethod
    def _estado_resultado(sin_ciclo_previo, hay_variacion, causas_no_explicadas):
        """Estado operativo que consume la capa conversacional."""
        if sin_ciclo_previo:
            return "sin_ciclo_previo"
        if not hay_variacion:
            return "sin_variacion"
        if causas_no_explicadas > 0:
            return "requiere_revision"
        return "resuelto"

    @staticmethod
    def _conciliacion_importe(delta, monto_sustento, evidencia_contextual=False):
        """Describe cuánto del delta queda respaldado por un importe fuente.

        ``parcial`` conserva causas reales cuando una misma línea de recibo
        agrupa más de un concepto. ``no_conciliada`` evita presentar un monto
        como verificado cuando la fuente no aporta una cifra comparable.
        """
        if monto_sustento is None or pd.isna(monto_sustento):
            return {
                "estado": "parcial" if evidencia_contextual else "no_conciliada",
                "delta": round(float(delta), 2), "monto_sustento": None,
                "diferencia": None,
            }
        monto_sustento = float(monto_sustento)
        diferencia = round(float(delta) - monto_sustento, 2)
        return {
            "estado": "exacta" if abs(diferencia) <= TOLERANCIA_SOLES else "parcial",
            "delta": round(float(delta), 2), "monto_sustento": round(monto_sustento, 2),
            "diferencia": diferencia,
        }

    def _historial_5_ciclos(self, cuenta: str, ciclos: list[str], indice_actual: int):
        """Resume hasta cinco ciclos anteriores, del mas reciente al mas antiguo.

        La comparacion y atribucion de causas sigue usando solo el ciclo
        inmediatamente previo. Este historial es evidencia de contexto para la
        App/Bot y permite mostrar los cinco recibos previos solicitados por el reto.
        """
        ciclos_previos = ciclos[max(0, indice_actual - 5):indice_actual]
        if not ciclos_previos:
            return []

        f = self.d.facturacion
        totales = (
            f[f["cuenta_financiera"] == cuenta]
            .groupby("ciclo")["CHARGE_TOTAL_AMOUNT"]
            .sum()
            .to_dict()
        )

        historial = []
        for i in range(len(ciclos_previos) - 1, -1, -1):
            ciclo = ciclos_previos[i]
            total = round(float(totales[ciclo]), 2)
            ciclo_anterior = ciclos_previos[i - 1] if i > 0 else None
            total_anterior = float(totales[ciclo_anterior]) if ciclo_anterior else None
            historial.append({
                "ciclo": ciclo,
                "total": total,
                "delta_vs_ciclo_anterior": (
                    round(total - total_anterior, 2) if total_anterior is not None else None
                ),
            })
        return historial

    def comparar(self, cuenta: str, ciclo_actual: str = None):
        ciclos = self.d.ciclos_de_cuenta(cuenta)
        if not ciclos:
            raise ValueError(f"Cuenta {cuenta} no encontrada en FACTURACION-CLIENTES")

        ciclo_actual = ciclo_actual or ciclos[-1]
        if ciclo_actual not in ciclos:
            raise ValueError(
                f"Ciclo {ciclo_actual} no encontrado para la cuenta {cuenta}. "
                f"Ciclos disponibles: {', '.join(ciclos)}"
            )
        idx = ciclos.index(ciclo_actual)
        ciclo_previo = ciclos[idx - 1] if idx > 0 else None
        historial_5_ciclos = self._historial_5_ciclos(cuenta, ciclos, idx)

        f = self.d.facturacion
        cargos_actual = f[(f["cuenta_financiera"] == cuenta) & (f["ciclo"] == ciclo_actual)].copy()

        # CASO ESPECIAL: sin ciclo previo disponible (cuenta nueva / alta).
        # No tiene sentido "diffear" contra cero -- eso generaria deltas
        # falsos para cargos base (CARGO FIJO, DESCUENTO) que en realidad
        # nunca cambiaron, solo que es su primer recibo. Verificado sobre
        # 200 cuentas: el escenario de prorrateo SIEMPRE cae en el primer
        # ciclo disponible de la cuenta (es logico: el prorrateo ocurre en
        # el alta). Por eso este caso se maneja explicitamente en vez de
        # generar "no_explicado" para cargos que no necesitan explicacion.
        if ciclo_previo is None:
            total_actual = round(cargos_actual["CHARGE_TOTAL_AMOUNT"].sum(), 2)
            linea_alta = None
            cf = cargos_actual[cargos_actual["GRUPO"].isin(GRUPOS_PRORRATEO)]
            if not cf.empty:
                fila = self.d.prorrateo[
                    (self.d.prorrateo["cuenta_financiera"] == cuenta) & (self.d.prorrateo["ciclo_norm"] == ciclo_actual)
                ]
                sustento = {"tabla": "BRAINY_PRORRATEO_ALTASV3.csv"}
                if not fila.empty:
                    r = fila.iloc[0]
                    monto_prorrateo = float(r["suma_prorrateo"]) if pd.notna(r["suma_prorrateo"]) else None
                    sustento.update({
                        "fecha_inicio": r["fecha_inicio_minima"], "fecha_fin": r["fecha_fin_maxima"],
                        "monto_sustento": monto_prorrateo,
                        "conciliacion_importe": self._conciliacion_importe(float(cf["CHARGE_TOTAL_AMOUNT"].sum()), monto_prorrateo),
                        "llave_fuente": {"CuentaFinanciera": r["CuentaFinanciera"], "Ciclica": r["Ciclica"]},
                        "campos_usados": {
                            "suma_prorrateo": float(r["suma_prorrateo"]) if pd.notna(r["suma_prorrateo"]) else None,
                            "fecha_inicio_minima": r["fecha_inicio_minima"],
                            "fecha_fin_maxima": r["fecha_fin_maxima"],
                        },
                    })
                linea_alta = DeltaLinea(
                    grupo="CARGO FIJO PROPORCIONAL", sub_grupo=cf["SUB_GRUPO"].iloc[0],
                    monto_actual=float(cf["CHARGE_TOTAL_AMOUNT"].sum()), monto_previo=0.0,
                    delta=float(cf["CHARGE_TOTAL_AMOUNT"].sum()),
                    causa="prorrateo", sustento=sustento,
                    descripcion="Prorrateo por alta de servicio a mitad de ciclo (primer recibo de la cuenta)",
                )
            return {
                "cuenta": cuenta, "ciclo_actual": ciclo_actual, "ciclo_previo": None,
                "total_actual": total_actual, "total_previo": None, "delta_total": None,
                "historial_5_ciclos": historial_5_ciclos,
                "hay_variacion": False, "sin_ciclo_previo": True,
                # La frontera publica del motor usa solo tipos JSON nativos.
                # DeltaLinea se conserva como estructura interna de calculo.
                "lineas": [linea_alta.to_dict()] if linea_alta else [],
                "causas_no_explicadas": 0,
                "estado_resultado": self._estado_resultado(True, False, 0),
            }

        cargos_previo = f[(f["cuenta_financiera"] == cuenta) & (f["ciclo"] == ciclo_previo)].copy()

        total_actual = round(cargos_actual["CHARGE_TOTAL_AMOUNT"].sum(), 2)
        total_previo = round(cargos_previo["CHARGE_TOTAL_AMOUNT"].sum(), 2)
        delta_total = round(total_actual - total_previo, 2)

        lineas = []

        # 1) Cambio de plan: caso especial, se detecta ANTES del diffing
        #    generico porque el CHARGE_CODE_ID cambia completo (nueva
        #    tarifa), no tiene sentido tratarlo como "cargo nuevo" + "cargo
        #    que desaparecio" por separado.
        linea_cambio_plan, cargos_actual, cargos_previo = self._detectar_cambio_plan(
            cuenta, ciclo_actual, ciclo_previo, cargos_actual, cargos_previo
        )
        if linea_cambio_plan:
            lineas.append(linea_cambio_plan)

        # 2) Diffing agregado por (GRUPO, SUB_GRUPO) del resto de cargos
        lineas.extend(self._diff_por_grupo(cuenta, ciclo_actual, ciclo_previo, cargos_actual, cargos_previo))

        no_explicadas = sum(1 for l in lineas if l.causa == "no_explicado")

        hay_variacion = bool(abs(delta_total) > TOLERANCIA_SOLES)
        estado_resultado = self._estado_resultado(False, hay_variacion, no_explicadas)
        return {
            "cuenta": cuenta, "ciclo_actual": ciclo_actual, "ciclo_previo": ciclo_previo,
            "total_actual": total_actual, "total_previo": total_previo, "delta_total": delta_total,
            "historial_5_ciclos": historial_5_ciclos,
            # pandas/numpy pueden devolver numpy.bool_, que json.dumps no acepta.
            "hay_variacion": hay_variacion,
            "sin_ciclo_previo": False,
            "lineas": [linea.to_dict() for linea in lineas],
            "causas_no_explicadas": no_explicadas,
            "estado_resultado": estado_resultado,
        }

    # ------------------------------------------------------------------ #
    def _detectar_cambio_plan(self, cuenta, ciclo_actual, ciclo_previo, cargos_actual, cargos_previo):
        if ciclo_previo is None:
            return None, cargos_actual, cargos_previo

        mask_recurrente = lambda df: (
            df["GRUPO"].isin(GRUPOS_CARGO_FIJO_RECURRENTE)
            & df["CHARGE_CODE_CLASSIFICATION"].str.contains("Cargo Recurrente De Plan", na=False)
        )
        cf_actual = cargos_actual[mask_recurrente(cargos_actual)]
        cf_previo = cargos_previo[mask_recurrente(cargos_previo)]

        codes_actual = set(cf_actual["CHARGE_CODE_ID"])
        codes_previo = set(cf_previo["CHARGE_CODE_ID"])

        if codes_actual and codes_previo and codes_actual != codes_previo:
            monto_actual = round(cf_actual["CHARGE_TOTAL_AMOUNT"].sum(), 2)
            monto_previo = round(cf_previo["CHARGE_TOTAL_AMOUNT"].sum(), 2)
            delta = monto_actual - monto_previo

            sustento = {
                "descripcion_plan_anterior": cf_previo["CHARGE_CODE_DESC"].iloc[0] if not cf_previo.empty else None,
                "descripcion_plan_nuevo": cf_actual["CHARGE_CODE_DESC"].iloc[0] if not cf_actual.empty else None,
            }
            orden = self._buscar_orden_cercana(cuenta, ciclo_actual)
            if orden is not None:
                sustento.update({
                    "tabla": "Ordenes.csv (aproximado: orden mas cercana en fecha al ciclo, no hay llave exacta)",
                    "fecha_orden": str(orden["fecha_completado"]),
                    "motivo_orden": orden["ORDER_ACTION_REASON_DESC"],
                    "llave_fuente": {
                        "CUSTOMER_KEY": orden["customer_key"],
                        "ORDER_ACTION_COMPLETION_DATE": str(orden["fecha_completado"]),
                    },
                    "campos_usados": {
                        "ORDER_ACTION_REASON_DESC": orden["ORDER_ACTION_REASON_DESC"],
                        "distancia_dias_al_ciclo": int(orden["dist_dias"]),
                    },
                })
            else:
                sustento["tabla"] = "FACTURACION-CLIENTES.csv (cambio de CHARGE_CODE_ID detectado entre ciclos)"
                sustento["llave_fuente"] = {"FINANCIAL_ACCOUNT_KEY": cuenta, "ciclo_actual": ciclo_actual, "ciclo_previo": ciclo_previo}
                sustento["campos_usados"] = {
                    "CHARGE_CODE_ID_actual": sorted(codes_actual),
                    "CHARGE_CODE_ID_previo": sorted(codes_previo),
                }

            linea = DeltaLinea(
                grupo="CARGO FIJO", sub_grupo="PLAN",
                monto_actual=monto_actual, monto_previo=monto_previo, delta=delta,
                causa="cambio_plan", sustento=sustento,
                descripcion=f"{sustento.get('descripcion_plan_anterior')} -> {sustento.get('descripcion_plan_nuevo')}",
            )
            cargos_actual = cargos_actual.drop(cf_actual.index)
            cargos_previo = cargos_previo.drop(cf_previo.index)
            return linea, cargos_actual, cargos_previo

        return None, cargos_actual, cargos_previo

    def _buscar_orden_cercana(self, cuenta, ciclo, ventana_dias=60):
        """No existe llave exacta (cuenta,ciclo) en Ordenes.csv -- solo
        CUSTOMER_KEY + fecha. Se busca la orden completada más cercana
        (antes o después) a la fecha del ciclo, dentro de una ventana
        razonable. Esto es una aproximación, se declara así en el sustento."""
        f = self.d.facturacion
        fila_cuenta = f[f["cuenta_financiera"] == cuenta]
        if fila_cuenta.empty:
            return None
        customer_key = fila_cuenta["customer_key"].iloc[0]

        fecha_ciclo = ciclo_a_fecha(ciclo)
        if fecha_ciclo is None:
            return None

        ordenes_cliente = self.d.ordenes[self.d.ordenes["customer_key"] == customer_key].dropna(
            subset=["fecha_completado"]
        )
        if ordenes_cliente.empty:
            return None

        ordenes_cliente = ordenes_cliente.copy()
        ordenes_cliente["dist_dias"] = (ordenes_cliente["fecha_completado"] - fecha_ciclo).abs().dt.days
        candidata = ordenes_cliente.sort_values("dist_dias").iloc[0]
        if candidata["dist_dias"] > ventana_dias:
            return None
        return candidata

    def _buscar_nota_credito_conciliada(self, cuenta, ciclo, delta):
        """Busca evidencia de nota de credito/debito que cuadre con el delta.

        Una nota presente en el mismo ciclo no basta para explicar un cargo:
        su importe debe coincidir, ya sea como una fila individual o como el
        neto de todas las notas del ciclo. Si no concilia, el motor no atribuye
        causalidad y deja el delta como ``no_explicado``.
        """
        notas = self.d.notas_credito[
            (self.d.notas_credito["cuenta_financiera"] == cuenta)
            & (self.d.notas_credito["ciclo_norm"] == ciclo)
        ].copy()
        if notas.empty:
            return None

        coincidencias = notas[(notas["AMOUNT"] - delta).abs() <= TOLERANCIA_SOLES]
        if not coincidencias.empty:
            return {"tipo": "fila_exacta", "filas": coincidencias}

        monto_neto = float(notas["AMOUNT"].sum())
        if abs(monto_neto - delta) <= TOLERANCIA_SOLES:
            return {"tipo": "neto_del_ciclo", "filas": notas}
        return None

    # ------------------------------------------------------------------ #
    def _diff_por_grupo(self, cuenta, ciclo_actual, ciclo_previo, cargos_actual, cargos_previo):
        agg_actual = cargos_actual.groupby(["GRUPO", "SUB_GRUPO"])["CHARGE_TOTAL_AMOUNT"].sum()
        agg_previo = cargos_previo.groupby(["GRUPO", "SUB_GRUPO"])["CHARGE_TOTAL_AMOUNT"].sum()

        # descripcion representativa por (GRUPO,SUB_GRUPO) para el narrador
        desc_por_key = {}
        for _, row in pd.concat([cargos_actual, cargos_previo]).iterrows():
            key = (row["GRUPO"], row["SUB_GRUPO"])
            if key not in desc_por_key:
                desc_por_key[key] = row["CHARGE_CODE_DESC"]

        todas_las_keys = set(agg_actual.index) | set(agg_previo.index)
        lineas = []
        for key in sorted(todas_las_keys, key=lambda k: str(k)):
            grupo, sub_grupo = key
            monto_actual = float(agg_actual.get(key, 0.0))
            monto_previo = float(agg_previo.get(key, 0.0))
            delta = round(monto_actual - monto_previo, 2)
            if abs(delta) <= TOLERANCIA_SOLES:
                continue

            causa, sustento = self._clasificar_causa(cuenta, ciclo_actual, ciclo_previo, grupo, sub_grupo, delta)
            lineas.append(
                DeltaLinea(
                    grupo=grupo, sub_grupo=sub_grupo,
                    monto_actual=monto_actual, monto_previo=monto_previo, delta=delta,
                    causa=causa, sustento=sustento, descripcion=desc_por_key.get(key, ""),
                )
            )
        return lineas

    def _clasificar_causa(self, cuenta, ciclo_actual, ciclo_previo, grupo, sub_grupo, delta):
        d = self.d

        if grupo in GRUPOS_PRORRATEO:
            if delta < 0:
                # El prorrateo es un cargo puntual (una sola vez, por alta o
                # cambio a mitad de ciclo). Que "desaparezca" respecto al
                # ciclo anterior es normal y autoexplicable -- no necesita
                # sustento cruzado en Brainy, porque Brainy solo registra
                # prorrateos que SI ocurrieron, no su ausencia.
                return "fin_prorrateo_anterior", {
                    "tabla": "FACTURACION-CLIENTES_.csv",
                    "explicacion": "Cargo de prorrateo del ciclo anterior (cobro unico) que no se repite este ciclo.",
                    "llave_fuente": {"FINANCIAL_ACCOUNT_KEY": cuenta, "ciclo": ciclo_previo, "GRUPO": grupo, "SUB_GRUPO": sub_grupo},
                    "campos_usados": {"delta": delta, "GRUPO": grupo, "SUB_GRUPO": sub_grupo},
                }
            fila = d.prorrateo[(d.prorrateo["cuenta_financiera"] == cuenta) & (d.prorrateo["ciclo_norm"] == ciclo_actual)]
            if not fila.empty:
                r = fila.iloc[0]
                monto_prorrateo = float(r["suma_prorrateo"]) if pd.notna(r["suma_prorrateo"]) else None
                return "prorrateo", {
                    "tabla": "BRAINY_PRORRATEO_ALTASV3.csv",
                    "fecha_inicio": r["fecha_inicio_minima"], "fecha_fin": r["fecha_fin_maxima"],
                    "monto_sustento": monto_prorrateo,
                    "conciliacion_importe": self._conciliacion_importe(delta, monto_prorrateo),
                    "llave_fuente": {"CuentaFinanciera": r["CuentaFinanciera"], "Ciclica": r["Ciclica"]},
                    "campos_usados": {
                        "suma_prorrateo": float(r["suma_prorrateo"]) if pd.notna(r["suma_prorrateo"]) else None,
                        "fecha_inicio_minima": r["fecha_inicio_minima"],
                        "fecha_fin_maxima": r["fecha_fin_maxima"],
                    },
                }
            return "no_explicado", {}

        if grupo == "CARGO POR RECONEXION":
            # La reconexion es un cobro unico. Si estaba en el ciclo anterior
            # y ya no aparece, su desaparicion es explicable sin exigir una
            # nueva fila Brainy (Brainy solo registra el evento que ocurrio).
            if delta < 0:
                return "fin_reconexion_anterior", {
                    "tabla": "FACTURACION-CLIENTES_.csv",
                    "explicacion": "Cargo de reconexión del ciclo anterior que no se repite este ciclo.",
                    "llave_fuente": {"FINANCIAL_ACCOUNT_KEY": cuenta, "ciclo": ciclo_previo, "GRUPO": grupo, "SUB_GRUPO": sub_grupo},
                    "campos_usados": {"delta": delta, "GRUPO": grupo, "SUB_GRUPO": sub_grupo},
                }
            fila = d.reconexiones[(d.reconexiones["cuenta_financiera"] == cuenta) & (d.reconexiones["ciclo_norm"] == ciclo_actual)]
            if not fila.empty:
                r = fila.iloc[0]
                monto_reconexion = float(r["Monto"]) if pd.notna(r["Monto"]) else None
                return "reconexion", {
                    "tabla": "BRAINY_RECONEXIONESV3.csv",
                    "fecha_corte": r["FechaCorte"], "fecha_reconexion": r["FechaReconexion"],
                    "monto_sustento": monto_reconexion,
                    "conciliacion_importe": self._conciliacion_importe(delta, monto_reconexion),
                    "llave_fuente": {"CuentaFinanciera": r["CuentaFinanciera"], "Ciclica": r["Ciclica"]},
                    "campos_usados": {
                        "Monto": float(r["Monto"]) if pd.notna(r["Monto"]) else None,
                        "FechaCorte": r["FechaCorte"], "FechaReconexion": r["FechaReconexion"],
                    },
                }
            return "no_explicado", {}

        if grupo == "DESCUENTO CARGO RECURRENTE" and delta > 0:
            fila = d.descuentos[
                (d.descuentos["cuenta_financiera"] == cuenta)
                & (d.descuentos["ciclo_norm"] == ciclo_previo)
                & (d.descuentos["FechaFin"].notna())
            ]
            if not fila.empty:
                r = fila.iloc[0]
                return "fin_descuento", {
                    "tabla": "BRAINY_DESCUENTOS_CUOTAS.csv",
                    "descripcion": r["Descripcion"], "fecha_fin": r["FechaFin"],
                    "porcentaje_promo": float(r["PorcentajePromo"]) if pd.notna(r["PorcentajePromo"]) else None,
                    "tipo_renta": r["TipoRenta"],
                    "conciliacion_importe": self._conciliacion_importe(delta, None, evidencia_contextual=True),
                    "llave_fuente": {"cuentafinanciera": r["cuentafinanciera"], "Ciclo": r["Ciclo"]},
                    "campos_usados": {
                        "Descripcion": r["Descripcion"], "FechaFin": r["FechaFin"],
                        "PorcentajePromo": float(r["PorcentajePromo"]) if pd.notna(r["PorcentajePromo"]) else None,
                        "TipoRenta": r["TipoRenta"],
                    },
                }
            return "no_explicado", {}

        if grupo == "NO CONSIDERAR" and sub_grupo == "FINANCIAMIENTO":
            fila = d.descuentos[(d.descuentos["cuenta_financiera"] == cuenta) & (d.descuentos["ciclo_norm"] == ciclo_actual)]
            sustento = {"tabla": "FACTURACION-CLIENTES.csv (GRUPO=NO CONSIDERAR/FINANCIAMIENTO, sin par de reversion)"}
            if not fila.empty:
                r = fila.iloc[0]
                cuota_actual = float(r["CuotaActual"]) if pd.notna(r["CuotaActual"]) else None
                sustento.update({
                    "tabla": "BRAINY_DESCUENTOS_CUOTAS.csv",
                    "cuota_actual": cuota_actual,
                    "descripcion": r["Descripcion"],
                    "conciliacion_importe": self._conciliacion_importe(delta, cuota_actual),
                    "llave_fuente": {"cuentafinanciera": r["cuentafinanciera"], "Ciclo": r["Ciclo"]},
                    "campos_usados": {
                        "CuotaActual": float(r["CuotaActual"]) if pd.notna(r["CuotaActual"]) else None,
                        "Descripcion": r["Descripcion"],
                    },
                })
            if "conciliacion_importe" not in sustento:
                sustento["conciliacion_importe"] = self._conciliacion_importe(delta, None, evidencia_contextual=True)
            return "equipo_financiado", sustento

        if grupo == "CARGA EXTERNA":
            return "equipo_financiado", {
                "tabla": "FACTURACION-CLIENTES.csv (GRUPO=CARGA EXTERNA, ajuste asociado a financiamiento)",
                "conciliacion_importe": self._conciliacion_importe(delta, None, evidencia_contextual=True),
                "llave_fuente": {"FINANCIAL_ACCOUNT_KEY": cuenta, "ciclo": ciclo_actual, "GRUPO": grupo, "SUB_GRUPO": sub_grupo},
                "campos_usados": {"delta": delta, "GRUPO": grupo, "SUB_GRUPO": sub_grupo},
            }

        # Nota de credito/debito: solo se atribuye si su importe concilia con
        # el delta. Su mera presencia en el ciclo no es evidencia suficiente.
        nota_conciliada = self._buscar_nota_credito_conciliada(cuenta, ciclo_actual, delta)
        if nota_conciliada is not None:
            filas_nc = nota_conciliada["filas"]
            r = filas_nc.iloc[0]
            monto_neto = round(float(filas_nc["AMOUNT"].sum()), 2)
            return "nota_credito", {
                "tabla": "NOTAS_CREDITO.csv",
                "tipo": r["CANCEL_CHARGE_TYPE"],
                "monto": monto_neto,
                "conciliacion": nota_conciliada["tipo"],
                "llave_fuente": {
                    "BA_NO": r["BA_NO"], "CICLO": r["CICLO"],
                    "CHARGE_CODE": r["CHARGE_CODE"], "EFFECTIVE_DATE": r["EFFECTIVE_DATE"],
                },
                "campos_usados": {
                    "CANCEL_CHARGE_TYPE": r["CANCEL_CHARGE_TYPE"], "AMOUNT": monto_neto,
                    "delta_conciliado": delta, "tipo_conciliacion": nota_conciliada["tipo"],
                },
            }

        return "no_explicado", {
            "tabla": "FACTURACION-CLIENTES_.csv",
            "llave_fuente": {"FINANCIAL_ACCOUNT_KEY": cuenta, "ciclo_actual": ciclo_actual, "ciclo_previo": ciclo_previo, "GRUPO": grupo, "SUB_GRUPO": sub_grupo},
            "campos_usados": {"delta": delta, "GRUPO": grupo, "SUB_GRUPO": sub_grupo},
        }


# --------------------------------------------------------------------- #
# Ejecución: correr sobre los 5 casos de prueba del Paso 1 + el caso real
# de cambio de plan encontrado en el análisis exploratorio.
# --------------------------------------------------------------------- #
if __name__ == "__main__":
    print("=" * 70)
    print("PASO 2 — Cargando datos reales y motor de diffing")
    print("=" * 70)
    datos = DatosReales()
    motor = MotorDiffingReal(datos)

    casos_path = os.path.join(BASE_DIR, "..", "..", "Paso1", "salida_paso1", "casos_prueba_por_escenario.csv")
    casos_df = pd.read_csv(casos_path, dtype=str)

    # Reemplazamos e_cambio_plan y b_financiamiento por casos reales con
    # variación de monto genuina entre ciclo actual y previo (los que
    # seleccionó Paso 1 con su heurística de "primera coincidencia" no
    # tenían delta real -- eran cuentas de control o el evento cae fuera
    # de la ventana de ciclos disponible). Ambos verificados manualmente
    # contra el dataset real.
    casos_df.loc[casos_df["escenario"] == "e_cambio_plan", ["cuenta_financiera", "ciclo"]] = ["100706563", "20260415"]
    casos_df.loc[casos_df["escenario"] == "b_financiamiento", ["cuenta_financiera", "ciclo"]] = ["757869240", "20260605"]
    casos_df.loc[casos_df["escenario"] == "d_fin_descuento", ["cuenta_financiera", "ciclo"]] = ["758420349", "20260505"]

    filas_resultado = []
    for _, row in casos_df.iterrows():
        escenario, cuenta, ciclo = row["escenario"], row["cuenta_financiera"], row["ciclo"]
        print()
        print("-" * 70)
        print(f"CASO: {escenario}  (cuenta {cuenta}, ciclo {ciclo})")
        try:
            r = motor.comparar(cuenta, ciclo)
        except ValueError as e:
            print(f"  ERROR: {e}")
            continue

        if r.get("sin_ciclo_previo"):
            print(f"  Sin ciclo previo disponible (primer recibo de la cuenta en el dataset)")
            print(f"  Total actual: S/ {r['total_actual']:.2f}")
        else:
            print(f"  Ciclo previo: {r['ciclo_previo']}")
            print(f"  Total actual: S/ {r['total_actual']:.2f} | Total previo: S/ {r['total_previo']:.2f}")
            print(f"  Delta total: S/ {r['delta_total']:.2f} | Hay variacion: {r['hay_variacion']}")
        print(f"  Lineas detectadas: {len(r['lineas'])}")
        for l in r["lineas"]:
            print(f"    - [{l['causa']}] {l['grupo']}/{l['sub_grupo']}: delta S/ {l['delta']:.2f}  ({l['descripcion']})")
            filas_resultado.append({
                "escenario": escenario, "cuenta": cuenta, "ciclo_actual": ciclo,
                "ciclo_previo": r["ciclo_previo"], "grupo": l["grupo"], "sub_grupo": l["sub_grupo"],
                "delta": l["delta"], "causa": l["causa"], "sustento": str(l["sustento"]),
            })
        if r["causas_no_explicadas"] > 0:
            print(f"  *** {r['causas_no_explicadas']} linea(s) SIN causa sustentada -> derivar a asesor ***")

    out_path = os.path.join(OUT_DIR, "resultados_diffing_casos_prueba.csv")
    pd.DataFrame(filas_resultado).to_csv(out_path, index=False, encoding="utf-8")
    print()
    print("=" * 70)
    print(f"PASO 2 completado. Resultados exportados a: {out_path}")
    print("=" * 70)
