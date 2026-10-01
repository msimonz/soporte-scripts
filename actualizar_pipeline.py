#!/usr/bin/env python3
"""
Modifica un azure-pipeline.yaml para:

  1. Dejar la sección `variables:` igual que en MiProyecto/backend/azure-pipeline.yaml:
     un solo Variable Group por rama, "vars-<rama>".

         variables:
         - name: system.debug
           value: false
         - ${{ if eq(variables['Build.SourceBranchName'], 'develop') }}:
           - group: "vars-develop"
         - ${{ if eq(variables['Build.SourceBranchName'], 'qa') }}:
           - group: "vars-qa"
         ...

  2. Borrar los bloques compileSecureFiles y deploySecureFiles (los archivos
     seguros que reemplazaban el .properties).

El resto del archivo queda igual (trigger, resources, stages y los demás
parámetros). Se respeta la indentación que use el archivo.

Uso:
    python3 actualizar_pipeline.py <azure-pipeline.yaml | directorio> [--simular]

    Con un directorio, usa el azure-pipeline.yaml (o .yml) que haya en él.
    --simular muestra los cambios sin modificar el archivo.
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

# Ramas y nombre del Variable Group de cada una (en el orden en que quedan en el archivo).
RAMAS = ("develop", "qa", "preprod", "master")
NOMBRE_GRUPO = "vars-{rama}"

# Bloques de stages.parameters que se borran.
BLOQUES_A_BORRAR = ("compileSecureFiles", "deploySecureFiles")

NOMBRES_PIPELINE = ("azure-pipeline.yaml", "azure-pipeline.yml", "azure-pipelines.yaml", "azure-pipelines.yml")


def sangria(linea):
    return len(linea) - len(linea.lstrip(" "))


def es_raiz(linea):
    """Línea con una clave de primer nivel (sin sangría), como 'stages:'."""
    return bool(linea.strip()) and not linea[0].isspace() and not linea.startswith(("#", "-"))


def bloque_variables(indent):
    """Arma la sección variables: con la sangría de lista que usa el archivo (0 o 2 espacios)."""
    p = " " * indent
    lineas = [
        "variables:",
        f"{p}- name: system.debug",
        f"{p}  value: false",
    ]
    for rama in RAMAS:
        lineas.append(f"{p}- ${{{{ if eq(variables['Build.SourceBranchName'], '{rama}') }}}}:")
        lineas.append(f'{p}  - group: "{NOMBRE_GRUPO.format(rama=rama)}"')
    return lineas


def reemplazar_variables(lineas):
    inicio = next((i for i, l in enumerate(lineas) if re.match(r"^variables:\s*$", l)), None)
    if inicio is None:
        sys.exit("ERROR: el archivo no tiene una sección 'variables:' de primer nivel.")

    fin = inicio + 1
    while fin < len(lineas) and not es_raiz(lineas[fin]):
        fin += 1
    # Las líneas vacías del final del bloque se conservan fuera de él (separan de la siguiente sección).
    while fin > inicio + 1 and not lineas[fin - 1].strip():
        fin -= 1

    primer_item = next((l for l in lineas[inicio + 1:fin] if l.lstrip().startswith("- ")), "- ")
    nuevo = bloque_variables(sangria(primer_item))
    return lineas[:inicio] + nuevo + lineas[fin:], lineas[inicio:fin], nuevo


def borrar_bloques(lineas):
    resultado, borrados = [], []
    i = 0
    while i < len(lineas):
        m = re.match(rf"^(\s*)({'|'.join(BLOQUES_A_BORRAR)}):\s*$", lineas[i])
        if not m:
            resultado.append(lineas[i])
            i += 1
            continue

        nivel = len(m.group(1))
        bloque = [lineas[i]]
        i += 1
        # Pertenecen al bloque las líneas más indentadas o los "- " al mismo nivel que la clave.
        while i < len(lineas) and lineas[i].strip() and (
                sangria(lineas[i]) > nivel or (sangria(lineas[i]) == nivel and lineas[i].lstrip().startswith("- "))):
            bloque.append(lineas[i])
            i += 1
        borrados.append((m.group(2), bloque))
    return resultado, borrados


def destino_secure_file(linea):
    """'- origen: "destino"' -> destino (con o sin comillas)."""
    m = re.search(r':\s*(?:"([^"]+)"|\'([^\']+)\'|(\S.*?))\s*$', linea)
    return next((g for g in m.groups() if g), None) if m else None


def validar_yaml(texto):
    try:
        import yaml
    except ImportError:
        return None
    try:
        yaml.safe_load(texto)
        return True
    except yaml.YAMLError as e:
        return str(e)


def resolver_archivo(ruta):
    if ruta.is_file():
        return ruta
    if ruta.is_dir():
        for nombre in NOMBRES_PIPELINE:
            if (ruta / nombre).is_file():
                return ruta / nombre
        sys.exit(f"ERROR: no hay {' / '.join(NOMBRES_PIPELINE)} en {ruta}")
    sys.exit(f"ERROR: no existe {ruta}")


def main():
    parser = argparse.ArgumentParser(
        description="Deja la sección variables como en backend y borra compileSecureFiles/deploySecureFiles")
    parser.add_argument("ruta", nargs="?", help="azure-pipeline.yaml o el directorio que lo contiene")
    parser.add_argument("--simular", action="store_true", help="Muestra los cambios sin modificar el archivo")
    args = parser.parse_args()

    ruta = Path(args.ruta or input("Ruta del azure-pipeline.yaml o de su directorio: ").strip().strip("'\"")).expanduser()
    archivo = resolver_archivo(ruta)

    with open(archivo, encoding="utf-8", newline="") as f:
        original = f.read()
    salto = "\r\n" if "\r\n" in original else "\n"
    termina_en_salto = original.endswith(("\n", "\r"))
    lineas = original.splitlines()

    lineas, variables_antes, variables_despues = reemplazar_variables(lineas)
    lineas, borrados = borrar_bloques(lineas)

    nuevo = salto.join(lineas) + (salto if termina_en_salto else "")
    if nuevo == original:
        print(f"{archivo}: ya está como debe quedar, no hay cambios.")
        return

    validacion = validar_yaml(nuevo)
    if isinstance(validacion, str):
        sys.exit(f"ERROR: el resultado no es un YAML válido, no se modificó el archivo:\n{validacion}")

    print(f"Archivo: {archivo}\n")
    if variables_antes != variables_despues:
        grupos_antes = re.findall(r'group:\s*"?([^"\s]+)"?', "\n".join(variables_antes))
        print("Sección variables:")
        print(f"  antes:   {', '.join(grupos_antes) or '(sin grupos)'}")
        print(f"  después: {', '.join(NOMBRE_GRUPO.format(rama=r) for r in RAMAS)}")
    else:
        print("Sección variables: ya estaba igual.")

    if borrados:
        print("\nBloques borrados:")
        for nombre, bloque in borrados:
            print(f"  {nombre}:")
            for linea in bloque[1:]:
                print(f"      {linea.strip()}")
        # Destinos que no son application.properties: probablemente no se reemplazan con los tokens.
        otros = sorted({
            destino
            for _, bloque in borrados for linea in bloque[1:]
            for destino in [destino_secure_file(linea)]
            if destino and not destino.endswith("application.properties")
        })
        if otros:
            print("\nATENCIÓN: también se borraron archivos seguros que NO son application.properties:")
            for destino in otros:
                print(f"    {destino}")
            print("  Si el servicio los necesita, tendrán que llegar de otra forma (tokens o secure files).")
    else:
        print("\nNo había compileSecureFiles ni deploySecureFiles.")

    if args.simular:
        print("\n[SIMULACIÓN] Cambios que se harían:\n")
        diff = difflib.unified_diff(original.splitlines(), nuevo.splitlines(),
                                    fromfile=f"{archivo.name} (actual)", tofile=f"{archivo.name} (nuevo)", lineterm="")
        print("\n".join(diff))
        print("\nSimulación: no se modificó el archivo.")
        return

    with open(archivo, "w", encoding="utf-8", newline="") as f:
        f.write(nuevo)
    print(f"\n{archivo} actualizado." + ("" if validacion else " (No se pudo validar el YAML: falta PyYAML.)"))


if __name__ == "__main__":
    main()
