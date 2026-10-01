#!/usr/bin/env python3
"""
Reemplaza los tokens #{VARIABLE}# de los manifiestos de Kubernetes
(kubernetes.yaml, hpa.yaml y vpa.yaml) con los valores de los Variable Groups
de Azure DevOps.

Flujo:
  1. Consulta los Variable Groups del proyecto.
  2. Toma los valores en orden de jerarquía: primero el grupo específico del
     servicio (p. ej. backend-vars-develop) y después el general del ambiente
     (p. ej. miproyecto-vars-develop). Si una variable está en los dos, gana la
     del grupo del servicio.
  3. Reemplaza los tokens en cada .yaml del directorio (modifica los archivos).

Los tokens que no estén en ningún grupo se dejan como están (#{TAG_IMAGEN}#,
por ejemplo, lo pone el pipeline) y se listan al final.

Uso:
    python3 vargroups_a_manifiestos.py <directorio> --proyecto <PROYECTO>

Nombres de los grupos (se pueden cambiar con --grupo-servicio / --grupo-general):
    servicio: <servicio>-vars-<ambiente>   (backend-vars-develop)
    general:  <proyecto>-vars-<ambiente>   (miproyecto-vars-develop)

    <servicio> por defecto es el nombre de la carpeta del servicio: si el
    directorio se llama "manifiestos", la carpeta de arriba (backend).
    <ambiente> por defecto es develop.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from txt_a_vargroup import AzDevOps, ErrorAz  # noqa: E402

MANIFIESTOS = ("kubernetes.yaml", "hpa.yaml", "vpa.yaml")
TOKEN = re.compile(r"#\{([^}]+)\}#")

# Tokens que NUNCA se reemplazan, aunque estén en los Variable Groups (los resuelve el pipeline).
NO_REEMPLAZAR = {"REPLICAS"}

# Campos que siempre quedan con un valor fijo, sin importar qué tenga la plantilla.
# {archivo: {campo: valor}}
CAMPOS_FIJOS = {
    "kubernetes.yaml": {"replicas": "#{REPLICAS}#"},
    "hpa.yaml": {"minReplicas": "#{REPLICAS}#"},
}


def fijar_campos(nombre_archivo, texto):
    """Pone el valor fijo en los campos de CAMPOS_FIJOS. Devuelve (texto, campos_cambiados)."""
    cambiados = []
    for campo, valor in CAMPOS_FIJOS.get(nombre_archivo, {}).items():
        patron = re.compile(rf"^([ \t]*{re.escape(campo)}:[ \t]*)([^\r\n]*?)[ \t]*(?=\r?$)", re.M)

        def poner(m):
            if m.group(2).strip() != valor:
                cambiados.append((campo, m.group(2).strip(), valor))
            return m.group(1) + valor

        texto = patron.sub(poner, texto)
    return texto, cambiados


def nombre_servicio(directorio):
    return (directorio.parent.name if directorio.name.lower() == "manifiestos" else directorio.name).lower()


def buscar(grupos, nombre):
    return next((g for g in grupos if g["name"].lower() == nombre.lower()), None)


def valores_de(grupo):
    """{nombre_en_minúscula: (nombre, valor, es_secreta)} de un Variable Group."""
    valores = {}
    for nombre, datos in (grupo.get("variables") or {}).items():
        datos = datos or {}
        valores[nombre.lower()] = (nombre, datos.get("value"), bool(datos.get("isSecret")))
    return valores


def leer(ruta):
    with open(ruta, encoding="utf-8", newline="") as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(
        description="Reemplaza los #{TOKENS}# de kubernetes.yaml, hpa.yaml y vpa.yaml con los Variable Groups")
    parser.add_argument("directorio", nargs="?", help="Directorio con kubernetes.yaml, hpa.yaml y vpa.yaml")
    parser.add_argument("--proyecto", "-p", help="Proyecto de Azure DevOps")
    parser.add_argument("--ambiente", "-a", default="develop", help="Ambiente (por defecto: develop)")
    parser.add_argument("--servicio", "-s", help="Servicio (por defecto: nombre de la carpeta del servicio)")
    parser.add_argument("--grupo-servicio", help="Nombre exacto del Variable Group del servicio")
    parser.add_argument("--grupo-general", help="Nombre exacto del Variable Group general del ambiente")
    parser.add_argument("--organizacion", help="URL de la organización (por defecto, la configurada en el CLI)")
    parser.add_argument("--simular", action="store_true", help="Muestra qué reemplazaría sin modificar los archivos")
    args = parser.parse_args()

    directorio = Path(args.directorio or input("Directorio de los manifiestos: ").strip().strip("'\"")).expanduser()
    proyecto = args.proyecto or input("Proyecto de Azure DevOps: ").strip()
    if not directorio.is_dir():
        sys.exit(f"ERROR: no existe el directorio {directorio}")

    archivos = [directorio / n for n in MANIFIESTOS if (directorio / n).is_file()]
    for faltante in sorted(set(MANIFIESTOS) - {a.name for a in archivos}):
        print(f"AVISO: no está {faltante} en {directorio}, se omite.")
    if not archivos:
        sys.exit(f"ERROR: no hay ninguno de {', '.join(MANIFIESTOS)} en {directorio}")

    servicio = (args.servicio or nombre_servicio(directorio)).lower()
    nombre_grupo_servicio = args.grupo_servicio or f"{servicio}-vars-{args.ambiente}"
    nombre_grupo_general = args.grupo_general or f"{proyecto.lower()}-vars-{args.ambiente}"

    # 1. Consultar los Variable Groups del proyecto
    az = AzDevOps(proyecto, args.organizacion)
    try:
        grupos = az.ejecutar(["pipelines", "variable-group", "list"]) or []
    except ErrorAz as e:
        sys.exit(f"ERROR consultando Azure DevOps:\n{e}\n\n"
                 "Si es un problema de autenticación, corre 'az login' y vuelve a intentar.")

    print(f"Variable Groups del proyecto '{proyecto}':")
    for g in sorted(grupos, key=lambda g: g["name"].lower()):
        print(f"  - {g['name']} (id {g['id']})")

    grupo_servicio = buscar(grupos, nombre_grupo_servicio)
    grupo_general = buscar(grupos, nombre_grupo_general)
    if not grupo_servicio and not grupo_general:
        sys.exit(f"\nERROR: no se encontró '{nombre_grupo_servicio}' ni '{nombre_grupo_general}'.\n"
                 "Indica los nombres con --grupo-servicio y --grupo-general.")

    # 2. Valores en orden de jerarquía: el general primero y el del servicio encima
    valores, origen = {}, {}
    print("\nOrden de jerarquía:")
    for posicion, (nombre, grupo) in enumerate(
            [(nombre_grupo_servicio, grupo_servicio), (nombre_grupo_general, grupo_general)], start=1):
        if grupo:
            print(f"  {posicion}. {grupo['name']} ({len(grupo.get('variables') or {})} variables)")
        else:
            print(f"  {posicion}. {nombre} -> AVISO: no existe en el proyecto, se omite")
    for grupo in (grupo_general, grupo_servicio):
        if grupo:
            for clave, dato in valores_de(grupo).items():
                valores[clave] = dato
                origen[clave] = grupo["name"]

    # 3. Reemplazar en cada .yaml
    sin_valor, secretas, omitidos = set(), set(), set()
    prefijo = "[SIMULACIÓN] " if args.simular else ""
    print()
    for archivo in archivos:
        original = leer(archivo)
        texto, fijados = fijar_campos(archivo.name, original)
        reemplazos = []

        def reemplazar(m):
            token = m.group(1).strip()
            if token.upper() in NO_REEMPLAZAR:
                omitidos.add(token)
                return m.group(0)
            dato = valores.get(token.lower())
            if dato is None:
                sin_valor.add(token)
                return m.group(0)
            _, valor, es_secreta = dato
            if es_secreta or valor is None:
                secretas.add(token)
                return m.group(0)
            reemplazos.append((token, valor, origen[token.lower()]))
            return valor

        nuevo = TOKEN.sub(reemplazar, texto)
        print(f"{prefijo}{archivo.name}: {len(reemplazos)} reemplazos")
        for campo, antes, despues in fijados:
            print(f"    {campo}: {antes} -> {despues}   (campo fijo)")
        for token, valor, de in dict.fromkeys(reemplazos):
            veces = reemplazos.count((token, valor, de))
            print(f"    #{{{token}}}# -> {valor}   ({de}{f', {veces} veces' if veces > 1 else ''})")

        if nuevo != original and not args.simular:
            with open(archivo, "w", encoding="utf-8", newline="") as f:
                f.write(nuevo)

    if omitidos:
        print("\nTokens que no se reemplazan por configuración (NO_REEMPLAZAR): " + ", ".join(sorted(omitidos)))
    if sin_valor:
        print("\nTokens sin valor en los Variable Groups (se dejan igual): " + ", ".join(sorted(sin_valor)))
    if secretas:
        print("Tokens que son variables secretas (el CLI no entrega su valor, se dejan igual): "
              + ", ".join(sorted(secretas)))
    if args.simular:
        print("\nSimulación: no se modificó ningún archivo.")


if __name__ == "__main__":
    main()
