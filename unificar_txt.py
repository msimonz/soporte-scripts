#!/usr/bin/env python3
"""
Unifica en un solo .txt las variables de los .txt (CLAVE=VALOR) que hay en los
subdirectorios de un directorio. Cada subdirectorio es un servicio.

    PROPERTIES/
      backend-despues-del-cambio/properties.txt                        -> servicio "backend"
      otro-backend-despues-del-cambio/properties.txt  -> servicio "otro-backend"

Reglas:
  - Variable que está en un solo servicio: se copia tal cual.
  - Variable repetida con el MISMO valor en todos los servicios que la tienen:
    se copia una sola vez.
  - Variable repetida con valores DIFERENTES: se copia una vez por servicio,
    con el nombre del servicio como sufijo en la clave:
        SPRING_PROFILES_ACTIVE_BACKEND=develop
        SPRING_PROFILES_ACTIVE_OTRO_BACKEND=${profile:develop}

El nombre del servicio es el del subdirectorio sin "-despues-del-cambio" ni
"-antes-del-cambio" (se ajusta en SUFIJOS_DIRECTORIO).

Al inicio del .txt unificado queda un comentario con los servicios y su sufijo,
que usa properties_a_tokens.py. txt_a_vargroup.py ignora esas líneas.

Uso:
    python3 unificar_txt.py <directorio> [--salida <archivo.txt>]

    Por defecto el resultado queda en <directorio>/unificado.txt.
"""

import argparse
import re
import sys
from pathlib import Path

# Terminaciones que se le quitan al nombre del subdirectorio para obtener el nombre del servicio.
SUFIJOS_DIRECTORIO = ("-despues-del-cambio", "-antes-del-cambio")

ENCABEZADO_SERVICIOS = "# SERVICIOS:"


def nombre_servicio(directorio):
    nombre = directorio.name
    for sufijo in SUFIJOS_DIRECTORIO:
        if nombre.lower().endswith(sufijo):
            return nombre[: -len(sufijo)]
    return nombre


def sufijo_servicio(servicio):
    """otro-backend -> OTRO_BACKEND"""
    return re.sub(r"[^A-Za-z0-9]+", "_", servicio).strip("_").upper()


def leer_txt(ruta):
    """Devuelve [(clave, valor)] en el orden del archivo."""
    variables = []
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1):
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        if "=" not in linea:
            print(f"AVISO: {ruta}, línea {n} sin '=', se ignora: {linea}")
            continue
        clave, valor = linea.split("=", 1)
        variables.append((clave.strip(), valor.rstrip()))
    return variables


def leer_servicios_de_unificado(ruta):
    """Lee el encabezado '# SERVICIOS:' del unificado. Devuelve {servicio: sufijo}."""
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.startswith(ENCABEZADO_SERVICIOS):
            pares = [p.strip() for p in linea[len(ENCABEZADO_SERVICIOS):].split(",") if p.strip()]
            return dict(p.split("=", 1) for p in pares if "=" in p)
    return {}


def main():
    parser = argparse.ArgumentParser(description="Unifica los .txt de los subdirectorios en un solo .txt")
    parser.add_argument("directorio", nargs="?", help="Directorio cuyos subdirectorios tienen los .txt")
    parser.add_argument("--salida", "-o", help="Ruta del .txt unificado (por defecto <directorio>/unificado.txt)")
    args = parser.parse_args()

    directorio = Path(args.directorio or input("Directorio: ").strip().strip("'\"")).expanduser()
    if not directorio.is_dir():
        sys.exit(f"ERROR: no existe el directorio {directorio}")
    salida = Path(args.salida).expanduser() if args.salida else directorio / "unificado.txt"

    # 1. Leer los .txt de cada subdirectorio (un servicio por subdirectorio)
    servicios = {}  # servicio -> [(clave, valor)]
    for sub in sorted(p for p in directorio.iterdir() if p.is_dir()):
        txts = sorted(t for t in sub.rglob("*.txt") if t.resolve() != salida.resolve())
        if not txts:
            continue
        if len(txts) > 1:
            sys.exit(f"ERROR: {sub} tiene más de un .txt ({', '.join(t.name for t in txts)}). "
                     "Deja uno solo por servicio.")
        servicio = nombre_servicio(sub)
        if servicio in servicios:
            sys.exit(f"ERROR: hay dos subdirectorios para el servicio '{servicio}'.")
        servicios[servicio] = leer_txt(txts[0])
        print(f"{servicio}: {len(servicios[servicio])} variables ({txts[0].relative_to(directorio)})")

    if not servicios:
        sys.exit(f"ERROR: no se encontraron .txt en los subdirectorios de {directorio}")

    # 2. Agrupar por clave: {clave: {servicio: valor}}, conservando el orden de aparición
    por_clave = {}
    for servicio, variables in servicios.items():
        for clave, valor in variables:
            por_clave.setdefault(clave, {})[servicio] = valor

    # 3. Armar el unificado
    lineas, iguales, diferentes = [], [], []
    for clave, valores in por_clave.items():
        if len(set(valores.values())) == 1:
            lineas.append((clave, next(iter(valores.values()))))
            if len(valores) > 1:
                iguales.append(clave)
        else:
            diferentes.append(clave)
            for servicio, valor in valores.items():
                lineas.append((f"{clave}_{sufijo_servicio(servicio)}", valor))

    claves = [c for c, _ in lineas]
    repetidas = sorted({c for c in claves if claves.count(c) > 1})
    if repetidas:
        sys.exit("ERROR: al agregar los sufijos, estas claves chocan con otras que ya existían: "
                 + ", ".join(repetidas))

    encabezado = [
        "# Generado por unificar_txt.py. No editar este encabezado: lo usa properties_a_tokens.py.",
        ENCABEZADO_SERVICIOS + " " + ", ".join(f"{s}={sufijo_servicio(s)}" for s in servicios),
    ]
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text("\n".join(encabezado + [f"{c}={v}" for c, v in lineas]) + "\n", encoding="utf-8")

    print(f"\n{len(lineas)} variables escritas en {salida}")
    print(f"  {len(iguales)} repetidas con el mismo valor (se copiaron una vez)")
    print(f"  {len(diferentes)} repetidas con valor diferente (se copiaron con el sufijo del servicio)")
    for clave in diferentes:
        print(f"    {clave} -> " + ", ".join(f"{clave}_{sufijo_servicio(s)}" for s in por_clave[clave]))


if __name__ == "__main__":
    main()
