# Casandra

## Motivación

*Algo irrefutable es que en los partidos de fútbol siempre hay un resultado más probable*.

La premisa principal de Casandra será **aprovechar el poder del machine learning para predecir resultados y total de goles en partidos de fútbol**.

No espero un sistema perfecto, ya que, evidentemente, siempre hay un factor de aleatoriedad en los partidos de fútbol. Sin embargo, la gran mayoría de los partidos tienden a ajustarse a su resultado más probable.

**Casandra** será entrenada utilizando todos los partidos de todas las jornadas de las 5 principales ligas europeas de los ultimos 30 anios. Por lo tanto, los primeros datos se corresponderan a la jornada 5 de la temporada 94/95.

## Requerimientos

El objetivo es construir una aplicación de terminal que, al ejecutarse, muestre una lista con las 5 principales ligas europeas, y al seleccionarse la competición deseada, *el programa mostrara una lista con todos los partidos de la próxima jornada junto con su resultado más probable y total de goles más probable* ordenando los resultados de mayor a menor seguridad.

Se utilizara (en principio) el algoritmo de machine learning que recibe el nombre de Support Vector Machine (SVM) dadas las caracteristicas del dataset. 

# Fases del proyecto

## 1- Conseguir datos

* Definir lista de features.

* Crear una funcion (get_match_features) que reciba el acronimo de un partido (bar-get) y su fecha, y retorne todas las features de dicho partido. Esta funcion debe ser utilizada para encontrar datos de partidos terminados y no terminados, es decir, tambien retornaria el resultado del encuentro en caso de estar disponible.


* Crear funcion (get_previes_matches) que reciba un equipo y una fecha y retorne los N partidos previos a esa fecha con el formato : 

[
    ['bar-sev', 'dd/mm/aa'],
    ['vill-bar', 'dd/mm/aa'],
    ...
]

* Crear funcion (get_match_result) que dado un partido y su fecha retorne su resultado.

* Crear funcion (get_elo) que dado un equipo y una fecha retorne su ELO en esa fecha.

* Crear funcion (get_team_value) que dado un equipo y una fecha retorne el valor de mercado total de la plantilla en ese momento.

* Crear clase `Match`, que contendra toda la informacion asociada a un partido.

* Crear clase `Result` que contendra informacion acerca de los resultados previos a un partido.

* Crear funcion (get_matches_list) que reciba una liga, temporada y jornada y retorne la lista de partidos (formato: ([codigo],[fecha]) ).


## 2 - Entrenamiento de Casandra

Una vez obtenidos los datos, se entrenará Casandra.

## 3 - Juntar módulos para producción

...

## 4 - Pruebas con casos reales


# Ideas generales de features

## General

* Competición (categórica)

* local (categórica)

* visitante (categórica)

* ranking fifa del local en el momento del partido

* ranking fifa del visitante en el momento del partido

* ranking del estadio


## Rendimiento Reciente

* PGML: Promedio de goles marcados del local en -5 partidos 

* PGEL: Promedio de goles encajados del local en -5 partidos 

* PGMV: Promedio de goles marcados del visitante en -5 partidos 

* PGEV: Promedio de goles encajados del visitante en -5 partidos 

* PPV: promedio de puntos obtenidos en los últimos partidos del visitante.

* PPL: promedio de puntos obtenidos en los últimos partidos del local.

* PPLCL: promedio de puntos obtenidos por el local como local -10 partidos

* PPVCV: promedio de puntos obtenidos por el visitante como  visitante -10 partidos

* PPCL: promedio de puntos de los últimos partidos del local en la competición (-5 partidos)

* PPCV: promedio de puntos de los últimos partidos de visitante en la competición.

* PTPL: promedio de tiros a puerta del local en los últimos partidos.

* PTPV: promedio de tiros a puerta del visitante en los últimos partidos.

## Enfrentamiento directo

* ED_PPGLCL: promedio de partidos ganados como local del local en enfrentamiento directo.

* ED_PPGVCV: promedio de partidos ganados como visitante del visitante en enfrentamiento directo.

* ED_PPGL : promedio de partidos ganados del local en enfrentamientos directos.

* ED_PPGV : promedio de partidos ganados del visitante en enfrentamientos directos.

* ED_PE: promedio de empates en enfrentamientos directos.

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

DD_L: dias de descanso desde el último partido del local.
DD_V: dias de descanso desde el último partido del visitante.

## Cantidad de partidos

CP_L: cantidad de partidos del local en los últimos 20 días.
CP_V: cantidad de partidos del visitante en los últimos 20 días.

## Importancia del partido

I_P: un número del 1 al 3 que represente la importancia del partido, si es una jornada de liga normal o es de las últimas jornadas de liga o las últimas fases de un torneo de eliminatorias.



# Lista de features primaria

En principio, utilizare las features mas destacadas para evitar ruido y colinealidad. En un futuro pensare si poner mas.

## Identidad / contexto

Local (categórica) → codificada.

Visitante (categórica) → igual que arriba.

Competicion (categorica)


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



