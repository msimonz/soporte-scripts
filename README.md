# Scripts de soporte

Scripts para sacar las variables de ambiente de los `.properties` a Variable Groups de Azure DevOps y dejar los
servicios (properties, manifiestos y pipeline) usando esos grupos.

| Script | Qué hace |
|---|---|
| [`properties_a_txt.py`](#properties_a_txtpy) | Saca las variables de ambiente/sensibles de un `.properties` a un `.txt` (`CLAVE=VALOR`). |
| [`unificar_txt.py`](#unificar_txtpy) | Une los `.txt` de varios servicios en uno solo; las que chocan quedan con el sufijo del servicio. |
| [`properties_a_tokens.py`](#properties_a_tokenspy) | Cambia los valores del `.properties` por tokens `#{CLAVE}#`. |
| [`txt_a_vargroup.py`](#txt_a_vargrouppy) | Sube las variables del `.txt` a un Variable Group (existente o nuevo). |
| [`vargroups_a_manifiestos.py`](#vargroups_a_manifiestospy) | Llena los tokens de `kubernetes.yaml`, `hpa.yaml` y `vpa.yaml` con los Variable Groups. |
| [`actualizar_pipeline.py`](#actualizar_pipelinepy) | Deja el `azure-pipeline.yaml` usando `vars-<rama>` y sin secure files. |

El orden en que se usan está en [Flujo completo](#flujo-completo), al final.

### Requisitos generales

- Python 3.8 o superior. Para verificar la versión: `python3 --version`.
- **Todos los scripts deben estar en la misma carpeta**, porque unos usan código de otros:
  - `properties_a_tokens.py` usa `properties_a_txt.py` y `unificar_txt.py`;
  - `vargroups_a_manifiestos.py` usa `txt_a_vargroup.py`.
- Los que hablan con Azure DevOps (`txt_a_vargroup.py` y `vargroups_a_manifiestos.py`) necesitan el Azure CLI con
  la extensión `azure-devops` (ver los requisitos de [`txt_a_vargroup.py`](#txt_a_vargrouppy)).
- `actualizar_pipeline.py` usa PyYAML, si está instalado, para validar el resultado. Si no está, funciona igual
  pero sin esa validación.
- Todos se corren desde la carpeta `SOPORTE`. Si alguna ruta tiene espacios, ponla entre comillas.

---

## properties_a_txt.py

Toma un archivo `.properties` y genera un `.txt`, en formato `CLAVE=VALOR`, **solo con las variables que cambian
entre ambientes o que son sensibles**: URLs, hosts, usuarios, contraseñas, llaves, etc. Las demás (timeouts, pools,
lifetimes, paths relativos, drivers...) se quedan quemadas en el `.properties` y no van al `.txt`.

La clave pasa a MAYÚSCULAS y los puntos (y guiones) se cambian por `_`. El valor se copia tal cual.

```
spring.datasource.portal.url=jdbc:postgresql://...     ->  SPRING_DATASOURCE_PORTAL_URL=jdbc:postgresql://...
api.empresa.inmuebles.endpoint.base-url=http://... ->  API_EMPRESA_INMUEBLES_ENDPOINT_BASE_URL=http://...
spring.datasource.portal.hikari.max-lifetime=90000     ->  (no va al .txt, se queda en el .properties)
```

### Cómo correrlo

Desde la carpeta `SOPORTE`:

```bash
python3 properties_a_txt.py <archivo.properties> <salida>
```

- `<archivo.properties>`: ruta del archivo que quieres convertir.
- `<salida>`: ruta del `.txt` que se va a crear, o una carpeta. Si es una carpeta, el archivo se crea ahí con el
  mismo nombre del `.properties` y extensión `.txt`. Si la carpeta no existe, se crea.

Si alguna ruta tiene espacios, ponla entre comillas.

### Ejemplos

Generar un `.txt` con nombre específico:

```bash
python3 properties_a_txt.py MiProyecto/backend/src/main/resources/application.properties salida/miproyecto-develop.txt
```

Generar el `.txt` dentro de una carpeta (queda como `salida/application.txt`):

```bash
python3 properties_a_txt.py MiProyecto/backend/src/main/resources/application.properties salida/
```

Sin argumentos, el script pide las rutas por consola (puedes arrastrar el archivo a la terminal):

```bash
python3 properties_a_txt.py
```

Al terminar muestra cuántas variables escribió y cuántas se quedan en el `.properties`:

```
70 variables de ambiente escritas en salida/application.txt
56 variables se quedan quemadas en el .properties
```

Para ver el listado de las que se quedan quemadas, agrega `--detalle`:

```bash
python3 properties_a_txt.py MiProyecto/backend/src/main/resources/application.properties salida/ --detalle
```

### Qué variables van al .txt

Una variable va al `.txt` si cumple cualquiera de estas reglas:

| Regla | Ejemplos |
|---|---|
| Alguna parte de la clave contiene `password`, `secret`, `token`, `access`, `contrasena`, `username`, `user`, `usuario`, `clientid`, `host`, `endpoint` o `bootstrap-servers` | `spring.datasource.erp.password`, `app.empresa.sftp.host`, `pagos.contrasena` |
| Alguna parte de la clave termina en `key`, `url` o `uri` | `api.empresa.gestordocs.applicationKey`, `api.erp.url`, `...endpoint.base-url` |
| El valor es una URL (`http://`, `https://`...), una cadena `jdbc:`, una IP o `host:puerto` | `api.erp.fondos.api=http://...`, Kafka |
| El valor está **encriptado** (ver abajo) | `pagos.reiniciarContrasena=Xy7+Ab9/Cd...`, `app.ftp.password=AbC1...]DeF2...]GhI3...` |

Un valor se considera **encriptado** si tiene 20 caracteres o más, usa solo caracteres de base64
(`A-Z a-z 0-9 + / =`, o varios bloques así separados por `]`) y mezcla mayúsculas, minúsculas y números. Así se
detectan las URLs y contraseñas cifradas aunque la clave no lo diga, sin confundirlas con nombres de archivo
(`comprobanteContable.jasper`) o textos (`notificacionAvanceObra`). Se ajusta en `PATRON_ENCRIPTADO` y
`LARGO_MINIMO_ENCRIPTADO`.

Además, estas claves van siempre al `.txt` aunque no cumplan las reglas (están en `INCLUIR_SIEMPRE`):
`spring.profiles.active`, `app.ssl.check`, `app.empresa.obtener.instanceId`,
`app.empresa.sftp.path.root`, `app.empresa.sftp.path.miProyecto`, `app.ftp.path.extractos` y
`app.ftp.path.extractos.valores`.

Y estas **nunca** van al `.txt`, aunque cumplan las reglas (están en `EXCLUIR_SIEMPRE`): `server.port`, porque no
cambia entre ambientes y se queda quemado en el `.properties`.

Todo lo demás se queda en el `.properties`.

Si alguna variable queda mal clasificada, ajústala al inicio del script, en la sección `CONFIGURACIÓN`:

- `INCLUIR_SIEMPRE`: claves que siempre deben ir al `.txt`.
- `EXCLUIR_SIEMPRE`: claves que nunca deben ir al `.txt`.
- `PALABRAS_CLAVE`, `TERMINACIONES_CLAVE` y `PATRONES_VALOR`: las reglas generales.

Las claves en `INCLUIR_SIEMPRE` y `EXCLUIR_SIEMPRE` se escriben como están en el `.properties`, por ejemplo:

```python
INCLUIR_SIEMPRE = {
    "spring.profiles.active",
    "otra.clave.que.quieras.incluir",
}
```

### Qué tener en cuenta

- Se ignoran las líneas vacías y los comentarios (`#` o `!`).
- Acepta `=`, `:` o espacio como separador entre clave y valor, igual que Java.
- Las claves en camelCase solo pasan a mayúscula, sin `_` adicional: `dataSourceClassName` -> `DATASOURCECLASSNAME`.
- **Avisos que puede mostrar:**
  - `ya tienen token (#{...}#)`: el `.properties` ya pasó por `properties_a_tokens.py` y esas variables no tienen
    el valor real, así que no van al `.txt`. Los valores reales están en el `.bak` o en una copia anterior.
  - `tenía espacios al final`: el valor termina en espacios en el `.properties`. En el `.txt` se copia sin esos
    espacios.
  - `ya existía`: dos claves quedaron con el mismo nombre al convertirlas (o la clave está repetida). Se deja
    la última, igual que hace Spring.
- El `.txt` queda con las contraseñas en texto plano, igual que el `.properties`. No lo subas a git ni lo
  compartas por canales abiertos.

---

## unificar_txt.py

Une en un solo `.txt` las variables de los `.txt` que hay en los subdirectorios de un directorio. Cada
subdirectorio es un servicio:

```
MiProyecto/PROPERTIES/
  backend-despues-del-cambio/properties.txt                         -> servicio "backend"
  otro-backend-despues-del-cambio/properties.txt   -> servicio "otro-backend"
  unificado.txt                                                     <- resultado
```

El nombre del servicio es el del subdirectorio sin `-despues-del-cambio` ni `-antes-del-cambio`. Esas terminaciones
se ajustan en `SUFIJOS_DIRECTORIO`, al inicio del script.

### Reglas

| Caso | Resultado en el unificado |
|---|---|
| La variable está en un solo servicio | Se copia tal cual. |
| Está en varios servicios con el **mismo valor** | Se copia una sola vez, sin sufijo. |
| Está en varios servicios con **valores diferentes** | Se copia una vez por servicio, con el nombre del servicio como sufijo. |

Ejemplo del último caso:

```
SPRING_PROFILES_ACTIVE_BACKEND=develop
SPRING_PROFILES_ACTIVE_OTRO_BACKEND=${profile:develop}
```

El sufijo es el nombre del servicio en mayúsculas, con `_` en vez de `-`.

Al inicio del unificado quedan dos líneas de comentario con los servicios y su sufijo. Las usa
`properties_a_tokens.py`, así que no las borres. `txt_a_vargroup.py` ignora los comentarios.

### Cómo correrlo

Desde la carpeta `SOPORTE`:

```bash
python3 unificar_txt.py <directorio> [--salida <archivo.txt>]
```

### Dónde queda el unificado

- **Por defecto**, en la raíz del directorio que le pasas, con el nombre `unificado.txt`. Si le pasas
  `MiProyecto/PROPERTIES`, queda en `MiProyecto/PROPERTIES/unificado.txt`, al lado de los subdirectorios de los
  servicios.
- **Con `--salida`** (o `-o`), lo deja en la ruta que indiques. Si la carpeta no existe, se crea:

  ```bash
  python3 unificar_txt.py MiProyecto/PROPERTIES --salida MiProyecto/PROPERTIES/miproyecto-develop.txt
  ```

- Si el archivo ya existe, **se sobrescribe**.
- Al terminar, el script muestra la ruta donde lo dejó: `126 variables escritas en .../unificado.txt`.

Esa misma ruta es la que se le pasa después a `txt_a_vargroup.py` y a `properties_a_tokens.py --unificado`.

### Ejemplo

Con la ruta por defecto (queda en `MiProyecto/PROPERTIES/unificado.txt`):

```bash
python3 unificar_txt.py MiProyecto/PROPERTIES
```

Al terminar muestra un resumen con las variables que quedaron con sufijo:

```
126 variables escritas en MiProyecto/PROPERTIES/unificado.txt
  0 repetidas con el mismo valor (se copiaron una vez)
  2 repetidas con valor diferente (se copiaron con el sufijo del servicio)
    SPRING_PROFILES_ACTIVE -> SPRING_PROFILES_ACTIVE_BACKEND, SPRING_PROFILES_ACTIVE_OTRO_BACKEND
    ...
```

### Qué tener en cuenta

- Busca los `.txt` dentro de cada subdirectorio (también en sus subcarpetas). Si un subdirectorio tiene más de
  un `.txt`, el script se detiene: deja uno solo por servicio.
- Los subdirectorios sin `.txt` (por ejemplo `*-antes-del-cambio`) se ignoran.
- El `unificado.txt` no se toma como entrada si vuelves a correr el script.
- Si al agregar un sufijo la clave choca con otra que ya existía, el script se detiene sin escribir nada.
- El unificado tiene las contraseñas en texto plano, igual que los `.txt`.

---

## properties_a_tokens.py

Modifica el `.properties` y cambia el **valor** de cada variable de ambiente o sensible por un token con el nombre
de la variable, en el formato `#{CLAVE}#`:

```
spring.profiles.active=develop                     ->  spring.profiles.active=#{SPRING_PROFILES_ACTIVE}#
spring.datasource.erp.password=MiClave123         ->  spring.datasource.erp.password=#{SPRING_DATASOURCE_ERP_PASSWORD}#
spring.datasource.erp.hikari.max-lifetime=1800000 ->  (no cambia)
```

Usa **las mismas reglas** que `properties_a_txt.py` (la sección `CONFIGURACIÓN` de ese script, incluidas
`INCLUIR_SIEMPRE` y `EXCLUIR_SIEMPRE`). Así, los tokens del `.properties` coinciden exactamente con las claves del
`.txt`. Por eso los scripts deben estar en la misma carpeta (ver [Requisitos generales](#requisitos-generales)).

### Cómo correrlo

Desde la carpeta `SOPORTE`:

```bash
python3 properties_a_tokens.py <archivo.properties | directorio> [--unificado <unificado.txt>] [--servicio <nombre>]
```

- **Modifica el mismo archivo** y deja al lado un respaldo con el contenido anterior
  (`application.properties.bak`).
- Puedes pasarle el `.properties` o el directorio del servicio. Con un directorio, usa su
  `application.properties` o, si no está ahí, el de `src/main/resources`.
- Sin argumentos, pide la ruta por consola.

### Con el unificado (`--unificado`)

Toma los nombres de los tokens del `unificado.txt` que genera `unificar_txt.py`. Para cada variable:

1. Si en el unificado está **con el sufijo de este servicio**, usa ese nombre:
   `spring.profiles.active=#{SPRING_PROFILES_ACTIVE_OTRO_BACKEND}#`.
2. Si no, usa el nombre sin sufijo: `spring.datasource.erp.url=#{SPRING_DATASOURCE_ERP_URL}#`.
3. Si no está en el unificado de ninguna forma, **deja el valor como está** y lo avisa. Así no queda un token
   que no exista en el Variable Group.

El servicio se deduce de la carpeta del proyecto: en `otro-backend/src/main/resources` es
`otro-backend`. Tiene que coincidir con un servicio del encabezado del unificado; si no, el script
se detiene y te muestra los que hay. Para indicarlo a mano, usa `--servicio`.

Al terminar muestra qué variables quedaron con el sufijo del servicio.

### Ejemplos

Con el unificado, pasando el directorio del servicio:

```bash
python3 properties_a_tokens.py MiProyecto/otro-backend --unificado MiProyecto/PROPERTIES/unificado.txt
python3 properties_a_tokens.py MiProyecto/backend --unificado MiProyecto/PROPERTIES/unificado.txt
```

Sin unificado (los tokens llevan el nombre de la variable, sin sufijo):

```bash
python3 properties_a_tokens.py MiProyecto/backend/src/main/resources/application.properties
```

Al terminar muestra cuántos valores reemplazó:

```
70 valores reemplazados en MiProyecto/backend/src/main/resources/application.properties
```

### Orden recomendado

1. Corre primero `properties_a_txt.py` para sacar los valores reales al `.txt`.
2. Después corre `properties_a_tokens.py` para reemplazarlos por los tokens.

Si lo haces al revés, el `.txt` quedaría con los tokens (`SPRING_PROFILES_ACTIVE=#{SPRING_PROFILES_ACTIVE}#`)
en vez de los valores reales. Si pasa, recupera los valores del respaldo `.bak`.

### Qué tener en cuenta

- Solo cambia el valor. Los comentarios, las líneas vacías, el orden y las demás variables quedan igual.
- Si una variable ya tiene su token, no la toca. Si no queda nada por reemplazar, no modifica el archivo ni el
  `.bak`.
- Si vuelves a correrlo y hay variables nuevas por reemplazar (por ejemplo, porque
  agregaste claves a `INCLUIR_SIEMPRE`), el `.bak` se sobrescribe con la versión actual, que ya tiene tokens.
  Si necesitas los valores originales, guarda una copia del `.bak` antes.

---

## txt_a_vargroup.py

Sube a un **Variable Group de Azure DevOps** las variables del `.txt` (`CLAVE=VALOR`) que generan
`properties_a_txt.py` o `unificar_txt.py`. Usa el Azure CLI con la extensión `azure-devops`.

Tiene dos modos:

| Modo | Cómo se usa | Qué hace |
|---|---|---|
| **Subir a un grupo existente** (por defecto) | sin `--crear` | Sube las variables al grupo que le indicas. Si el grupo no existe, falla sin hacer nada. |
| **Crear un grupo nuevo** | `--crear` | Crea el grupo con el nombre que le indicas y le sube las variables. Si ya existe un grupo con ese nombre, falla sin hacer nada. |
| **Borrar y crear de nuevo** | `--crear --reemplazar` | Si el grupo ya existe, lo **borra** y lo crea de nuevo con las variables del `.txt`. Antes de borrar pide confirmación. |

Con cualquiera de los modos se puede agregar `--borrar-otros`: después de subir las variables, **borra todos los
demás Variable Groups del proyecto** menos el indicado (y los que pases en `--conservar`).

### Requisitos

- Azure CLI con la extensión `azure-devops` (ya están instalados en este computador).
- La organización por defecto configurada en el CLI. En este computador ya es `https://dev.azure.com/mi-organizacion`.
  Para verlo:

  ```bash
  az devops configure --list
  ```

- Haber iniciado sesión (`az login`) con un usuario que pueda administrar el Variable Group en ese proyecto.
  Para `--crear` y `--reemplazar` (crear y borrar grupos), el usuario necesita el rol **Administrator** en
  *Pipelines → Library* del proyecto.

### Ver los Variable Groups de un proyecto

Para saber qué nombre pasarle al script en `--grupo`, lista los Variable Groups del proyecto:

```bash
az pipelines variable-group list --project "<PROYECTO>" --query "[].{Id:id, Nombre:name}" --output table
```

Ejemplo:

```bash
az pipelines variable-group list --project "MiProyecto" --query "[].{Id:id, Nombre:name}" --output table
```

Muestra una tabla con el id y el nombre de cada grupo. Usa el nombre tal como aparece en la columna `Nombre`.

Otras variantes útiles:

```bash
# Solo los que empiezan por "backend" (acepta comodines)
az pipelines variable-group list --project "MiProyecto" --group-name "backend*" --query "[].{Id:id, Nombre:name}" --output table

# Ver las variables de un grupo (las secretas salen con valor null)
az pipelines variable-group variable list --project "MiProyecto" --group-id <ID> --output table
```

El comando toma la organización configurada por defecto en el CLI. Para usar otra, agrega
`--organization https://dev.azure.com/<ORGANIZACION>`.

### Cómo correrlo

Desde la carpeta `SOPORTE`:

```bash
python3 txt_a_vargroup.py <archivo.txt> --proyecto <PROYECTO> --grupo <VARIABLE_GROUP>
```

Sin argumentos, pide el archivo, el proyecto y el grupo por consola.

| Opción | Qué hace |
|---|---|
| `--proyecto`, `-p` | Proyecto de Azure DevOps. |
| `--grupo`, `-g` | Nombre del Variable Group. |
| `--simular` | Muestra qué haría, sin crear, borrar ni modificar nada. **Úsalo primero.** |
| `--crear` | Crea el Variable Group (no debe existir) y le sube las variables. |
| `--reemplazar` | Con `--crear`: si el grupo ya existe, lo **borra** y lo crea de nuevo. Pide escribir el nombre del grupo para confirmar. |
| `--borrar-otros` | Después de subir las variables, **borra todos los demás Variable Groups del proyecto**. Pide escribir el nombre del proyecto para confirmar. |
| `--conservar` | Con `--borrar-otros`: uno o más grupos que **no** se deben borrar (separados por espacio). |
| `--si` | Con `--reemplazar` o `--borrar-otros`: borra sin pedir confirmación. Úsalo con cuidado. |
| `--autorizar` | Con `--crear`: deja el grupo nuevo accesible para todos los pipelines. Sin esta opción, queda sin autorizar. |
| `--sobrescribir` | Actualiza el valor de las variables que ya existen en el grupo. Sin esta opción, se saltan. |
| `--sin-secretas` | Crea todas las variables como no secretas. |
| `--organizacion` | URL de otra organización, si no quieres usar la configurada por defecto. |

### Ejemplos

Ver qué haría, sin tocar nada:

```bash
python3 txt_a_vargroup.py salida/application.txt -p MiProyecto -g backend-vars-develop --simular
```

Subir las variables a un grupo que ya existe:

```bash
python3 txt_a_vargroup.py salida/application.txt -p MiProyecto -g backend-vars-develop
```

Actualizar también las que ya existen en ese grupo:

```bash
python3 txt_a_vargroup.py salida/application.txt -p MiProyecto -g backend-vars-develop --sobrescribir
```

Crear un grupo nuevo y subirle las variables:

```bash
python3 txt_a_vargroup.py MiProyecto/PROPERTIES/unificado.txt -p MiProyecto -g miproyecto-props-develop --crear --autorizar
```

Borrar el grupo existente y crearlo de nuevo (primero simúlalo):

```bash
python3 txt_a_vargroup.py MiProyecto/PROPERTIES/unificado.txt -p MiProyecto -g miproyecto-props-develop --crear --reemplazar --simular
python3 txt_a_vargroup.py MiProyecto/PROPERTIES/unificado.txt -p MiProyecto -g miproyecto-props-develop --crear --reemplazar
```

Antes de borrar, el script muestra cuántas variables tiene el grupo y pide escribir su nombre:

```
ATENCIÓN: se va a BORRAR el Variable Group 'miproyecto-props-develop' (id 42) del proyecto 'MiProyecto', con sus 70 variables.
  - No se puede deshacer. Los valores de las variables secretas se pierden.
  - El grupo nuevo tendrá otro id y sus permisos de pipelines se configuran de nuevo.
Escribe el nombre del grupo para confirmar (miproyecto-props-develop):
```

Si lo que escribes no coincide, se cancela sin borrar ni crear nada.

Dejar solo un grupo en el proyecto: subir las variables a `vars-develop` y borrar todos los demás (primero
simúlalo para ver la lista de lo que se borraría):

```bash
python3 txt_a_vargroup.py MiProyecto/PROPERTIES/unificado.txt -p MiProyecto -g vars-develop --borrar-otros --simular
python3 txt_a_vargroup.py MiProyecto/PROPERTIES/unificado.txt -p MiProyecto -g vars-develop --borrar-otros
```

Lo mismo, pero sin borrar algunos grupos que todavía se usan:

```bash
python3 txt_a_vargroup.py MiProyecto/PROPERTIES/unificado.txt -p MiProyecto -g vars-develop --borrar-otros \
  --conservar vars-qa vars-preprod vars-master
```

Antes de borrar, muestra la lista y pide escribir el nombre del proyecto:

```
ATENCIÓN: se van a BORRAR 3 Variable Groups del proyecto 'MiProyecto':
    - backend-vars-develop (id 3, 0 variables)
    - frontend-vars-develop (id 4, 1 variables)
    - miproyecto-vars-develop (id 2, 2 variables)
  - No se puede deshacer. Los valores de las variables secretas se pierden.
  - Los pipelines que usen esos grupos van a fallar hasta que se cambien.
Escribe el nombre del proyecto para confirmar (MiProyecto):
```

Al terminar muestra un resumen:

```
Resumen: 70 creadas, 0 actualizadas, 1 saltadas, 0 con error.
```

En la salida, `+` es una variable creada, `~` una actualizada, `=` una que ya existía y se saltó, y `!` un error.

### Variables secretas

Se crean como **secretas** (con candado en Azure) las variables cuyo nombre:

- tiene una parte (entre `_`) que contiene `PASSWORD`, `PASSWD`, `PWD`, `SECRET`, `ACCESS` o `CREDENTIAL`;
- tiene una parte que termina en `KEY` (`APPLICATIONKEY`);
- tiene una parte que es exactamente `TOKEN` (`ACCESS_TOKEN`, pero no `VALIDARTOKEN_ENDPOINT`).

Las reglas están al inicio del script (`PALABRAS_SECRETAS`, `TERMINACIONES_SECRETAS`, `PARTES_SECRETAS`).

El valor de las secretas se le pasa al Azure CLI por variable de entorno, no por la línea de comandos, para que no
quede visible en la lista de procesos.

### Qué tener en cuenta

- Los nombres de las variables en Azure no distinguen mayúsculas de minúsculas: `REPORTES_PASSWORD` y `reportes_password` son
  la misma variable.
- Si una variable da error, el script sigue con las demás y al final lista las que fallaron.
- Los valores se envían tal cual, incluidos los espacios al final. El script avisa cuando los encuentra.
- **`--reemplazar` borra solo el grupo que indicas en `--grupo`**, no otros grupos del proyecto.
- **`--borrar-otros` borra todos los demás grupos del proyecto**, de todos los servicios y de todos los ambientes
  (incluidos `vars-qa`, `vars-preprod`, `vars-master` y los de frontend), salvo los que pases en `--conservar`.
  Revisa siempre la lista con `--simular` antes.
  - Primero sube las variables. Si alguna da error, **no borra nada**.
  - Si cancelas la confirmación, las variables quedan subidas pero no se borra ningún grupo.
  - Si un grupo no se puede borrar (por ejemplo, por permisos), sigue con los demás y al final lista los que
    fallaron.
  - Los pipelines que todavía usen los grupos borrados van a fallar. Actualízalos antes con
    `actualizar_pipeline.py`.
- Al borrar y crear un grupo:
  - El grupo nuevo tiene **otro id**. Los pipelines YAML que lo usan por nombre (`- group: ...`) siguen
    funcionando; los releases clásicos que lo tenían enlazado por id hay que volver a enlazarlo.
  - Se pierden las variables que estaban en el grupo y no están en el `.txt`, incluidos los valores de las
    secretas.
  - Sin `--autorizar`, el grupo queda sin autorizar y el pipeline pide permiso la primera vez que lo usa. Se
    autoriza en *Pipelines → Library → el grupo → Pipeline permissions*.
- Para crear el grupo, Azure exige al menos una variable: se crea con la primera variable **no secreta** del
  `.txt`, para que ningún secreto quede visible ni un momento.

---

## vargroups_a_manifiestos.py

Reemplaza los tokens `#{VARIABLE}#` de los manifiestos de Kubernetes (`kubernetes.yaml`, `hpa.yaml` y `vpa.yaml`)
con los valores de los Variable Groups de Azure DevOps. **Modifica los archivos** del directorio que le indiques.

```yaml
# Antes                                  # Después
name: #{APP_NAME}#                       name: backend
namespace: #{NAMESPACE}#                 namespace: miproyecto
cpu: "#{CPU_REQUEST}#"                   cpu: "14m"
```

### Cómo funciona

1. Consulta los Variable Groups del proyecto y los lista.
2. Toma los valores en orden de jerarquía:
   1. el grupo **del servicio**: `<servicio>-vars-<ambiente>` (por ejemplo `backend-vars-develop`);
   2. el grupo **general del ambiente**: `<proyecto>-vars-<ambiente>` (por ejemplo `miproyecto-vars-develop`).

   Si una variable está en los dos, gana la del grupo del servicio.
3. Reemplaza los tokens en cada `.yaml` y muestra qué valor puso y de qué grupo salió.

Si el directorio se llama `manifiestos`, el servicio es el nombre de la carpeta de arriba (`backend`). Si no, es el
nombre del directorio. El ambiente por defecto es `develop`.

Los requisitos son los mismos que los de `txt_a_vargroup.py` (Azure CLI con `azure-devops` y sesión iniciada), y
los scripts tienen que estar en la misma carpeta (ver [Requisitos generales](#requisitos-generales)).

### Cómo correrlo

Desde la carpeta `SOPORTE`:

```bash
python3 vargroups_a_manifiestos.py <directorio> --proyecto <PROYECTO>
```

| Opción | Qué hace |
|---|---|
| `--proyecto`, `-p` | Proyecto de Azure DevOps. |
| `--ambiente`, `-a` | Ambiente para armar los nombres de los grupos. Por defecto `develop`. |
| `--servicio`, `-s` | Nombre del servicio, si no es el de la carpeta. |
| `--grupo-servicio` | Nombre exacto del grupo del servicio, si no sigue la convención `<servicio>-vars-<ambiente>`. |
| `--grupo-general` | Nombre exacto del grupo general, si no sigue la convención `<proyecto>-vars-<ambiente>`. |
| `--simular` | Muestra qué reemplazaría, sin modificar los archivos. |
| `--organizacion` | URL de otra organización, si no quieres usar la configurada por defecto. |

### Ejemplos

Ver qué reemplazaría, sin tocar nada:

```bash
python3 vargroups_a_manifiestos.py MiProyecto/backend/manifiestos -p MiProyecto --simular
```

Reemplazar en los archivos:

```bash
python3 vargroups_a_manifiestos.py MiProyecto/backend/manifiestos -p MiProyecto
```

Con nombres de grupos que no siguen la convención:

```bash
python3 vargroups_a_manifiestos.py MiProyecto/backend/manifiestos -p MiProyecto \
  --grupo-servicio backend-vars-develop --grupo-general miproyecto-vars-develop
```

### Qué tener en cuenta

- Los tokens que no están en ninguno de los dos grupos **se dejan igual** y se listan al final (por ejemplo
  `#{TAG_IMAGEN}#`, que lo pone el pipeline al construir la imagen).
- Estos campos **siempre quedan como `#{REPLICAS}#`**, sin importar qué tenga la plantilla (por ejemplo
  `#{MIN_REPLICAS}#` o un número):
  - `replicas:` en `kubernetes.yaml`
  - `minReplicas:` en `hpa.yaml`

  Se configuran en `CAMPOS_FIJOS` al inicio del script.
- `#{REPLICAS}#` **nunca se reemplaza**, aunque esté en los Variable Groups: se deja como token. Para agregar
  otros tokens que no se deban tocar, inclúyelos en `NO_REEMPLAZAR` al inicio del script.
- Las variables **secretas** tampoco se reemplazan: el Azure CLI no entrega su valor. Se dejan como token y se
  listan al final.
- Solo cambia los tokens. Las comillas, la indentación y el resto del archivo quedan igual. Por ejemplo,
  `value: "#{PORT}#"` queda `value: "3600"`. Las comillas son necesarias: en Kubernetes el `value` de una variable
  de entorno tiene que ser texto, y `value: 3600` sin comillas hace fallar el `kubectl apply`.
- Si uno de los dos grupos no existe, avisa y usa solo el otro. Si no existe ninguno, falla sin modificar nada.
- Los manifiestos están en git: si algo queda mal, recupera la versión con tokens con
  `git checkout -- manifiestos/`.

---

## actualizar_pipeline.py

Modifica un `azure-pipeline.yaml` para que use los Variable Groups en vez de los archivos seguros:

1. Deja la sección `variables:` igual que en `MiProyecto/backend/azure-pipeline.yaml`, con un solo Variable Group
   por rama (`vars-<rama>`):

   ```yaml
   variables:
   - name: system.debug
     value: false
   - ${{ if eq(variables['Build.SourceBranchName'], 'develop') }}:
     - group: "vars-develop"
   - ${{ if eq(variables['Build.SourceBranchName'], 'qa') }}:
     - group: "vars-qa"
   - ${{ if eq(variables['Build.SourceBranchName'], 'preprod') }}:
     - group: "vars-preprod"
   - ${{ if eq(variables['Build.SourceBranchName'], 'master') }}:
     - group: "vars-master"
   ```

2. Borra los bloques `compileSecureFiles` y `deploySecureFiles` de los parámetros del stage.

El resto del archivo queda igual: `trigger`, `resources`, `stages` y los demás parámetros (por ejemplo
`compileFlags`). Respeta la sangría que use el archivo (listas a 0 o a 2 espacios) y sus saltos de línea.

### Cómo correrlo

Desde la carpeta `SOPORTE`:

```bash
python3 actualizar_pipeline.py <azure-pipeline.yaml | directorio> [--simular]
```

- Puedes pasarle el archivo o el directorio del servicio. Con un directorio, busca ahí `azure-pipeline.yaml` (o
  `.yml`, o `azure-pipelines.*`).
- **Modifica el mismo archivo.** No deja `.bak`: los pipelines están en git, así que puedes revisar el cambio con
  `git diff` y deshacerlo con `git checkout -- azure-pipeline.yaml`.
- `--simular` muestra el diff de lo que cambiaría, sin modificar el archivo.

### Ejemplos

```bash
# Ver qué cambiaría
python3 actualizar_pipeline.py MiProyecto/otro-backend --simular

# Aplicar el cambio
python3 actualizar_pipeline.py MiProyecto/otro-backend
```

Al terminar muestra los grupos que había antes y después, y los bloques que borró:

```
Sección variables:
  antes:   miproyecto-vars-develop, otro-backend-vars-develop, ...
  después: vars-develop, vars-qa, vars-preprod, vars-master

Bloques borrados:
  compileSecureFiles:
      - otro-miproyecto-${{ variables['Build.SourceBranchName'] }}.properties: "src/main/resources/application.properties"
  deploySecureFiles:
      - ...
```

### Qué tener en cuenta

- **Reemplaza todos los grupos que había** por `vars-<rama>`. Los grupos anteriores (por ejemplo
  `miproyecto-vars-develop` y `<servicio>-vars-develop`) dejan de usarse en ese pipeline, así que las variables
  que tenían deben estar en `vars-<rama>`.
- Si alguno de los archivos seguros que borra **no es** `application.properties` (por ejemplo,
  `config/firma.properties` o `application.yml`), el script avisa con `ATENCIÓN`. Esos archivos dejan de
  llegar al build, y si el servicio los necesita hay que resolverlos de otra forma antes de correr el pipeline.
- Si el archivo ya está como debe quedar, no lo modifica.
- Antes de guardar, valida que el resultado sea un YAML válido. Si no lo es, no modifica el archivo.
- Las ramas y el nombre de los grupos se configuran al inicio del script, en `RAMAS` y `NOMBRE_GRUPO`.

---

## Flujo completo

Para varios servicios que comparten Variable Group (por ejemplo `backend` y `otro-backend`). Corre
cada paso primero con `--simular` cuando el script lo tenga.

```bash
# 1. Sacar las variables de ambiente de cada servicio a su .txt
python3 properties_a_txt.py MiProyecto/backend/src/main/resources/application.properties \
  MiProyecto/PROPERTIES/backend-despues-del-cambio/properties.txt
python3 properties_a_txt.py MiProyecto/otro-backend/src/main/resources/application.properties \
  MiProyecto/PROPERTIES/otro-backend-despues-del-cambio/properties.txt

# 2. Unificarlas en un solo .txt (las que chocan quedan con el sufijo del servicio)
python3 unificar_txt.py MiProyecto/PROPERTIES

# 3. Subirlas al Variable Group del ambiente (vars-<rama>, el que usa el pipeline)
#    - si el grupo ya existe:
python3 txt_a_vargroup.py MiProyecto/PROPERTIES/unificado.txt -p <PROYECTO> -g vars-develop
#    - si hay que crearlo:
python3 txt_a_vargroup.py MiProyecto/PROPERTIES/unificado.txt -p <PROYECTO> -g vars-develop --crear --autorizar

# 4. Reemplazar los valores de cada .properties por los tokens, según el unificado
python3 properties_a_tokens.py MiProyecto/backend --unificado MiProyecto/PROPERTIES/unificado.txt
python3 properties_a_tokens.py MiProyecto/otro-backend --unificado MiProyecto/PROPERTIES/unificado.txt

# 5. Dejar el pipeline de cada servicio usando vars-<rama> y sin secure files
python3 actualizar_pipeline.py MiProyecto/backend
python3 actualizar_pipeline.py MiProyecto/otro-backend

# 6. Llenar los manifiestos de Kubernetes de cada servicio con los Variable Groups
python3 vargroups_a_manifiestos.py MiProyecto/backend/manifiestos -p <PROYECTO>
python3 vargroups_a_manifiestos.py MiProyecto/otro-backend/manifiestos -p <PROYECTO>

# 7. Borrar los .bak: tienen las contraseñas en texto plano y quedan dentro del repo de cada servicio
rm MiProyecto/backend/src/main/resources/application.properties.bak
rm MiProyecto/otro-backend/src/main/resources/application.properties.bak
```

Los `.txt` y el `unificado.txt` también tienen las contraseñas en texto plano: guárdalos fuera de git y bórralos
cuando ya no los necesites.
