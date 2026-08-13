# PASO 1: Preparación y unificación de datos

## Cómo correrlo

```bash
cd scripts
python3 paso1_unificar_datos.py
```

Genera de nuevo los archivos de `salida_paso1/` a partir de `datos_originales/`.
Tarda unos segundos porque procesa las 297,000 filas de facturación completas.

## Qué hace el script, en corto

1. **Carga los 8 CSV con `pd.read_csv`** detectando automáticamente el
   delimitador de cada uno (el dataset trae una mezcla real de `;` y `,`
   según el archivo — no es un error, hay que manejarlo).
2. **Normaliza las llaves de cuenta** creando una columna `cuenta_financiera`
   uniforme en cada tabla, y una columna `customer_key` para el caso especial
   de Órdenes (ver nota de llaves abajo).
3. **Agrupa `FACTURACION-CLIENTES.csv`** con `groupby(["cuenta_financiera",
   "ciclo"])` — así queda listo para comparar un ciclo contra el anterior en
   el Paso 2.
4. **Cruza (con sets, equivalente a un merge de existencia)** cada
   combinación `(cuenta, ciclo)` contra las 4 tablas Brainy + Notas de
   Crédito + Órdenes y etiqueta cada una con sus causas detectadas
   (prorrateo, reconexión, descuento/financiamiento, nota de crédito/débito,
   cambio de plan).
5. **Exporta la tabla maestra de eventos** — el insumo directo del motor de
   diffing (Paso 2) y **5 casos de prueba reales**, uno por cada escenario
   crítico que pide la ficha del desafío.

## Nota importante de llaves (para que el equipo no la redescubra)

- La mayoría de tablas (Brainy, Notas de Crédito) usan una columna de
  **cuenta financiera** que sí es comparable con `FINANCIAL_ACCOUNT_KEY` de
  `FACTURACION-CLIENTES.csv`.
- **`Ordenes.csv` es distinto**: identifica al cliente por `CUSTOMER_KEY`,
  no por cuenta financiera. Para cruzarlo hay que pasar primero por el
  `CUSTOMER_KEY` que trae `FACTURACION-CLIENTES.csv` para esa misma cuenta.
  El script ya resuelve esto (ver `cuenta_a_customer` en el código).

## Resultado de la última corrida (dataset completo)
======================================================================

- 98,389 combinaciones únicas de `(cuenta, ciclo)` en la tabla maestra.
- 1,642 cuentas con prorrateo · 5,199 con reconexión · 2,136 con
  descuentos/financiamiento · 1,514 con notas de crédito/débito · 14,076
  clientes con órdenes registradas.
- Los 5 casos de prueba (uno por escenario) quedaron identificados con
  cuenta y ciclo reales — listos para usarse en Dify tal como describe la
  sección 11 de la propuesta.
======================================================================
PASO 1: Seleccionando 5 casos de prueba reales (uno por escenario)
======================================================================
  · a_prorrateo: cuenta 716389015, ciclo 20260417
  · b_financiamiento: cuenta 100222091, ciclo 20260131
  · c_reconexion: cuenta 100032914, ciclo 20260415
  · d_fin_descuento: cuenta 100222091, ciclo 20260131
  · e_cambio_plan: cuenta 100001124, ciclo 20260215
======================================================================

## Siguiente paso

Con `tabla_maestra_eventos.csv` y `casos_prueba_por_escenario.csv` ya
generados, se puede pasar directo al **Paso 2** (motor de diffing):
comparar el ciclo actual contra el anterior para cada cuenta y calcular el delta S/ por `GRUPO`/`SUB_GRUPO`, usando las causas que este Paso 1 ya dejó identificadas.
