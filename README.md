# Casandra

## Motivación

*Algo irrefutable es que en los partidos de fútbol siempre hay un resultado más probable*.

La premisa principal de Casandra será **aprovechar el poder del machine learning para predecir resultados y total de goles en partidos de fútbol**.

**Casandra** es el nombre que recibirá el meta-modelo predictor.

No espero un sistema perfecto, ya que, evidentemente, siempre hay un factor de aleatoriedad en los partidos de fútbol. Sin embargo, la gran mayoría de los partidos tienden a ajustarse a su resultado más probable.

**Casandra** será entrenada usando todos los partidos de todas las jornadas de las principales competiciones de las 5 principales ligas europeas de los últimos 10 años, dando un total de aproximadamente 25.000 partidos.

## Requerimientos

El objetivo es construir una aplicación de terminal que, al ejecutarse, muestre una lista con las 5 principales ligas europeas, copas ligueras y Champions, y al seleccionarse la competición deseada, *el programa mostrara una lista con todos los partidos de la próxima jornada junto con su resultado más probable y total de goles más probable*.

La premisa de este proyecto será crear dos **meta-modelos** de machine learning capaces de realizar predicciones de partidos de fútbol, uno para resultado más probable (Clasificación) y otro para la cantidad de goles más probables (Regresión). Ambos constituirán a **Casandra**.

Ambos meta-modelos seguirán el concepto de *stacking* en el contexto de *ensemble learning* utilizando la mayor cantidad de algoritmos de machine learning y deep learning, esto para lograr los mejores resultados posibles.


# Fases del proyecto

## 1- Conseguir datos


* Definir lista de features.

* Crear una función que reciba competición, temporada y jornada y retorne la lista de partidos. (**MatchLister**)

* Crear una función que, dado un partido, retorne los últimos 10 partidos de cada uno de los equipos, enfrentamiento y fecha.

* Crear función que, dado un partido y una fecha, retorne los valores para las features seleccionadas y el resultado y goles totales en caso de estar definidos. (**MatchScrapper**)

* Unir ambas funciones anteriores para crear un dataframe y exportar.

## 2 - Entrenamiento de Casandra

Una vez obtenidos los datos, se entrenará Casandra.

## 3 - Juntar módulos para producción

En producción se unirán los módulos **MatchLister**, **MatchScrapper** y **Casandra** para cumplir con los requisitos.



## 4 - Pruebas con casos reales


# Selección de features

* Competición (categórica)

* local (categórica)

* visitante (categórica)

* PGML: Promedio de goles marcados del local en -5 partidos (Float)

* PGEL: Promedio de goles encajados del local en -5 partidos (Float)

* PGMV: Promedio de goles marcados del visitante en -5 partidos (Float)

* PGEV: Promedio de goles encajados del vístante en -5 partidos (Float)

* PPV: promedio de puntos obtenidos en los últimos partidos del visitante.

* PPL: promedio de puntos obtenidos en los últimos partidos del local.


* JI: suma de valores de mercado de sus jugadores indispuestos (lesiones, sanciones, etc.)

* PPLCL: promedio de puntos obtenidos por el local como local -10 partidos

* PPVCV: promedio de puntos obtenidos por el visitante como  visitante -10 partidos

* PPCL: promedio de puntos de los últimos partidos del local en la competición (-5 partidos)

* PPCV: promedio de puntos de los últimos partidos de visitante en la competición

