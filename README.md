# Casandra

## Motivación

*Algo irrefutable es que en los partidos de fútbol siempre hay un resultado más probable*.

La premisa principal de Casandra será **aprovechar el poder del machine learning para predecir resultados y total de goles en partidos de fútbol**.

No espero un sistema perfecto, ya que, evidentemente, siempre hay un factor de aleatoriedad en los partidos de fútbol. Sin embargo, la gran mayoría de los partidos tienden a ajustarse a su resultado más probable.

**Casandra** será entrenada utilizando todos los partidos de todas las jornadas de las 5 principales ligas europeas de los últimos 30 años. Por lo tanto, los primeros datos se corresponden a la jornada 5 de la temporada 94/95.

## Requerimientos

El objetivo es construir una aplicación de terminal que, al ejecutarse, muestre una lista con las 5 principales ligas europeas, y al seleccionarse la competición deseada, *el programa mostrará una lista con todos los partidos de la próxima jornada junto con su resultado más probable y total de goles más probable* ordenando los resultados de mayor a menor seguridad.

Se utilizará (en principio) el algoritmo de machine learning que recibe el nombre de Support Vector Machine (SVM) dadas las características del dataset. 

# Fases del proyecto

## 1- Conseguir datos

* Definir lista de features.

* Crear una función (get_match_features) que reciba el acrónimo de un partido (bar-get) y su fecha, y retorna todas las features de dicho partido. Esta función debe ser utilizada para encontrar datos de partidos terminados y no terminados, es decir, también retorna el resultado del encuentro en caso de estar disponible.


* Crear funcion (get_previus_matches) que reciba un equipo y una fecha y retorne los N partidos previos a esa fecha con el formato : 

[
    ['bar-sev', 'dd/mm/aa'],
    ['vill-bar', 'dd/mm/aa'],
    ...
]

* Crear función (get_match_result) que dado un partido y su fecha retorne su resultado.

* Crear función (get_elo) que dado un equipo y una fecha retorne su ELO en esa fecha.

* Crear función (get_team_value) que dado un equipo y una fecha retorna el valor de mercado total de la plantilla en ese momento. Se considerará tener en cuenta la inflación europea de la fecha. Esta funcion debera ser capaz de:

    1. Retornar el valor de mercado para cualquier equipo que actualmente este en 1ra/2da/3ra division en las 5 principales ligas europeas.
    2. Retornar el valor de mercado para cualquier fecha entre 1994 y 2025
    3. Retornar el valor de mercado ajustado a la inflacion del momento.

    Nota: recordar que cuando se haga el proceso de minado de data, se deben cachear los team_values por temporada.

* Crear clase `Match`, que contendrá toda la información asociada a un partido.

* Crear clase `Result` que contendrá información acerca de los resultados previos a un partido.

* Crear función (get_matches_list) que reciba una liga, temporada y jornada y retorna la lista de partidos (formato: ([código],[fecha]) ).


## 2 - Entrenamiento de Casandra

Una vez obtenidos los datos, se entrenará Casandra.

## 3 - Juntar módulos para producción

...

## 4 - Pruebas con casos reales


# Ideas generales de features

## General

* Competición

* local

* visitante

* jornada

## Rendimiento general en la competición

* PA : posición actual en la competición. En caso de ser un partido de eliminatorias, a ambos se les asigna un 0.

* TGACL : total de goles anotados por el equipo local en la competición.

* TGECL : total de goles encajados por el local en la competición.

* TGACV : total de goles anotados por el equipo visitante en la competición.

* TGECV : total de goles encajados por el equipo visitante en la competición.

* PPLCL : promedio de puntos del local como local.

* PPVCV : promedio de puntos del visitante como visitante.

* ranking fifa del local en el momento del partido

* ranking fifa del visitante en el momento del partido

* ranking del estadio


## Rendimiento Reciente en goles

* PGML: Promedio de goles marcados del local en -5 partidos (todas las competiciones)

* PGEL: Promedio de goles encajados del local en -5 partidos (todas las competiciones)

* PGMV: Promedio de goles marcados del visitante en -5 partidos (todas las competiciones)

* PGEV: Promedio de goles encajados del visitante en -5 partidos (todas las competiciones)

* PGMLCL: Promedio de goles marcados del local como local. (todas las competiciones)

* PGELCL: Promedio de goles encajados del local como local. (todas las competiciones)

* PGMVCV: Promedio de goles marcados del visitante como visitante. (todas las competiciones)

* PGEVCV: Promedio de goles encajados del visitante como visitante. (todas las competiciones)

## Rendimiento reciente en puntos

* PPV: promedio de puntos obtenidos en los últimos partidos del visitante. (todas las competiciones)

* PPL: promedio de puntos obtenidos en los últimos partidos del local. (todas las competiciones)

* PPLCL: promedio de puntos obtenidos por el local como local -10 partidos (todas las competiciones)

* PPVCV: promedio de puntos obtenidos por el visitante como  visitante -10 partidos (todas las competiciones)

* PPCL: promedio de puntos de los últimos partidos del local en la competición (-5 partidos)

* PPCV: promedio de puntos de los últimos partidos de visitante en la competición.

* PTPL: promedio de tiros a puerta del local en los últimos partidos.

* PTPV: promedio de tiros a puerta del visitante en los últimos partidos.

## Enfrentamiento directo

* ED_PPGLCL: porcentaje de partidos ganados como local del local en enfrentamiento directo.

* ED_PPGVCV: porcentaje de partidos ganados como visitante del visitante en enfrentamiento directo.

* ED_PPGL : porcentaje de partidos ganados del local en enfrentamientos directos.

* ED_PPGV : porcentaje de partidos ganados del visitante en enfrentamientos directos.

* ED_PE: porcentaje de empates en enfrentamientos directos.

* ED_PGL: promedio de goles del local en enfrentamientos directos.

* ED_PGV: promedio de goles del visitante en enfrentamientos directos.

* ED_PGT: promedio de goles totales en enfrentamientos directos.

## Rachas

* PLSP: partidos del local sin perder.

* PLSPCL: partidos del local sin perder como local.

* PVSP: partidos del visitante sin perder.

* PVSPCV: partidos del visitante sin perder como visitante.

## Valores de mercado

* JI: suma de valores de mercado de sus jugadores indispuestos (lesiones, sanciones, etc.)

* VMTL : valor de mercado total de la plantilla del equipo local.

* VMTV : valor de mercado total de la plantilla del equipo visitante.

## Dias de descanso

* DD_L: días de descanso desde el último partido del local.

* DD_V: días de descanso desde el último partido del visitante.

## Cantidad de partidos

* CP_L: cantidad de partidos del local en los últimos 20 días.

* CP_V: cantidad de partidos del visitante en los últimos 20 días.

## Importancia del partido

* I_P: un número del 1 al 3 que represente la importancia del partido, si es una jornada de liga normal o es de las últimas jornadas de liga o las últimas fases de un torneo de eliminatorias.



# Lista de features primaria

En principio, utilizaré las features más destacadas para evitar ruido y colinealidad. En un futuro pensaré si poner más.

## Identidad / contexto

Local (categórica) → codificada.

Visitante (categórica) → igual que arriba.

Competición (categoría)


## Fuerza global

Ranking Elo/FIFA local

Ranking Elo/FIFA visitante

## Forma reciente (últimos 5 partidos)

PGML: promedio goles marcados local

PGEL: promedio goles encajados local

PGMV: promedio goles marcados visitante

PGEV: promedio goles encajados visitante


## Resultados recientes

PPL: puntos promedio últimos 5 del local

PPV: puntos promedio últimos 5 del visitante


## Contexto físico / externo

DD_L: días descanso local

DD_V: días descanso visitante


## Valor de mercado

VMTL: valor mercado total local

VMTV: valor mercado total visitante


Total de features inicial : 15


# Minado de data
