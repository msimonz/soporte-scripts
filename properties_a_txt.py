#!/usr/bin/env python3
"""
Extrae de un archivo .properties las variables que cambian entre ambientes o
que son sensibles (URLs, hosts, usuarios, contraseñas, llaves) y las escribe en
un .txt con formato CLAVE=VALOR. Las demás (timeouts, pools, paths relativos,
etc.) se quedan quemadas en el .properties y no van al .txt.

Las claves pasan de minúsculas separadas por puntos a MAYÚSCULAS separadas por
guion bajo (spring.datasource.url -> SPRING_DATASOURCE_URL). Los valores se
copian tal cual están en el .properties.

Qué variables se extraen se ajusta en las listas de CONFIGURACIÓN de abajo.

Uso:
    python3 properties_a_txt.py <archivo.properties> <salida>

    <salida> puede ser la ruta de un .txt o una carpeta. Si es una carpeta, el
    archivo se crea ahí con el mismo nombre del .properties y extensión .txt.

Si no se pasan argumentos, el script los pide por consola.
"""

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIGURACIÓN: qué variables se consideran de ambiente / sensibles
# ---------------------------------------------------------------------------

# Si alguna parte de la clave (entre puntos) contiene una de estas palabras, se extrae.
PALABRAS_CLAVE = (
    "password", "passwd", "pwd", "secret", "token", "access", "credential",
    "contrasena", "contraseña",
    "username", "user", "usuario", "clientid",
    "host", "endpoint", "bootstrap-servers",
)

# Si alguna parte de la clave TERMINA en una de estas palabras, se extrae
# (applicationKey, base-url; pero no keepaliveTime ni security).
TERMINACIONES_CLAVE = ("key", "url", "uri")

# Si el valor tiene esta forma, se extrae aunque la clave no lo diga
# (por ejemplo api.erp.fondos.api=http://...).
PATRONES_VALOR = (
    r"^[a-zA-Z][a-zA-Z0-9+.\-]*://",        # http://, https://, ftp://, ...
    r"^jdbc:",                              # cadenas de conexión a BD
    r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$",      # IP con o sin puerto
    r"^[\w.\-]+:\d+(,[\w.\-]+:\d+)*$",      # host:puerto (o lista, como Kafka)
)

# Valores encriptados (base64, o varios bloques base64 separados por "]", como los de app.ftp.*).
# Se extraen siempre: son secretos o URLs cifradas. Para no confundirlos con texto normal
# (nombres de archivo, plantillas), el valor debe tener al menos LARGO_MINIMO_ENCRIPTADO caracteres,
# solo caracteres de base64 y mezclar mayúsculas, minúsculas y números.
PATRON_ENCRIPTADO = r"^[A-Za-z0-9+/]+={0,2}(\][A-Za-z0-9+/]+={0,2})*$"
LARGO_MINIMO_ENCRIPTADO = 20

# Claves que SIEMPRE van al .txt, aunque las reglas de arriba no las detecten.
INCLUIR_SIEMPRE = {
    "spring.profiles.active",
    "app.ssl.check",
    "app.empresa.obtener.instanceId",
    "app.empresa.sftp.path.root",
    "app.empresa.sftp.path.miProyecto",
    "app.ftp.path.extractos",
    "app.ftp.path.extractos.valores",
}

# Claves que NUNCA van al .txt, aunque las reglas de arriba las detecten.
EXCLUIR_SIEMPRE = {
    "server.port",  # no cambia entre ambientes: se queda quemado en el .properties
}

# ---------------------------------------------------------------------------


def leer_lineas(ruta):
    """Lee el archivo en UTF-8 y, si falla, en ISO-8859-1 (el estándar de Java)."""
    try:
        return ruta.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return ruta.read_text(encoding="iso-8859-1").splitlines()


def unir_continuaciones(lineas):
    """Une las líneas que terminan en '\\' (valor partido en varias líneas)."""
    logicas = []
    actual = None
    for linea in lineas:
        if actual is None:
            actual = linea
        else:
            actual += linea.lstrip()

        barras_finales = len(actual) - len(actual.rstrip("\\"))
        if barras_finales % 2 == 1:
            actual = actual[:-1]
            continue

        logicas.append(actual)
        actual = None

    if actual is not None:
        logicas.append(actual)
    return logicas


def separar_clave_valor(linea):
    """
    Separa una línea en (clave, valor) siguiendo las reglas de Java:
    el separador es el primer '=', ':' o espacio que no esté escapado.
    """
    linea = linea.lstrip()
    i = 0
    while i < len(linea):
        c = linea[i]
        if c == "\\":
            i += 2
            continue
        if c in "=: \t\f":
            break
        i += 1

    clave = linea[:i]
    resto = linea[i:].lstrip(" \t\f")
    if resto[:1] in ("=", ":"):
        resto = resto[1:].lstrip(" \t\f")
    return clave, resto


def convertir_clave(clave):
    """spring.datasource.portal.driver-class-name -> SPRING_DATASOURCE_PORTAL_DRIVER_CLASS_NAME"""
    clave = re.sub(r"\\(.)", r"\1", clave)
    return re.sub(r"[.\-]", "_", clave).upper()


def es_valor_encriptado(valor):
    valor = valor.strip()
    return (
        len(valor) >= LARGO_MINIMO_ENCRIPTADO
        and re.match(PATRON_ENCRIPTADO, valor) is not None
        and re.search(r"[A-Z]", valor) is not None
        and re.search(r"[a-z]", valor) is not None
        and re.search(r"[0-9]", valor) is not None
    )


def es_de_ambiente(clave, valor):
    """True si la variable cambia entre ambientes o es sensible."""
    if clave in EXCLUIR_SIEMPRE:
        return False
    if clave in INCLUIR_SIEMPRE:
        return True

    partes = clave.lower().split(".")
    if any(palabra in parte for parte in partes for palabra in PALABRAS_CLAVE):
        return True
    if any(parte.endswith(fin) for parte in partes for fin in TERMINACIONES_CLAVE):
        return True
    valor = valor.strip()
    if es_valor_encriptado(valor):
        return True
    return any(re.search(patron, valor) for patron in PATRONES_VALOR)


def parsear_properties(ruta):
    variables = []
    for linea in unir_continuaciones(leer_lineas(ruta)):
        limpia = linea.strip()
        if not limpia or limpia[0] in "#!":
            continue
        clave, valor = separar_clave_valor(linea)
        if clave:
            variables.append((clave, valor))
    return variables


def resolver_salida(entrada, salida):
    salida = Path(salida).expanduser()
    if salida.is_dir() or str(salida).endswith(("/", "\\")) or not salida.suffix:
        salida = salida / f"{entrada.stem}.txt"
    return salida


def main():
    parser = argparse.ArgumentParser(
        description="Extrae las variables de ambiente/sensibles de un .properties a CLAVE=VALOR en un .txt")
    parser.add_argument("entrada", nargs="?", help="Ruta del archivo .properties")
    parser.add_argument("salida", nargs="?", help="Ruta del .txt de salida o carpeta donde crearlo")
    parser.add_argument("--detalle", action="store_true",
                        help="Lista las variables que se quedan quemadas en el .properties")
    args = parser.parse_args()

    entrada = args.entrada or input("Ruta del archivo .properties: ").strip().strip("'\"")
    salida = args.salida or input("Ruta de salida (.txt o carpeta): ").strip().strip("'\"")

    entrada = Path(entrada).expanduser()
    if not entrada.is_file():
        sys.exit(f"ERROR: no existe el archivo {entrada}")

    variables = parsear_properties(entrada)
    if not variables:
        sys.exit(f"ERROR: no se encontraron variables en {entrada}")

    # Las que ya tienen token (#{...}#) no tienen el valor real: no se pueden llevar al .txt.
    con_token = [c for c, v in variables if re.fullmatch(r"#\{[^}]+\}#", v.strip())]
    variables = [(c, v) for c, v in variables if c not in con_token]
    if con_token:
        print(f"AVISO: {len(con_token)} variables ya tienen token (#{{...}}#) en vez del valor real; no van al .txt. "
              "Si necesitas sus valores, sácalos del .bak o de una copia anterior del .properties.")

    de_ambiente = [(c, v) for c, v in variables if es_de_ambiente(c, v)]
    quemadas = [c for c, v in variables if not es_de_ambiente(c, v)]
    if not de_ambiente:
        sys.exit(f"ERROR: no se encontraron variables de ambiente en {entrada}")

    lineas_salida = []
    vistas = {}
    for clave, valor in de_ambiente:
        nueva = convertir_clave(clave)
        if nueva in vistas:
            print(f"AVISO: '{clave}' queda como {nueva}, que ya existía (de '{vistas[nueva]}'). "
                  f"Se deja la última, igual que en Spring.")
            lineas_salida = [l for l in lineas_salida if not l.startswith(f"{nueva}=")]
        vistas[nueva] = clave
        if valor != valor.rstrip():
            print(f"AVISO: el valor de {nueva} tenía espacios al final; se copian sin ellos.")
            valor = valor.rstrip()
        lineas_salida.append(f"{nueva}={valor}")

    ruta_salida = resolver_salida(entrada, salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text("\n".join(lineas_salida) + "\n", encoding="utf-8")

    print(f"{len(lineas_salida)} variables de ambiente escritas en {ruta_salida}")
    print(f"{len(quemadas)} variables se quedan quemadas en el .properties")
    if args.detalle:
        print("\nQuedan en el .properties:")
        for clave in quemadas:
            print(f"  {clave}")


if __name__ == "__main__":
    main()
