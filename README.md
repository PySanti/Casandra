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

## 1- Minado de datos

* Definir lista de features.

* Crear clase `Match`, que contendrá toda la información asociada a un partido (un registro de entrenamiento).

* Crear clase `Result` que contendra informacion solo del resultado de un partido.

* Crear función (get_match_result) que dado un partido y su fecha retorne su resultado usando la clase `Result`.

* Crear función (get_elo) que dado un equipo y una fecha retorne su ELO en esa fecha.

* Crear función (get_team_value) que dado un equipo y una fecha retorna el valor de mercado total de la plantilla en ese momento. Se considerará tener en cuenta la inflación europea de la fecha. Esta funcion debera ser capaz de:


    1. Retornar el valor de mercado para cualquier equipo que actualmente este en 1ra/2da/3ra division en las 5 principales ligas europeas.
    2. Retornar el valor de mercado para cualquier fecha entre 1994 y 2025
    3. Retornar el valor de mercado ajustado a la inflacion del momento.

    **Nota**: destacar que cuando se haga el proceso de minado de data, se deben cachear los team_values por temporada.


* Crear funcion (get_previus_matches) que reciba un equipo y una fecha y retorne los N partidos previos a esa fecha con el formato : 

[
    ['bar-sev', 'dd/mm/aa'],
    ['vill-bar', 'dd/mm/aa'],
    ...
]


* Crear función (get_matches_list) que reciba una liga, temporada y jornada y retorna la lista de partidos (formato: ([código],[fecha]) ).

* Crear una función (get_match_features) que reciba el acrónimo de un partido (bar-get) y su fecha, y retorna todas las features de dicho partido. Esta función debe ser utilizada para encontrar datos de partidos terminados y no terminados, es decir, también retorna el resultado del encuentro en caso de estar disponible.

* Dadas las funcionalidades anteriores, crear script para minado de data.


## 2 - Entrenamiento de Casandra

Una vez obtenidos los datos, se entrenará Casandra.

## 3 - Juntar módulos para producción

...

## 4 - Pruebas con casos reales

# Minado de data
