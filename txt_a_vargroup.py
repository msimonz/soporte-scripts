#!/usr/bin/env python3
"""
Sube a un Variable Group de Azure DevOps las variables de un .txt con formato
CLAVE=VALOR (el que generan properties_a_txt.py y unificar_txt.py).

Tiene dos modos:
  - Por defecto: sube las variables a un Variable Group que YA EXISTE. Si no
    existe, falla sin hacer nada.
  - --crear: crea un Variable Group NUEVO con el nombre indicado y le sube las
    variables. Si ya existe uno con ese nombre, falla sin hacer nada, salvo que
    se use --reemplazar: en ese caso BORRA el existente y lo crea de nuevo.

Con --borrar-otros, después de subir las variables (y solo si no hubo errores)
BORRA TODOS los demás Variable Groups del proyecto, menos el indicado y los que
se pasen en --conservar.

Usa el Azure CLI con la extensión azure-devops. La organización se toma de la
configuración por defecto del CLI (az devops configure --list); solo hay que
indicar el proyecto y el nombre del Variable Group.

Las variables sensibles (password, secret, token, access, ...key) se crean
como secretas. Su valor se le pasa al CLI por variable de entorno, no por la
línea de comandos.

Uso:
    python3 txt_a_vargroup.py <archivo.txt> --proyecto <PROYECTO> --grupo <VARIABLE_GROUP> [--crear [--reemplazar]]

Opciones:
    --simular         Muestra qué haría sin crear, borrar ni modificar nada.
    --crear           Crea el Variable Group (debe no existir) y le sube las variables.
    --reemplazar      Con --crear: si el Variable Group ya existe, lo borra y lo crea de nuevo.
                      Pide confirmación escribiendo el nombre del grupo.
    --borrar-otros    Después de subir las variables, BORRA todos los demás Variable Groups del
                      proyecto. Pide confirmación escribiendo el nombre del proyecto.
    --conservar       Con --borrar-otros: nombres de otros grupos que NO se deben borrar.
    --si              Con --reemplazar o --borrar-otros: no pide confirmación.
    --autorizar       Con --crear: deja el grupo nuevo accesible para todos los pipelines.
    --sobrescribir    Actualiza las variables que ya existen en el grupo (por defecto se saltan).
    --sin-secretas    Crea todas las variables como no secretas.
    --organizacion    URL de la organización, si no quieres usar la configurada por defecto.

Si no se pasan el archivo, el proyecto o el grupo, el script los pide por consola.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Si alguna parte del nombre (entre _) contiene una de estas palabras, la variable se crea como secreta.
PALABRAS_SECRETAS = ("PASSWORD", "PASSWD", "PWD", "SECRET", "ACCESS", "CREDENTIAL")
# Si alguna parte del nombre TERMINA en una de estas palabras, también (APPLICATIONKEY, APIKEY).
TERMINACIONES_SECRETAS = ("KEY",)
# Si alguna parte del nombre ES exactamente una de estas palabras, también
# (ACCESS_TOKEN sí; VALIDARTOKEN_ENDPOINT no, porque es una URL).
PARTES_SECRETAS = ("TOKEN",)

PREFIJO_ENV_SECRETO = "AZURE_DEVOPS_EXT_PIPELINE_VAR_"


class ErrorAz(Exception):
    pass


def es_secreta(nombre):
    partes = nombre.upper().split("_")
    if any(p in parte for parte in partes for p in PALABRAS_SECRETAS):
        return True
    if any(parte in PARTES_SECRETAS for parte in partes):
        return True
    return any(parte.endswith(t) for parte in partes for t in TERMINACIONES_SECRETAS)


def leer_txt(ruta):
    variables = []
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1):
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        if "=" not in linea:
            print(f"AVISO: línea {n} sin '=', se ignora: {linea}")
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", clave):
            print(f"AVISO: línea {n} tiene un nombre de variable no válido, se ignora: {clave}")
            continue
        if valor != valor.rstrip():
            print(f"AVISO: el valor de {clave} tiene espacios al final (se envían tal cual).")
        variables.append((clave, valor))
    return variables


class AzDevOps:
    def __init__(self, proyecto, organizacion=None, simular=False):
        self.az = shutil.which("az")
        if not self.az:
            sys.exit("ERROR: no se encontró el comando 'az'. Revisa que el Azure CLI esté instalado y en el PATH.")
        self.proyecto = proyecto
        self.organizacion = organizacion
        self.simular = simular

    def ejecutar(self, args, env_extra=None, escritura=False):
        comando = [self.az, *args, "--project", self.proyecto, "--output", "json", "--only-show-errors"]
        if self.organizacion:
            comando += ["--organization", self.organizacion]
        if escritura and self.simular:
            return None

        env = os.environ.copy()
        env.update(env_extra or {})
        resultado = subprocess.run(comando, capture_output=True, text=True, env=env)
        if resultado.returncode != 0:
            raise ErrorAz(resultado.stderr.strip() or resultado.stdout.strip())
        salida = resultado.stdout.strip()
        if not salida:
            return None
        try:
            return json.loads(salida)
        except json.JSONDecodeError:
            # Algunos comandos (como 'variable-group delete') responden con texto y no con JSON.
            return salida

    def buscar_grupo(self, nombre):
        grupos = self.ejecutar(["pipelines", "variable-group", "list", "--group-name", nombre]) or []
        for grupo in grupos:
            if grupo["name"].lower() == nombre.lower():
                return grupo
        return None

    def crear_grupo(self, nombre, clave, valor, autorizar):
        """Azure exige al menos una variable para crear el grupo."""
        return self.ejecutar(
            ["pipelines", "variable-group", "create", "--name", nombre,
             "--variables", f"{clave}={valor}", "--authorize", "true" if autorizar else "false"],
            escritura=True,
        )

    def borrar_grupo(self, id_grupo):
        self.ejecutar(["pipelines", "variable-group", "delete", "--group-id", str(id_grupo), "--yes"], escritura=True)

    def crear_variable(self, id_grupo, nombre, valor, secreta):
        args = ["pipelines", "variable-group", "variable", "create", "--group-id", str(id_grupo), "--name", nombre]
        if secreta:
            args += ["--secret", "true"]
            env = {PREFIJO_ENV_SECRETO + nombre: valor}
        else:
            args += [f"--value={valor}"]
            env = None
        self.ejecutar(args, env_extra=env, escritura=True)

    def actualizar_variable(self, id_grupo, nombre, valor, secreta):
        args = ["pipelines", "variable-group", "variable", "update", "--group-id", str(id_grupo), "--name", nombre]
        if secreta:
            args += ["--secret", "true", "--prompt-value", "true"]
            env = {PREFIJO_ENV_SECRETO + nombre: valor}
        else:
            args += ["--secret", "false", f"--value={valor}"]
            env = None
        self.ejecutar(args, env_extra=env, escritura=True)


def pedir(valor, mensaje):
    return valor or input(mensaje).strip().strip("'\"")


def confirmar_borrado(grupo, proyecto):
    n = len(grupo.get("variables") or {})
    print(f"\nATENCIÓN: se va a BORRAR el Variable Group '{grupo['name']}' (id {grupo['id']}) del proyecto "
          f"'{proyecto}', con sus {n} variables.")
    print("  - No se puede deshacer. Los valores de las variables secretas se pierden.")
    print("  - El grupo nuevo tendrá otro id y sus permisos de pipelines se configuran de nuevo.")
    respuesta = input(f"Escribe el nombre del grupo para confirmar ({grupo['name']}): ").strip()
    return respuesta == grupo["name"]


def confirmar_borrado_otros(grupos, proyecto):
    print(f"\nATENCIÓN: se van a BORRAR {len(grupos)} Variable Groups del proyecto '{proyecto}':")
    for g in grupos:
        print(f"    - {g['name']} (id {g['id']}, {len(g.get('variables') or {})} variables)")
    print("  - No se puede deshacer. Los valores de las variables secretas se pierden.")
    print("  - Los pipelines que usen esos grupos van a fallar hasta que se cambien.")
    respuesta = input(f"Escribe el nombre del proyecto para confirmar ({proyecto}): ").strip()
    return respuesta == proyecto


def borrar_otros_grupos(az, proyecto, nombre_grupo, conservar, args, prefijo):
    """Borra todos los Variable Groups del proyecto menos nombre_grupo y los de conservar.
    Devuelve la lista de nombres que no se pudieron borrar."""
    try:
        grupos = az.ejecutar(["pipelines", "variable-group", "list"]) or []
    except ErrorAz as e:
        sys.exit(f"ERROR listando los Variable Groups:\n{e}")

    mantener = {nombre_grupo.lower(), *(c.lower() for c in conservar)}
    a_borrar = sorted((g for g in grupos if g["name"].lower() not in mantener), key=lambda g: g["name"].lower())
    if not a_borrar:
        print(f"\n{prefijo}No hay otros Variable Groups para borrar en '{proyecto}'.")
        return []

    no_encontrados = [c for c in conservar if c.lower() not in {g["name"].lower() for g in grupos}]
    if no_encontrados:
        print(f"\nAVISO: estos grupos de --conservar no existen en el proyecto: {', '.join(no_encontrados)}")

    if args.simular:
        print(f"\n{prefijo}Se borrarían {len(a_borrar)} Variable Groups:")
        for g in a_borrar:
            print(f"    - {g['name']} (id {g['id']}, {len(g.get('variables') or {})} variables)")
        return []

    if not args.si and not confirmar_borrado_otros(a_borrar, proyecto):
        print("Cancelado: el nombre no coincide. No se borró ningún otro Variable Group "
              "(las variables sí quedaron subidas).")
        return []

    fallidos = []
    for g in a_borrar:
        try:
            az.borrar_grupo(g["id"])
            print(f"  - {g['name']} (id {g['id']}) borrado")
        except ErrorAz as e:
            fallidos.append(g["name"])
            print(f"  ! ERROR borrando {g['name']}: {e}")
    print(f"\n{len(a_borrar) - len(fallidos)} Variable Groups borrados, {len(fallidos)} con error.")
    return fallidos


def subir_variables(az, id_grupo, variables, existentes, args, prefijo):
    creadas, actualizadas, saltadas, errores = [], [], [], []
    for clave, valor in variables:
        secreta = es_secreta(clave) and not args.sin_secretas
        marca = " (secreta)" if secreta else ""
        ya_existe = clave.lower() in existentes

        try:
            if ya_existe and not args.sobrescribir:
                saltadas.append(clave)
                print(f"{prefijo}  = {clave} ya existe, se salta (usa --sobrescribir para actualizarla)")
            elif ya_existe:
                az.actualizar_variable(id_grupo, existentes[clave.lower()], valor, secreta)
                actualizadas.append(clave)
                print(f"{prefijo}  ~ {clave}{marca} actualizada")
            else:
                az.crear_variable(id_grupo, clave, valor, secreta)
                creadas.append(clave)
                print(f"{prefijo}  + {clave}{marca}")
        except ErrorAz as e:
            errores.append(clave)
            print(f"  ! ERROR con {clave}: {e}")
    return creadas, actualizadas, saltadas, errores


def crear_grupo_con_variables(az, nombre_grupo, proyecto, variables, args, prefijo):
    """Crea el grupo con la primera variable no secreta (para no exponer ningún secreto) y devuelve
    (id_grupo, variables_pendientes, primera_variable)."""
    pendientes = list(variables)
    indice = next((i for i, (c, _) in enumerate(pendientes) if not es_secreta(c)), 0)
    clave, valor = pendientes.pop(indice)
    secreta = es_secreta(clave) and not args.sin_secretas

    print(f"{prefijo}Creando Variable Group '{nombre_grupo}' en el proyecto '{proyecto}'"
          f"{' (autorizado para todos los pipelines)' if args.autorizar else ''}...")
    try:
        creado = az.crear_grupo(nombre_grupo, clave, valor, args.autorizar)
        id_grupo = creado["id"] if creado else "(nuevo)"
        if secreta:
            # Solo pasa si todas las variables son secretas: se marca como secreta enseguida.
            az.actualizar_variable(id_grupo, clave, valor, secreta=True)
    except ErrorAz as e:
        sys.exit(f"ERROR creando el Variable Group:\n{e}")
    print(f"{prefijo}Variable Group '{nombre_grupo}' creado (id {id_grupo}).")
    print(f"{prefijo}  + {clave}{' (secreta)' if secreta else ''}")
    return id_grupo, pendientes, clave


def main():
    parser = argparse.ArgumentParser(description="Sube las variables de un .txt (CLAVE=VALOR) a un Variable Group de Azure DevOps")
    parser.add_argument("archivo", nargs="?", help="Ruta del .txt con las variables")
    parser.add_argument("--proyecto", "-p", help="Proyecto de Azure DevOps")
    parser.add_argument("--grupo", "-g", help="Nombre del Variable Group")
    parser.add_argument("--organizacion", help="URL de la organización (por defecto, la configurada en el CLI)")
    parser.add_argument("--simular", action="store_true", help="Muestra qué haría sin crear, borrar ni modificar nada")
    parser.add_argument("--crear", action="store_true", help="Crea el Variable Group y le sube las variables")
    parser.add_argument("--reemplazar", action="store_true",
                        help="Con --crear: si el Variable Group existe, lo BORRA y lo crea de nuevo")
    parser.add_argument("--borrar-otros", action="store_true",
                        help="Después de subir las variables, BORRA todos los demás Variable Groups del proyecto")
    parser.add_argument("--conservar", nargs="+", default=[], metavar="GRUPO",
                        help="Con --borrar-otros: otros Variable Groups que NO se deben borrar")
    parser.add_argument("--si", action="store_true",
                        help="Con --reemplazar o --borrar-otros: no pide confirmación antes de borrar")
    parser.add_argument("--autorizar", action="store_true",
                        help="Con --crear: deja el grupo nuevo accesible para todos los pipelines")
    parser.add_argument("--sobrescribir", action="store_true", help="Actualiza las variables que ya existen")
    parser.add_argument("--sin-secretas", action="store_true", help="Crea todas las variables como no secretas")
    args = parser.parse_args()

    if (args.reemplazar or args.autorizar) and not args.crear:
        parser.error("--reemplazar y --autorizar solo se usan junto con --crear")
    if args.si and not (args.reemplazar or args.borrar_otros):
        parser.error("--si solo se usa junto con --reemplazar o --borrar-otros")
    if args.conservar and not args.borrar_otros:
        parser.error("--conservar solo se usa junto con --borrar-otros")

    archivo = Path(pedir(args.archivo, "Ruta del .txt con las variables: ")).expanduser()
    proyecto = pedir(args.proyecto, "Proyecto de Azure DevOps: ")
    nombre_grupo = pedir(args.grupo, "Nombre del Variable Group: ")

    if not archivo.is_file():
        sys.exit(f"ERROR: no existe el archivo {archivo}")
    variables = leer_txt(archivo)
    if not variables:
        sys.exit(f"ERROR: no se encontraron variables en {archivo}")

    az = AzDevOps(proyecto, args.organizacion, args.simular)
    prefijo = "[SIMULACIÓN] " if args.simular else ""

    try:
        grupo = az.buscar_grupo(nombre_grupo)
    except ErrorAz as e:
        sys.exit(f"ERROR consultando Azure DevOps:\n{e}\n\n"
                 "Si es un problema de autenticación, corre 'az login' (o 'az devops login') y vuelve a intentar.")

    creadas = []
    if not args.crear:
        # Modo 1: subir a un grupo existente
        if not grupo:
            sys.exit(f"ERROR: no existe el Variable Group '{nombre_grupo}' en el proyecto '{proyecto}'.\n"
                     "Revisa el nombre, o usa --crear para crearlo.")
        id_grupo = grupo["id"]
        existentes = {k.lower(): k for k in (grupo.get("variables") or {})}
        pendientes = variables
        print(f"{prefijo}Variable Group '{grupo['name']}' encontrado (id {id_grupo}) en el proyecto '{proyecto}'.")
    else:
        # Modo 2: crear un grupo nuevo (y, con --reemplazar, borrar antes el que exista)
        if grupo and not args.reemplazar:
            sys.exit(f"ERROR: ya existe el Variable Group '{grupo['name']}' (id {grupo['id']}) en el proyecto "
                     f"'{proyecto}'.\nUsa --reemplazar para borrarlo y crearlo de nuevo, o quita --crear para "
                     "subir las variables a ese grupo.")
        if grupo:
            if not args.simular and not args.si and not confirmar_borrado(grupo, proyecto):
                sys.exit("Cancelado: el nombre no coincide. No se borró ni se creó nada.")
            try:
                az.borrar_grupo(grupo["id"])
            except ErrorAz as e:
                sys.exit(f"ERROR borrando el Variable Group:\n{e}")
            print(f"{prefijo}Variable Group '{grupo['name']}' (id {grupo['id']}) borrado.")
        id_grupo, pendientes, primera = crear_grupo_con_variables(az, nombre_grupo, proyecto, variables, args, prefijo)
        existentes = {}
        creadas.append(primera)

    nuevas, actualizadas, saltadas, errores = subir_variables(az, id_grupo, pendientes, existentes, args, prefijo)
    creadas += nuevas

    print(f"\n{prefijo}Resumen: {len(creadas)} creadas, {len(actualizadas)} actualizadas, "
          f"{len(saltadas)} saltadas, {len(errores)} con error.")
    if args.crear and not args.autorizar:
        print("Recuerda: el grupo nuevo no está autorizado para los pipelines. Autorízalo en Azure DevOps "
              "(Pipelines > Library > el grupo > Pipeline permissions) o vuelve a crearlo con --autorizar.")
    if errores:
        print("Variables con error: " + ", ".join(errores))
        if args.borrar_otros:
            print("No se borró ningún otro Variable Group porque hubo errores subiendo las variables.")
        sys.exit(1)

    if args.borrar_otros:
        fallidos = borrar_otros_grupos(az, proyecto, nombre_grupo, args.conservar, args, prefijo)
        if fallidos:
            print("Variable Groups que no se pudieron borrar: " + ", ".join(fallidos))
            sys.exit(1)


if __name__ == "__main__":
    main()
