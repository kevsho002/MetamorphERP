# Metamorph ERP — HCM

Monolito modular: **React 18 (Vite)** + **Django 6.1 / Django REST Framework** + **SQL Server**.
En producción Django sirve también el build de React (un solo despliegue, mismo origen, sin CORS).

| Fase | Alcance |
|------|---------|
| 1 | Esqueleto, esquema de persistencia (Empleados, Expediente digital, Asistencias, Planillas), health check |
| 2 | Seguridad: `CustomUser` (AbstractUser), RBAC por rol, sesión + CSRF, CRUD de usuarios, reseteo seguro de contraseñas |
| 3 | Gestión de empleados: alta individual y masiva (CSV/Excel/JSON), plantillas JSON por país y fecha de efectividad, atributos dinámicos (EAV), reporte en lenguaje natural, administración en `/admin/` |
| 4 | Frontend React de empleados: lista con filtros, formulario dinámico de alta/edición según la plantilla del país, carga masiva con vista previa y reporte por fila, control de roles en la interfaz; edición por API (PATCH) |
| 5 | Expediente digital dinámico (pestañas/secciones por plantilla y fecha de efectividad), fotografía y documentos PNG/JPG/JPEG con visor; cuenta Metamorph vinculada desde el alta; `/admin/` reservado a sesión, cliente web y auditoría |

```
MetamorphERP/
├── database/                       # Esquema de DOMINIO SQL-first (fuente de verdad)
│   ├── deploy.ps1                  # Ejecuta scripts en orden (idempotentes)
│   └── scripts/
│       ├── 001_schemas_and_core_catalogs.sql
│       ├── 010_core_employee_code.sql       # ID corporativo por país (SP + Luhn)
│       ├── 020_hcm_employees_and_digital_files.sql
│       ├── 030_wfm_attendance_ingestion.sql
│       ├── 040_fin_payroll_deductions.sql
│       ├── 050_core_cost_center.sql         # Fase 2: centros de costos
│       ├── 060_hcm_employee_cost_center.sql # Fase 3: Employee.CostCenterId con FK compuesta (mismo país)
│       ├── 090_seed_reference_data.sql
│       └── 095_hcm_digital_file_media.sql   # Fase 5: documentos sensibles, PROFILE_PHOTO, solo PNG/JPEG
├── backend/
│   ├── manage.py
│   ├── config/                     # settings (.env), urls, wsgi/asgi
│   ├── apps/
│   │   ├── common/                 # core: países, secuencia, centros de costos; helpers de campos
│   │   ├── hcm/                    # Empleados, Expediente digital; services/employee_code.py
│   │   ├── wfm/                    # Asistencias, downtimes, ingesta paramétrica
│   │   ├── payroll/                # fin: planillas y retenciones
│   │   ├── accounts/               # Fase 2: CustomUser, roles/RBAC, API de usuarios y sesión
│   │   │   ├── models.py           #   CustomUser(AbstractUser)
│   │   │   ├── roles.py            #   Roles + matriz de permisos (fuente única)
│   │   │   ├── permissions.py      #   Permisos DRF (deny by default)
│   │   │   ├── services.py         #   Reglas: reseteo, roles, activación, último admin
│   │   │   ├── serializers.py · views.py · urls.py · admin.py
│   │   │   └── migrations/         #   0001 tabla; 0002 FKs hacia hcm/core
│   │   ├── employees/              # Fase 3: alta de empleados con modelo dinámico
│   │   │   ├── models.py           #   AttributeDefinition, EmployeeTemplate (JSON), EmployeeAttributeValue (EAV), ImportBatch/Row
│   │   │   ├── schema.py           #   estructura de la plantilla, validación y conversión de tipos
│   │   │   ├── validation.py       #   validación de una fila/formulario contra la plantilla del país
│   │   │   ├── services.py         #   escritura: Employee + ID corporativo + expediente + EAV
│   │   │   ├── parsers.py · batch.py   # lectura CSV/XLSX/JSON · motor batch + reporte en lenguaje natural
│   │   │   ├── updates.py          #   Fase 4: edición (PATCH) con las mismas reglas + ROWVERSION
│   │   │   ├── digital_files.py    #   Fase 5: expediente dinámico, checklist y versiones de documentos
│   │   │   ├── media.py            #   Fase 5: validación segura de imágenes (firma + Pillow) y foto normalizada
│   │   │   ├── management/commands/purge_orphan_media.py
│   │   │   ├── serializers.py · views.py · urls.py · admin.py
│   │   │   └── migrations/         #   0001 tablas; 0002 FKs a core/hcm; 0003 semilla (atributos + plantillas SV/GT/MX/CO); 0004 layout + documentos
│   │   ├── system/                 # Fase 5: parámetros de sesión, cliente web, sesiones activas, auditoría
│   │   │   ├── models.py           #   PlatformSettings (fila única), UserSession, AuditEvent
│   │   │   ├── middleware.py       #   inactividad, duración máxima, modo mantenimiento
│   │   │   ├── audit.py · sessions.py · signals.py · policy.py
│   │   │   └── admin.py · views.py #   /admin/ de plataforma · GET /system/client-config/
│   │   ├── health/                 # GET /api/v1/health, /api/v1/health/db
│   │   └── web/                    # SPA (index.html), 404 JSON en /api, fallo CSRF en JSON
│   └── tests/                      # pytest-django contra test_MetamorphERP
└── frontend/src/
    ├── auth/                       # AuthContext (sesión), LoginPage, ChangePasswordPage
    ├── services/apiClient.js       # fetch + cookie de sesión + X-CSRFToken
    ├── app/router.jsx              # registro de módulos -> rutas + menú (filtrado por permiso)
    ├── app/ClientConfigContext.jsx # Fase 5: mantenimiento, aviso general y tiempos de sesión (del /admin/)
    ├── components/layout/          # AppLayout, SessionWatcher (cierre por inactividad), AnnouncementBar
    ├── styles/global.css · hcm.css · dossier.css # tokens corporativos · Fase 4 · Fase 5
    └── modules/
        ├── hcm/                    # Fase 4
        │   ├── api.js              #   endpoints de empleados, plantillas y cargas
        │   ├── hooks/              #   useCatalogs, useApplicableTemplate
        │   ├── lib/formSpec.js     #   secciones, validación local, armado del payload
        │   ├── components/         #   DynamicField, FileDropzone, ImportReport, Feedback, TemplateInfo, StatusBadge
        │   │                       #   Fase 5: DossierTab, DocumentsPanel, ImageViewer, ImageUploadDialog,
        │   │                       #   EmployeePhoto, AccountOptions, UserAccountPanel, TemporaryPassword, HistoryPanel
        │   └── pages/              #   lista, expediente, alta/edición, carga masiva, historial, expedientes digitales
        └── {wfm,payroll,system}/
```

## Persistencia: quién crea qué

| Tablas | Origen | En Django |
|--------|--------|-----------|
| `core.*`, `hcm.*`, `wfm.*`, `fin.*` (20) | `database/scripts` (SQL-first) | modelos `managed = False` |
| `dbo.accounts_customuser`, `auth_*`, `django_session`, `django_admin_log`, `django_content_type` | migraciones de Django | modelos administrados |
| `dbo.hcm_attribute_definition`, `hcm_employee_template`, `hcm_employee_attribute_value`, `hcm_import_batch`, `hcm_import_batch_row` | migraciones de Django (Fase 3) | modelos administrados |
| `dbo.sys_platform_settings`, `sys_user_session`, `sys_audit_event` | migraciones de Django (Fase 5) | modelos administrados |

`accounts.0002` y `employees.0002` crean FKs reales hacia tablas SQL-first (`hcm.Employee`, `core.catCountry`,
`core.catCostCenter`). Por eso **`deploy.ps1` va antes de `migrate`**.

| Concepto | Tabla |
|----------|-------|
| Empleados | `hcm.Employee` (`EmployeeCode` lo genera `core.usp_GenerateEmployeeCode`) |
| ExpedientesDigitales | `hcm.DigitalFile` (+ `DigitalFileDocument`, `catDocumentType`) |
| Asistencias | `wfm.Attendance` (+ `AttendanceDowntime`, ingesta paramétrica) |
| Planillas | `fin.Payroll` (+ `PayrollDetail`, `PayrollDeduction`, `catDeductionType`, `DeductionBracket`) |
| Usuarios | `dbo.accounts_customuser` (rol, ID corporativo, centro de costos) |
| Centros de costos | `core.catCostCenter` (semilla `{PAÍS}-ADM/RRHH/OPS/TI`, valores de referencia) |

### ID corporativo

`{IdPrefix}-{AAAA}-{NNNNNN}-{D}` → `SV-2026-000123-7`. Correlativo por país + año de ingreso, dígito
Luhn (letras A=10…Z=35), reserva atómica dentro de la transacción del alta (sin huecos).

## Seguridad (Fase 2)

**Roles** (`apps/accounts/roles.py`): `ADMIN` Administrador · `HR` Recursos Humanos · `WFM` Workforce Management · `EMPLOYEE` Empleado.

| Permiso | ADMIN | HR | WFM | EMPLOYEE |
|---------|:-----:|:--:|:---:|:--------:|
| users.view / create / update / assign_role / reset_password / deactivate | ✔ | ✔ ¹ | | |
| hcm.view / hcm.manage | ✔ / ✔ | ✔ / ✔ | ✔ / – | |
| wfm.view / wfm.manage | ✔ / ✔ | ✔ / – | ✔ / ✔ | |
| payroll.view / payroll.manage | ✔ / ✔ | ✔ / ✔ | | |
| system.status | ✔ | | | |
| self.view | ✔ | ✔ | ✔ | ✔ |

¹ RRHH solo administra cuentas `HR`, `WFM` y `EMPLOYEE`: nunca crea, edita, resetea ni otorga `ADMIN`.

Reglas adicionales: nadie cambia su propio rol ni se desactiva a sí mismo; solo un superusuario modifica a otro
superusuario; no se puede dejar el sistema sin administradores activos; `HR`/`WFM`/`EMPLOYEE` exigen un ID
corporativo de empleado existente y no retirado (una cuenta por empleado); el centro de costos debe ser del país
del empleado; la eliminación es baja lógica (`is_active = false`).

**Sesión**: cookie `HttpOnly` + `SameSite=Lax` (+ `Secure` en producción), CSRF obligatorio en métodos no seguros,
login con límite de intentos (`10/min`), mensaje de error genérico, sesión de 8 h. 401 = sin sesión, 403 = sin permiso.

**Contraseñas**: PBKDF2 (Django), mínimo 12 caracteres + validadores estándar. Las contraseñas iniciales y los
reseteos las **genera el servidor** (16 caracteres, CSPRNG), se muestran una única vez (`Cache-Control: no-store`),
invalidan las sesiones abiertas del usuario y obligan a cambiarla: hasta entonces la API responde 403 salvo
`/auth/me`, `/auth/password/change` y `/auth/logout`.

### Endpoints (`/api/v1`)

| Método | Ruta | Permiso |
|--------|------|---------|
| GET | `/auth/csrf/` | público (emite cookie CSRF) |
| POST | `/auth/login/` · `/auth/logout/` | público · sesión |
| GET | `/auth/me/` | sesión (incluye `permissions`) |
| POST | `/auth/password/change/` | sesión |
| GET | `/roles/` | users.view |
| GET / POST | `/users/` (`?search=&role=&is_active=&cost_center=`) | users.view / users.create |
| GET / PATCH / PUT | `/users/{id}/` | users.view / users.update |
| DELETE | `/users/{id}/` (baja lógica) | users.deactivate |
| POST | `/users/{id}/role/` | users.assign_role |
| POST | `/users/{id}/reset-password/` | users.reset_password |
| POST | `/users/{id}/activate/` · `/deactivate/` | users.deactivate |
| GET | `/health` · `/health/db` | público |

Admin de Django en `/admin/` (acceso derivado del rol `ADMIN`; ver Fase 5 para su alcance).

## Puesta en marcha

```powershell
# 1. Esquema de dominio (Windows auth contra localhost por defecto)
.\database\deploy.ps1                       # -Server / -Database / -User / -Password opcionales

# 2. Backend
cd backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env
python manage.py migrate                    # tablas de Django + FKs hacia hcm/core
python manage.py createsuperuser            # primer administrador (rol ADMIN)
python manage.py runserver                  # http://localhost:8000
pytest                                      # crea test_MetamorphERP desde database/scripts + migraciones

# 3. Frontend (desarrollo, proxy /api -> :8000)
cd frontend
npm install
npm run dev                                 # http://localhost:5173

# Despliegue unificado: npm run build; python manage.py collectstatic
#   -> Django sirve frontend/dist en "/" y los estáticos del admin vía WhiteNoise.
#   Producción: APP_ENV=production, DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, HTTPS.
```

## Gestión de empleados (Fase 3)

**Locación estricta.** Todo cuelga de `core.catCountry`: el empleado (`CountryId`), su plantilla (`country_id`, FK real)
y su centro de costos. `hcm.Employee (CostCenterId, CountryId)` tiene FK **compuesta** hacia
`core.catCostCenter (CostCenterId, CountryId)`: la BD rechaza un centro de costos de otro país.

**Plantillas por país y fecha de efectividad** (`hcm_employee_template.schema`, JSON validado al guardar):

```json
{
  "core_fields": {"national_id_type": {"default": "DUI", "choices": ["DUI", "PASAPORTE"]},
                  "national_id_number": {"patterns_by_type": {"DUI": {"pattern": "^\\d{8}-\\d$", "example": "01234567-8"}}},
                  "cost_center": {"required": true}, "work_email": {"recommended": true}},
  "attributes":  {"social_security_number": {"label": "Número de afiliación ISSS", "required": true, "pattern": "^\\d{9}$"},
                  "pension_fund": {"label": "AFP", "required": true, "choices": ["CONFIA", "CRECER"]}},
  "rules":       {"min_age": 18, "min_base_salary": "408.80", "max_future_hire_days": 90}
}
```

* La plantilla aplicable es la **activa con mayor `effective_date` ≤ fecha de ingreso** del empleado. Un cambio
  normativo = nueva versión con nueva fecha (acción del admin «Clonar como nueva versión»); una plantilla que ya
  validó empleados queda bloqueada para no reescribir la historia.
* Reglas por campo: `label, required, recommended, default, pattern, example, pattern_message, patterns_by_type,
  choices, min, max, min_length, max_length, transform (upper|lower|strip_spaces), help`. Los campos `NOT NULL` de
  `hcm.Employee` no pueden volverse opcionales.
* **EAV**: `hcm_attribute_definition` (catálogo: código y tipo STRING/INTEGER/DECIMAL/DATE/BOOLEAN/CHOICE/EMAIL) +
  `hcm_employee_attribute_value` (valor canónico por empleado y atributo, con la plantilla que lo validó).
* Semilla (migración `0003`): 12 atributos y una plantilla base por país vigente desde 2000-01-01.
  **Patrones de documentos, salario mínimo y edades son valores de referencia**: validarlos con RRHH/Legal.

**Alta individual y masiva** (misma validación, mismos mensajes):

* Cada fila → país (código, nombre o id) → plantilla vigente → campos base + atributos del país → reglas cruzadas
  (edad mínima, ingreso futuro, salario mínimo de referencia, centro de costos del mismo país, documento duplicado
  en BD o en el archivo, ID corporativo: formato `{PAÍS}-AAAA-NNNNNN-D`, dígito Luhn y prefijo del país).
* Encabezados en inglés o español (`pais`, `primer_nombre`, `fecha_ingreso`, `salario`, `centro_costos`…) y atributos
  por código (`tax_id`) o por la etiqueta del país (`NIT`, `RFC`, `EPS`). Fechas `AAAA-MM-DD` o `DD/MM/AAAA`.
  Opciones sin distinguir mayúsculas ni tildes («Confía» = `CONFIA`).
* Escritura: `core.usp_GenerateEmployeeCode` (ID corporativo) + `hcm.Employee` + `hcm.DigitalFile` (expediente
  abierto) + valores EAV, en una transacción.
* Atomicidad: `COUNTRY` (por defecto, **todo o nada por país**: un error en una fila de Guatemala no crea ningún
  empleado de Guatemala, pero sí los de otros países) o `ROW` (fila por fila). `dry_run` ejecuta todo —incluida la
  reserva del ID— y revierte: valida también las reglas de la BD sin consumir correlativos.
* Archivos: CSV (UTF-8 o ANSI; separador `,` `;` TAB `|`), Excel `.xlsx` (primera hoja), JSON; máx. 5 MB / 5000 filas.
* **Reporte**: resumen del lote en lenguaje natural + estado por fila `CREATED | VALID | ERROR | NOT_APPLIED` con
  retroalimentación, p. ej. *«Fila 3 (Guatemala): no se creó el empleado por 2 errores: (1) Falta el campo
  obligatorio «NIT» exigido por la plantilla «Guatemala — plantilla base» (vigente desde 01/01/2000) de Guatemala.
  (2) «Número de documento de identidad (DPI)» con valor «123» no tiene el formato esperado; ejemplo válido:
  1234567890101.»*

| Método | Ruta (`/api/v1`) | Permiso |
|--------|------------------|---------|
| GET | `/hcm/employees/` (`?country=&status=&cost_center=&search=&ordering=&page=&page_size=`) · `/hcm/employees/{ID}/` | hcm.view (salario y atributos sensibles solo con payroll.view) |
| PATCH | `/hcm/employees/{ID}/` (edición; 400 con errores explicados, 409 si otro usuario lo modificó) | hcm.manage |
| POST | `/hcm/employees/{ID}/validate/` (valida una edición sin guardar) | hcm.manage |
| GET | `/hcm/catalogs/` (países, centros de costos, estados, géneros, frecuencias de pago) | hcm.view |
| POST | `/hcm/employees/` (formulario individual: 201, o 400 con errores explicados) | hcm.manage |
| POST | `/hcm/employees/validate/` (valida sin guardar) | hcm.manage |
| GET | `/hcm/employee-templates/` · `/{id}/` (incluye `form`) · `/applicable/?country=SV&date=AAAA-MM-DD` | hcm.view |
| GET | `/hcm/employee-templates/{id}/csv/` (CSV de ejemplo) | hcm.manage |
| GET | `/hcm/attributes/` | hcm.view |
| POST | `/hcm/employee-imports/` multipart `file` (+ `atomicity`, `dry_run`) o JSON `{"rows": [...]}` | hcm.manage |
| GET | `/hcm/employee-imports/` · `/{id}/?row_status=ERROR` | hcm.manage |

**`/admin/`** (desde la Fase 5, ver abajo): plantillas (editor JSON indentado con validación, vista previa del
formulario resultante, enlace al CSV de ejemplo, clonado de versiones), atributos dinámicos, países (solo lectura) y
centros de costos. Empleados, valores EAV y cargas masivas se gestionan solo en la aplicación.

## Frontend de empleados (Fase 4)

| Ruta (React) | Pantalla | Permiso |
|--------------|----------|---------|
| `/hcm/employees` | Lista con búsqueda y filtros por país, estado (activos / inactivos / suspendidos / retirados) y centro de costos; orden y paginación. Los filtros viven en la URL. | hcm.view |
| `/hcm/employees/:ID` | Ficha: datos base, vínculo laboral y «Datos requeridos por {país}» con las etiquetas de su plantilla | hcm.view |
| `/hcm/employees/new` | Alta: se elige país y fecha de ingreso → se consulta la plantilla vigente y se renderizan sus campos (obligatorios, recomendados, patrones con ejemplo, listas de opciones, centros de costos del país) | hcm.manage |
| `/hcm/employees/:ID/edit` | Edición con las mismas reglas; país e ID corporativo bloqueados; estado laboral y fecha de retiro | hcm.manage |
| `/hcm/employees/import` | Carga masiva: arrastrar/soltar CSV/XLSX/JSON, atomicidad, **«Solo validar (vista previa)»** activado por defecto, luego «Aplicar carga»; CSV de ejemplo por país | hcm.manage |
| `/hcm/employees/imports` · `/imports/:id` | Historial de cargas y reporte de cada lote | hcm.manage |

* **Validación en dos niveles.** El navegador valida al salir de cada campo (obligatorios, formato del documento según
  su tipo, longitudes, rangos, edad mínima del país) para dar retroalimentación inmediata; «Validar sin guardar» y
  «Guardar» usan el backend, cuyos errores se muestran junto a cada campo y como texto en lenguaje natural.
* **Reporte de carga.** Resumen del lote, indicadores (filas, creadas/válidas, advertencias, errores, no aplicadas),
  observaciones del archivo, pestañas por estado y una tarjeta por fila con la retroalimentación del servidor, la lista
  de errores/advertencias con su campo y los datos recibidos. Se puede descargar como CSV.
* **Aplicar después de la vista previa.** «Aplicar carga» solo se habilita para el mismo archivo y la misma atomicidad
  que se validaron, y pide confirmación indicando cuántos empleados se crearán.
* **RBAC en la interfaz.** El menú y las rutas se filtran con `permissions` de `/auth/me/` (WFM ve la lista y la ficha,
  sin botones de alta/edición/carga). Sin `payroll.view` no se muestran el salario ni los atributos marcados como
  sensibles (NIT, NSS, NUP, cuenta bancaria…): la API no los envía y la ficha muestra «Restringido». La autorización
  real siempre la aplica la API (403).
* **Edición segura.** PATCH conserva lo no enviado; `""` borra un dato opcional. El país no se edita (el ID corporativo
  depende de él: un traslado es retiro + alta). `row_version` (ROWVERSION) evita pisar cambios de otra persona (409).
  Los atributos que la plantilla vigente ya no usa se conservan.

```powershell
cd frontend
npm install
npm run lint    # ESLint (reglas de React y hooks)
npm run build   # verificación de compilación + build para el despliegue unificado
npm run dev     # desarrollo en :5173 con proxy /api -> :8000 (python manage.py runserver)
```

## Expediente digital y cuenta vinculada (Fase 5)

### Expediente dinámico (`/hcm/employees/:ID`)

* **Pestañas y secciones desde la plantilla JSON** del país (`layout`, validado al guardar la plantilla en `/admin/`).
  Sin `layout` se usa un diseño por defecto; los campos que el layout no ubique se agregan en «Otros datos» (nada se
  oculta). La migración `employees.0004` agregó `layout` y `documents` a las plantillas base SV/GT/MX/CO.
* **Fecha de efectividad.** Por defecto se usa la plantilla vigente a la **fecha de ingreso** (la que validó el alta).
  «Otra fecha» / «Hoy» (`?as_of=AAAA-MM-DD`) evalúa la versión vigente a esa fecha: muestra sus pestañas, marca los
  obligatorios nuevos que faltan («Pendiente») y agrupa en «Otras versiones» los datos que esa versión ya no pide.
  Cada valor EAV indica con qué versión de la plantilla se registró.
* **Documentos** (`documents` de la plantilla + `hcm.catDocumentType`): checklist con obligatoriedad y nombre local
  (p. ej. «DUI», «DPI», «RUT»), estado (vigente, por vencer ≤ 30 días, vencido, pendiente), versiones con historial,
  fecha de emisión/vencimiento y avance de obligatorios. «Expedientes digitales» (`/hcm/digital-files`) lista el avance
  de todos los empleados.
* **Imágenes PNG/JPG/JPEG** (foto de perfil y documentos oficiales):
  - Validación por extensión, firma binaria y decodificación completa con Pillow (rechaza archivos disfrazados,
    corruptos, truncados y «bombas» de descompresión), tamaño máximo configurable y `CHECK` de tipo MIME en la BD.
  - Almacenamiento privado en `PRIVATE_MEDIA_ROOT` (fuera de static/WhiteNoise), con nombre aleatorio. El archivo solo
    se entrega por la API tras verificar sesión y permisos, con `nosniff`, `CSP sandbox` y sin caché si es sensible.
  - Cada carga es una versión nueva con SHA-256 (se rechaza la idéntica a la vigente). Los documentos oficiales se
    guardan con sus bytes originales. La foto se normaliza (orientación, máx. 800 px, JPEG **sin metadatos EXIF/GPS**).
  - Los documentos sensibles (identidad, tributarios, bancarios, médicos, antecedentes) requieren `payroll.view`, como
    los atributos EAV sensibles: WFM ve que existen, pero no su contenido. Cada consulta o descarga queda auditada.
  - `python manage.py purge_orphan_media [--delete]` limpia archivos sin registro (p. ej. tras un rollback).
* **Visor interactivo**: zoom (rueda, +/−, doble clic), arrastre, giro, ajuste, navegación ← → entre documentos,
  descarga y teclado (Esc). Vista previa local antes de subir.

### Cuenta Metamorph vinculada

* En el alta, con `users.create` (Administrador y RRHH): **«¿Desea crear un perfil de usuario Metamorph vinculado a
  este empleado?»**, con el rol (solo los que el usuario puede otorgar) y un usuario opcional (por defecto
  `nombre.apellido`, sin tildes y único).
* El backend crea el empleado y la cuenta en **la misma transacción**. La cuenta queda enlazada por FK al ID
  corporativo (`accounts_customuser.employee_code` → `hcm.Employee.EmployeeCode`) y hereda nombre, correo laboral y
  centro de costos; su contraseña temporal es de un solo uso y obliga a cambiarla. Si la cuenta no es válida (usuario
  tomado, rol no permitido), no se crea nada ni se consume el correlativo. «Validar sin guardar» muestra el usuario
  que se asignará.
* En el expediente, la pestaña «Cuenta Metamorph» crea la cuenta de un empleado existente, cambia el rol, resetea la
  contraseña y la activa o desactiva. **Retirar** a un empleado desactiva su cuenta y cierra sus sesiones.

### `/admin/`: solo plataforma y parametrización

* **Parámetros de sesión**: cierre por inactividad, aviso previo con cuenta regresiva, duración máxima y sesiones
  simultáneas por usuario. Los aplica el middleware del servidor (401 `session_expired`) y el navegador.
* **Control del cliente web**: modo mantenimiento (solo los administradores operan; el resto ve el mensaje), aviso
  general con nivel, tamaño máximo de imágenes. Se publica en `GET /system/client-config/`.
* **Sesiones de usuario**: quién está conectado, desde qué IP y navegador; acción «Cerrar las sesiones seleccionadas».
* **Registro de auditoría** (`sys_audit_event`, solo lectura incluso para superusuarios, exportable a CSV). Registra
  inicios de sesión (también fallidos y bloqueados), cierres y expiraciones; cuentas (alta, rol, reseteo, activación);
  altas y ediciones de empleados; cargas masivas; documentos subidos, consultados y descargados; y cambios de
  parámetros.
* Se retiraron del admin los usuarios, grupos, empleados, valores EAV y cargas masivas, para evitar asignaciones
  manuales fuera de las reglas de negocio. Se mantienen plantillas, atributos, países y centros de costos
  (parametrización sin pantalla en React todavía). Las cuentas técnicas de superusuario se crean con
  `python manage.py createsuperuser`.

### Endpoints nuevos (`/api/v1`)

| Método | Ruta | Permiso |
|--------|------|---------|
| GET | `/system/client-config/` | público |
| POST | `/hcm/employees/` con `user_account: {create, role, username}` | hcm.manage + users.create |
| GET | `/hcm/employees/{ID}/digital-file/?as_of=` | hcm.view |
| GET / POST | `/hcm/employees/{ID}/documents/` (`?type=`; multipart `file`, `document_type`, `issue_date`, `expiry_date`) | hcm.view / hcm.manage |
| GET / POST | `/hcm/employees/{ID}/photo/` | hcm.view / hcm.manage |
| GET | `/hcm/documents/{id}/content/` (`?download=1`) | hcm.view (+ payroll.view si es sensible) |
| POST | `/hcm/employees/{ID}/user-account/` | users.create |
| GET | `/hcm/employees/{ID}/history/` | hcm.manage |
| GET | `/hcm/digital-files/` (`?country=&status=&search=`) | hcm.view |

Migraciones de la Fase 5: `database/scripts/095_hcm_digital_file_media.sql` (con `deploy.ps1`, o
`sqlcmd -S localhost -E -C -I -f 65001 -d MetamorphERP -i database\scripts\095_hcm_digital_file_media.sql`) y luego
`python manage.py migrate` (`employees.0004`, `system.0001`). Dependencia nueva: `Pillow`.

## Fuera de alcance (por ahora)
* JWT / SSO (la API usa sesión + CSRF; el SPA no maneja tokens).
* Restablecimiento de contraseña por correo (no hay servicio de correo; el reseteo lo hace RRHH/Administración).
* Listado general de usuarios en React: las cuentas se gestionan desde el expediente de cada empleado.
  Las cuentas técnicas sin empleado se crean con `createsuperuser` o la API `/users/`.
* Edición de plantillas desde React (se administran en `/admin/`) y procesamiento asíncrono de lotes
  (hoy síncrono, límite 5000 filas).
* Documentos en PDF (la Fase 5 acepta solo imágenes PNG/JPG/JPEG) y antivirus en las cargas.
* Reportes y Power BI; CRUD de negocio, motor de planilla y procesador de ingesta.
