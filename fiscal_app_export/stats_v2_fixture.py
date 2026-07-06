"""
/stats-v2 — Contrato de datos del encuentro y fixture derivado del escenario 02.

Fase 2 del Hito 1 (10 §16): la página se construye contra fixtures, sin backend
de razonamiento. Este módulo es la única fuente de datos de /stats-v2 y define
el contrato que el razonamiento real deberá cumplir cuando exista.

CONTRATO — encuentro
  origen                'sistema' | 'responsable'          (D4, I11)
  cabecera.convocatoria prosa en voz del sistema           (I8, I11)
  cabecera.continuidad  prosa: qué pasó desde el último encuentro (I11)
  declaracion_conjunta  párrafo que nombra el conjunto antes que las partes (I12)
  ancla.estado          'impostergable' | 'satisfecha' | 'actualizada' (I14)
  ancla.texto           la implicación de la línea impostergable, una frase (I14)
  ancla.linea_id        id de la línea a la que el Ancla conduce (I14)
  pausa.estado          'latente' | 'disponible'           (I29)
  pausa.texto           declaración de la región de Pausa  (I29)
  periferia             lista de señales (vacía si no existe: la región no se
                        renderiza — I4 "solo si existe")   (I26)
  llegadas              lista de cruces en sesión (vacía: fase 2 no los computa;
                        legítimo por 10 §16 "puede no ocurrir todavía") (I27)
  lineas                lista ordenada POR URGENCIA DEL SISTEMA y nada más (I13)

CONTRATO — línea (cada elemento de `lineas`)
  id                    identificador estable
  implicacion           texto primario: frase de acción posible, nunca
                        título-etiqueta ni métrica                    (I15.1)
  solidez.lectura       'fragil'|'en-construccion'|'consistente'|'solida' (I9/E1)
  solidez.implicacion   ídem — SOLO estas cuatro palabras: números y
                        porcentajes prohibidos en la interfaz de convicción (I9)
  novedad               {etiqueta: 'nuevo'|'respuesta a tu cuestionamiento',
                         origen: 'espontaneo'|'respuesta'} | None      (I7, I15.3)
  estado_como_acto      el estado dicho como acto, jamás nombre técnico (I15.4)
  pertenencia           marca de pertenencia al conjunto              (I15.5, I12)
  estado                estado de interacción de 09 §14:
                        'pendiente-de-posicion'|'en-reevaluacion'|'aplazada'|
                        'escalada'|'en-intervencion'|'reportada'|'senalada'|
                        'cerrada' (ambas formas de cierre; producido por
                        Descartar en sesión — sin presencia propia en el
                        SIGUIENTE encuentro, con constancia en este, I21)
  actos                 repertorio del protocolo para ese estado (D12/T6:
                        la experiencia no lo recorta ni lo amplía — si un
                        estado excluye un acto, el dato no lo trae).
                        'descartar' se renderiza en fase 8 (control propio).
  condicion_vigente     opcional: condición declarada de una línea aplazada
                        por convicción insuficiente — única precarga de
                        línea autorizada (I20c, D13.5)
  posicion              {observo, interpreto, implica} — tripartita siempre;
                        la incertidumbre se declara dentro de `interpreto` (I17)
  bandas                {razon, procedencia, coste} — None cuando no aplican (I17)
  historia              lista DESDE EL ORIGEN: la primera entrada es el
                        nacimiento de la línea (I18). Cada entrada:
                        {cuando, entrada, evidencia|None}. La evidencia de
                        detalle (series, cifras) SOLO puede vivir aquí (I2, I18).
                        Formas de evidencia:
                          serie       {tipo:'serie', descripcion, puntos:[...]}
                          comparativa {tipo:'comparativa', descripcion,
                                       series:[{nombre, puntos:[...]}, ...]}

Traducción del escenario (docs/stats-v2/scenarios/02-competing-lines.md): los
valores internos del modelo («Convicción: 68%») NO viajan al contrato — se
traducen a los cuatro niveles categóricos de E1. Las cifras solo aparecen en
prosa de posición y en evidencia de historia, nunca como convicción.
"""

ENCUENTRO_FIXTURE = {
    "origen": "sistema",
    "cabecera": {
        "convocatoria": (
            "Te he convocado: hay dos líneas que necesitan tu posición."
        ),
        "continuidad": (
            "Desde el último encuentro: dos cruces nuevos en los últimos "
            "cuatro días; ningún frente anterior ha cambiado."
        ),
    },
    "declaracion_conjunta": (
        "He evaluado la conversión de la cohorte en período de prueba y el "
        "patrón de retención ligado a la integración temprana. Las dos líneas "
        "necesitan tu posición hoy: una tiene una ventana que se agota; la "
        "otra sostiene una decisión estructural sin fecha."
    ),
    "ancla": {
        "estado": "impostergable",
        "texto": (
            "Hoy no debería quedar sin posición: la ventana de la cohorte en "
            "prueba empieza a expirar en cinco días."
        ),
        "linea_id": "linea-conversion-prueba",
    },
    "pausa": {
        "estado": "latente",
        "texto": "Quedan 2 líneas de hoy sin posición.",
    },
    "periferia": [],
    "llegadas": [],
    "lineas": [
        {
            "id": "linea-conversion-prueba",
            "implicacion": (
                "La cohorte que hoy está en prueba saldrá sin convertir si "
                "nada cambia antes de que expire su ventana: intervenir su "
                "experiencia es posible mientras siga activa."
            ),
            "solidez": {"lectura": "en-construccion", "implicacion": "consistente"},
            "novedad": {"etiqueta": "nuevo", "origen": "espontaneo"},
            "estado_como_acto": "pendiente de tu posición",
            "pertenencia": "evaluada hoy junto a otra línea",
            "estado": "pendiente-de-posicion",
            "actos": ["activar", "cuestionar", "enriquecer", "aplazar", "descartar"],
            "posicion": {
                "observo": (
                    "En los últimos siete días la conversión de prueba a plan "
                    "de pago ha caído un 18% respecto a la media de los "
                    "treinta anteriores. La cohorte en prueba lleva entre "
                    "cinco y doce días activa: su ventana expirará en los "
                    "próximos cinco a doce días."
                ),
                "interpreto": (
                    "La caída del patrón es clara; su causa no lo es. No he "
                    "podido descartar que sea un cambio en el perfil de quien "
                    "está entrando, ni un factor externo que no tengo modo de "
                    "observar."
                ),
                "implica": (
                    "Si la causa está en el producto, intervenir la "
                    "experiencia de esta cohorte antes de que expire su "
                    "ventana puede recuperar parte de la conversión; después "
                    "de la expiración no quedará nada que recuperar."
                ),
            },
            "bandas": {"razon": None, "procedencia": None, "coste": None},
            "historia": [
                {
                    "cuando": "hace 4 días",
                    "entrada": (
                        "Nace la línea: detecto una desviación sostenida en "
                        "la conversión de prueba a pago."
                    ),
                    "evidencia": {
                        "tipo": "serie",
                        "descripcion": "conversión diaria de prueba a pago, últimos 14 días (%)",
                        "puntos": [3.4, 3.1, 3.3, 3.2, 3.0, 2.9, 3.1, 2.6, 2.5, 2.7, 2.4, 2.5, 2.6, 2.4],
                    },
                },
                {
                    "cuando": "hace 2 días",
                    "entrada": (
                        "La caída supera la variación estacional que conozco; "
                        "evalúo causas de producto, de perfil de entrada y "
                        "externas sin poder aislar una."
                    ),
                    "evidencia": None,
                },
                {
                    "cuando": "hoy",
                    "entrada": (
                        "Te presento la línea: la ventana de la cohorte "
                        "activa no admite esperar al ciclo largo."
                    ),
                    "evidencia": None,
                },
            ],
        },
        {
            "id": "linea-integracion-temprana",
            "implicacion": (
                "La primera semana de cada cuenta puede orientarse a conectar "
                "una herramienta externa: el patrón de retención que observo "
                "lo señala como palanca estructural."
            ),
            "solidez": {"lectura": "solida", "implicacion": "consistente"},
            "novedad": {"etiqueta": "nuevo", "origen": "espontaneo"},
            "estado_como_acto": "pendiente de tu posición",
            "pertenencia": "evaluada hoy junto a otra línea",
            "estado": "pendiente-de-posicion",
            "actos": ["activar", "cuestionar", "enriquecer", "aplazar", "descartar"],
            "posicion": {
                "observo": (
                    "Los usuarios que conectan al menos una herramienta "
                    "externa durante su primera semana retienen a noventa "
                    "días 3,1 veces más que quienes no lo hacen. El patrón se "
                    "sostiene en seis meses de cohortes consecutivas."
                ),
                "interpreto": (
                    "La correlación es estable y no depende de una cohorte "
                    "concreta. No he confirmado causalidad: no he podido "
                    "descartar que exista un perfil de usuario que explique "
                    "a la vez la integración y la retención."
                ),
                "implica": (
                    "Si la relación es causal, adelantar la integración a la "
                    "primera semana es la palanca de retención más sólida que "
                    "observo. No tiene ventana de expiración; tiene coste de "
                    "oportunidad por cada cohorte que entra sin ella."
                ),
            },
            "bandas": {"razon": None, "procedencia": None, "coste": None},
            "historia": [
                {
                    "cuando": "hace 6 meses",
                    "entrada": (
                        "Nace la línea: aparece una diferencia de retención "
                        "entre cuentas con y sin integración temprana."
                    ),
                    "evidencia": {
                        "tipo": "comparativa",
                        "descripcion": "retención a 90 días por cohorte mensual, con y sin integración en la primera semana (%)",
                        "series": [
                            {"nombre": "con integración", "puntos": [46, 44, 47, 45, 48, 46]},
                            {"nombre": "sin integración", "puntos": [15, 14, 16, 14, 15, 15]},
                        ],
                    },
                },
                {
                    "cuando": "hoy",
                    "entrada": (
                        "Te presento la línea: seis cohortes consecutivas "
                        "sostienen el patrón y ya no lo explico como ruido."
                    ),
                    "evidencia": None,
                },
            ],
        },
    ],
}
