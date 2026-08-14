# Paso 3: Entrega completa (capa de redacción LLM)

Hackathon AI Telecom Challenge (Movistar × Universidad de Lima)

Construido y verificado sobre los resultados REALES del Paso 1
(98,389 combinaciones cuenta-ciclo) y el Paso 2 (79,918 comparaciones,
5 casos confirmados por fecha real: PRORRATEO, EQUIPO_FINANCIADO,
RECONEXION, FIN_DESCUENTO, CAMBIO_PLAN).

## Qué hay en este ZIP

```
pdf/
  EXPLICA+_Paso3_Entrega_Completa.pdf   El documento completo, listo para
                                          presentar al jurado (8 páginas)

prompt/
  prompt_capa_redaccion.txt             El prompt final, listo para pegar
                                          en las INSTRUCCIONES del agente
                                          en Dify

json_entrada/
  caso_a_prorrateo.json                 Los 5 JSON reales que produjo el
  caso_b_financiamiento.json             Paso 2 — mismos que se usaron
  caso_c_reconexion.json                 como entrada de esta capa
  caso_d_fin_descuento.json
  caso_e_cambio_plan.json

respuestas_generadas/
  caso_a_prorrateo_respuesta.txt        Una por caso: JSON de entrada +
  caso_b_financiamiento_respuesta.txt    respuesta_corta + respuesta_detalle
  caso_c_reconexion_respuesta.txt        generadas por la capa de redacción
  caso_d_fin_descuento_respuesta.txt
  caso_e_cambio_plan_respuesta.txt      (el Caso E incluye nota sobre el
                                          campo motivo:null, manejado con
                                          honestidad, sin inventar)

trazabilidad/
  tabla_trazabilidad.csv                14 datos verificados uno por uno
  resumen_trazabilidad.txt               contra el JSON de entrada — 14/14
                                          coinciden, cero inventados

pruebas_robustez/
  resultados_5_pruebas.txt              Las 5 pruebas (fidelidad numérica,
                                          SIN_CAUSA_IDENTIFICADA, inyección,
                                          "léelo una vez", consistencia
                                          entre canales) — 5/5 PASA, con
                                          el texto exacto de cada entrada
                                          y cada respuesta
```

## Cómo usar esto para el Paso 4 (Dify)

1. Abre `prompt/prompt_capa_redaccion.txt` y pégalo (o intégralo) en las
   INSTRUCCIONES del agente de Dify, dentro de la sección que maneja la
   respuesta de la tool `consultar_recibo`.
2. Usa los archivos de `json_entrada/` como los "casos de prueba"
   sugeridos por el Starter Kit de Dify — reemplazan a los CLI001-CLI003
   genéricos de la clase con evidencia real del dataset de Movistar.
3. Compara la respuesta que da tu agente en Dify contra
   `respuestas_generadas/` — si Dify da algo muy distinto en fidelidad
   numérica, revisa el prompt antes de seguir al Paso 4.

## Cómo usar esto en la presentación / demo ante el jurado

- El PDF (`pdf/`) es el documento principal — tiene todo narrado y
  diagramado, ideal para el documento ejecutivo del Día 1.
- `trazabilidad/tabla_trazabilidad.csv` es la evidencia concreta que
  respalda "0% de alucinaciones" si el jurado pregunta cómo se
  garantiza — se puede abrir en vivo y mostrar fila por fila.
- `pruebas_robustez/resultados_5_pruebas.txt` tiene el texto exacto de
  la prueba de inyección (Prueba 3) — útil para mostrar en vivo que el
  sistema rechaza intentos de manipulación.

## Resumen de resultados

- 5/5 casos con respuesta generada y verificada.
- 14/14 datos de trazabilidad coinciden exactamente con el JSON de
  entrada — cero discrepancias.
- 5/5 pruebas de robustez pasadas.
- 1 caso (E) demuestra manejo honesto de un dato faltante
  (`motivo: null`) sin inventar información.
