# PASO 2: Motor de diffing (determinístico, SIN IA)

## Cómo correrlo

```bash
cd scripts
python3 paso2_motor_diffing.py
```

Corre el motor sobre los 5 casos de prueba (uno por escenario crítico) y
exporta el resultado a `salida_paso2/resultados_diffing_casos_prueba.csv`.

## Qué hace, en corto

Dada una `cuenta_financiera` (+ opcionalmente un `ciclo`), compara el
ciclo actual contra el **inmediato anterior disponible en el dataset** y
etiqueta cada delta S/ con una causa verificable, cruzando las 4 tablas
Brainy + Notas de Crédito + Órdenes. Si una variación no se puede
sustentar contra ninguna tabla, se marca `no_explicado` explícitamente
-- nunca se inventa una causa.

## 3 hallazgos importantes del análisis de datos reales (para el equipo)

### 1. Se agrupa por (GRUPO, SUB_GRUPO), no por CHARGE_CODE_ID exacto
`GRUPO="NO CONSIDERAR"` trae pares de reversión contable (un bono
`+13.74` con un `CHARGE_CODE_ID` y su reverso `-13.74` con OTRO
`CHARGE_CODE_ID` distinto). Si agrupamos por código exacto, estos pares
NO se cancelan y contaminan el diffing con "ruido" que no es una
variación real. Agrupando por `(GRUPO, SUB_GRUPO)` se cancelan solos al
sumar. Verificado sobre el dataset completo: de 65,104 combinaciones
`(cuenta, ciclo, GRUPO=NO CONSIDERAR)`, el 97% neteaba a ~0 y el 3%
restante correspondía a cargos reales de financiamiento de equipo (que
SÍ hay que explicar al cliente, y viven justamente dentro de este mismo
GRUPO, `SUB_GRUPO="FINANCIAMIENTO"`).

### 2. El escenario de prorrateo SIEMPRE cae en el primer ciclo de la cuenta
Verificado sobre 200 cuentas con prorrateo: el 100% tiene su registro de
`BRAINY_PRORRATEO_ALTASV3` exactamente en el primer ciclo disponible de
esa cuenta en el dataset. Tiene sentido: el prorrateo ocurre en el alta
del servicio. Por eso el motor maneja explícitamente el caso "sin ciclo
previo disponible" -- comparar contra cero generaría deltas falsos para
cargos base (CARGO FIJO, DESCUENTO) que en realidad nunca cambiaron,
solo que es el primer recibo de la cuenta en la ventana de datos.

### 3. Un prorrateo/vencido que "desaparece" es autoexplicable
El prorrateo es un cargo puntual (una sola vez). Que no se repita en el
ciclo siguiente es normal y no necesita sustento cruzado en Brainy
(Brainy solo registra prorrateos que SÍ ocurrieron, no su ausencia). Se
etiqueta como `fin_prorrateo_anterior` en vez de `no_explicado`.

## Los 5 casos de prueba (corregidos con cuentas reales)

Los casos que seleccionó el Paso 1 (`casos_prueba_por_escenario.csv`, con
su heurística de "primera cuenta que coincide") no todos mostraban una
variación de monto real al hacer el diffing cycle-a-cycle -- algunos eran
la primera cuenta que aparecía en un `set` de existencia, sin garantizar
que el escenario se reflejara como delta real. Se reemplazaron 3 de los
5 por cuentas verificadas manualmente contra el dataset real (ver
`salida_paso2/casos_prueba_corregidos.csv` para el detalle y la nota de
cada caso):

| Escenario | Cuenta | Ciclo | Delta | Causa |
|---|---|---|---|---|
| a) Prorrateo | 716389015 | 20260417 | S/ 7.73 | `prorrateo` |
| b) Financiamiento | 757869240 | 20260605 | S/ 8.75 (neto) | `equipo_financiado` + 1 residual sin explicar |
| c) Reconexión | 100032914 | 20260415 | S/ 4.58 (línea de reconexión) | `reconexion` |
| d) Fin de descuento | 758420349 | 20260505 | S/ 66.41 | `fin_descuento` |
| e) Cambio de plan | 100706563 | 20260415 | -S/ 24.51 (neto) | `cambio_plan` + `fin_descuento` |

El caso `b_financiamiento` deja intencionalmente 1 línea sin explicar
(S/ 1.31, un residual de `CARGO FIJO PROPORCIONAL VENCIDO` sin match en
Brainy) -- es un buen ejemplo real para demostrar en vivo que el sistema
deriva a asesor en vez de inventar cuando no encuentra sustento.

## Limitación conocida: Órdenes.csv no tiene llave exacta (cuenta, ciclo)

`Ordenes.csv` identifica al cliente por `CUSTOMER_KEY` y trae solo una
fecha de completado, sin período de ciclo. Las columnas
`PERIOD_START_DATE`/`PERIOD_END_DATE` de `FACTURACION-CLIENTES.csv` no
sirven para este join (vienen vacías/truncadas en el dataset: `"00:00.0"`).
Por eso el sustento de `cambio_plan` usa la **orden más cercana en fecha**
al ciclo (dentro de una ventana de 60 días) como aproximación, y lo
declara así explícitamente en el campo `sustento.tabla` de la respuesta
-- nunca se presenta como una coincidencia exacta cuando no lo es.

## Siguiente paso

Con el motor de diffing corriendo contra datos reales, el Paso 3 (LLM
como capa de redacción) puede conectarse tomando el diccionario que
devuelve `MotorDiffingReal.comparar()` como el único insumo que ve el
LLM -- igual que en el prototipo con datos sintéticos ya armado en
`explica-backend/`. El Paso 4 (motor de reglas + hand-off) se construye
en Dify siguiendo la sección 11 de la propuesta, usando este mismo motor
como el nodo Código de la tool `consultar_recibo`.
