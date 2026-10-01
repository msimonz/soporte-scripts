#!/usr/bin/env python3
"""
Reemplaza en un archivo .properties el valor de las variables de ambiente o
sensibles por un token con el nombre de la variable:

    spring.profiles.active=develop    ->  spring.profiles.active=#{SPRING_PROFILES_ACTIVE}#
    spring.datasource.erp.url=jdbc:  ->  spring.datasource.erp.url=#{SPRING_DATASOURCE_ERP_URL}#

Usa las mismas reglas de properties_a_txt.py (sección CONFIGURACIÓN de ese
script), así que los tokens coinciden con las claves del .txt que genera.
Las demás líneas (comentarios, timeouts, pools, etc.) quedan igual.

Con --unificado, los nombres de los tokens se toman del .txt que genera
unificar_txt.py: si la variable quedó con el sufijo de este servicio
(SPRING_PROFILES_ACTIVE_BACKEND), se usa ese; si no, el nombre sin sufijo
(SPRING_PROFILES_ACTIVE).
Las variables que no estén en el unificado se dejan con su valor y se avisan.

Uso:
    python3 properties_a_tokens.py <archivo.properties | directorio> [--unificado <unificado.txt>] [--servicio <nombre>]

    Si se da un directorio, se usa su application.properties (o el de
    src/main/resources). El servicio se deduce de la carpeta del proyecto
    (otro-backend/src/main/resources -> otro-backend).

    Modifica el mismo archivo y deja un respaldo <archivo.properties>.bak con
    el contenido anterior.

Si no se pasan argumentos, el script pide la ruta por consola.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from properties_a_txt import (  # noqa: E402
    convertir_clave,
    es_de_ambiente,
    separar_clave_valor,
    unir_continuaciones,
)
from unificar_txt import leer_servicios_de_unificado, leer_txt, sufijo_servicio  # noqa: E402

# Carpetas que se saltan al deducir el servicio a partir de la ruta del .properties.
CARPETAS_NO_SERVICIO = {"resources", "main", "src", "config"}

TOKEN_YA_PUESTO = re.compile(r"^#\{[^}]+\}#$")


def leer_archivo(ruta):
    """Devuelve (texto, encoding). Intenta UTF-8 y, si falla, ISO-8859-1. Conserva los saltos de línea."""
    for encoding in ("utf-8", "iso-8859-1"):
        try:
            with open(ruta, encoding=encoding, newline="") as f:
                return f.read(), encoding
        except UnicodeDecodeError:
            continue


def termina_en_continuacion(linea):
    sin_salto = linea.rstrip("\r\n")
    return (len(sin_salto) - len(sin_salto.rstrip("\\"))) % 2 == 1


def agrupar_lineas(lineas):
    """Agrupa las líneas físicas que forman una sola propiedad (continuaciones con '\\')."""
    grupo = []
    for linea in lineas:
        grupo.append(linea)
        es_comentario = len(grupo) == 1 and linea.lstrip()[:1] in ("#", "!")
        if es_comentario or not termina_en_continuacion(linea):
            yield grupo
            grupo = []
    if grupo:
        yield grupo


def tokenizar(texto, nombre_token=convertir_clave):
    """
    Devuelve (texto_nuevo, reemplazadas, sin_token).
    nombre_token(clave) da el nombre del token, o None si la variable no debe tocarse.
    """
    salida = []
    reemplazadas = []
    sin_token = []

    for grupo in agrupar_lineas(texto.splitlines(keepends=True)):
        primera = grupo[0]
        limpia = primera.strip()
        if not limpia or limpia[0] in "#!":
            salida.extend(grupo)
            continue

        logica = unir_continuaciones([l.rstrip("\r\n") for l in grupo])[0]
        clave, valor = separar_clave_valor(logica)

        if not clave or TOKEN_YA_PUESTO.match(valor.strip()) or not es_de_ambiente(clave, valor):
            salida.extend(grupo)
            continue

        # Se conserva lo que había antes del valor (sangría, clave y separador tal cual).
        prefijo = logica[: len(logica) - len(valor)] if valor else logica
        if not valor and not prefijo.rstrip().endswith(("=", ":")):
            prefijo = prefijo.rstrip() + "="

        nombre = nombre_token(clave)
        if nombre is None:
            sin_token.append(clave)
            salida.extend(grupo)
            continue

        token = f"#{{{nombre}}}#"
        salto = grupo[-1][len(grupo[-1].rstrip("\r\n")):]
        salida.append(f"{prefijo}{token}{salto}")
        reemplazadas.append((clave, token))

    return "".join(salida), reemplazadas, sin_token


def resolver_properties(ruta):
    """Acepta un .properties o un directorio con application.properties (directo o en src/main/resources)."""
    if ruta.is_file():
        return ruta
    for candidato in (ruta / "application.properties", ruta / "src" / "main" / "resources" / "application.properties"):
        if candidato.is_file():
            return candidato
    sys.exit(f"ERROR: no se encontró application.properties en {ruta} ni en {ruta / 'src/main/resources'}")


def deducir_servicio(properties):
    for carpeta in properties.resolve().parents:
        if carpeta.name.lower() not in CARPETAS_NO_SERVICIO:
            return carpeta.name
    return None


def preparar_unificado(ruta_unificado, servicio):
    """Devuelve la función nombre_token para tokenizar() según el unificado y el servicio."""
    if not ruta_unificado.is_file():
        sys.exit(f"ERROR: no existe el unificado {ruta_unificado}")
    servicios = leer_servicios_de_unificado(ruta_unificado)
    if not servicios:
        sys.exit(f"ERROR: {ruta_unificado} no tiene el encabezado '# SERVICIOS:'. Genéralo con unificar_txt.py.")

    sufijo = next((suf for s, suf in servicios.items() if s.lower() == (servicio or "").lower()), None)
    if not sufijo:
        sys.exit(f"ERROR: el servicio '{servicio}' no está en el unificado. Servicios: {', '.join(servicios)}.\n"
                 "Indícalo con --servicio.")

    claves = {c.upper() for c, _ in leer_txt(ruta_unificado)}
    print(f"Servicio '{servicio}' (sufijo _{sufijo}), {len(claves)} variables en el unificado.")

    def nombre_token(clave):
        base = convertir_clave(clave)
        if f"{base}_{sufijo}" in claves:
            return f"{base}_{sufijo}"
        if base in claves:
            return base
        return None

    return nombre_token


def main():
    parser = argparse.ArgumentParser(
        description="Reemplaza los valores de ambiente/sensibles de un .properties por #{CLAVE}#")
    parser.add_argument("entrada", nargs="?", help="Ruta del .properties o del directorio del servicio")
    parser.add_argument("--unificado", "-u", help="Ruta del unificado.txt que genera unificar_txt.py")
    parser.add_argument("--servicio", "-s", help="Nombre del servicio en el unificado (por defecto, se deduce de la ruta)")
    args = parser.parse_args()

    entrada = args.entrada or input("Ruta del .properties o del directorio del servicio: ").strip().strip("'\"")
    entrada = Path(entrada).expanduser()
    if not entrada.exists():
        sys.exit(f"ERROR: no existe {entrada}")
    entrada = resolver_properties(entrada)

    nombre_token = convertir_clave
    if args.unificado:
        servicio = args.servicio or deducir_servicio(entrada)
        nombre_token = preparar_unificado(Path(args.unificado).expanduser(), servicio)

    texto, encoding = leer_archivo(entrada)
    nuevo, reemplazadas, sin_token = tokenizar(texto, nombre_token)

    if sin_token:
        print("AVISO: estas variables no están en el unificado; se dejan con su valor:")
        for clave in sin_token:
            print(f"    {clave} ({convertir_clave(clave)})")

    if not reemplazadas:
        print(f"No hay valores para reemplazar en {entrada} (puede que ya tenga los tokens).")
        return

    respaldo = entrada.with_name(entrada.name + ".bak")
    shutil.copy2(entrada, respaldo)
    print(f"Respaldo del original en {respaldo}")

    with open(entrada, "w", encoding=encoding, newline="") as f:
        f.write(nuevo)

    print(f"{len(reemplazadas)} valores reemplazados en {entrada}")
    con_sufijo = [(c, t) for c, t in reemplazadas if t != f"#{{{convertir_clave(c)}}}#"]
    if con_sufijo:
        print("Con el sufijo del servicio:")
        for clave, token in con_sufijo:
            print(f"    {clave}={token}")


if __name__ == "__main__":
    main()
