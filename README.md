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
| 6 | Roster operativo independiente de la ficha: clientes, marcas, líneas/sub-líneas, wave y fechas de training, documento para reportes; EAV temporal con historial («Now»), sección Roster en React y consulta cruzada por rango de fechas |
| 7 | Refinamiento: máscaras de entrada desde la plantilla JSON, catálogo de bancos, corrección de vigencia, ciclo de vida Activo / Inactivo / Terminado, vincular una cuenta existente, catálogos operativos (clientes, marcas, LOB, sub-LOB) y módulo independiente de General IDs |
| 8 | Horarios y tiempo: turnos parametrizables en JSON (`lunch_minutes` = solo duración), asignación por fechas efectivas sin traslapes, tiempo evaluado por fecha de ocurrencia (turnos que cruzan la medianoche), nocturnidad parametrizable por país, ciclos de pago y cortes operativos internos, reporte de horas teóricas vs reales |
| 9 | Acciones de Personal (AP) EAV: folio único, fecha efectiva, justificación, estado y firmas digitales por rol; horarios atómicos por día (inicio, fin, almuerzo, horas diurnas y nocturnas) en lugar de turnos predefinidos; Primera AP de asignación de horario obligatoria en el alta |
| 10 | Correcciones BPO: ciclos con cortes que cruzan de mes (10–24 / 25–9) validando solo la continuidad contra el periodo anterior; carga manual de tiempos retirada (base lista para un Web Timer interno); ciclos agrupados por año y frecuencia; varios bloques y varias AP el mismo día con almuerzo opcional y reglas de almuerzo por país; fechas de ocurrencia enlazadas a un desglose diario |
| 11 | Periodos de pago y cortes internos de asistencia desacoplados (dos tablas con sus propias reglas de traslape; cada corte se mapea al periodo de pago que contiene su cierre; horas de planilla por periodo = suma de sus cortes); módulo ACD estilo Genesys Cloud: estados operativos, auxiliares y sub-auxiliares, acceso por grupo de agentes, consola del agente con hora del servidor, tablero en vivo, reporte con el formato de exportación de Genesys y envío del tiempo pagado como horas reales (WEB_TIMER) |
| 14 | Barra superior estilo Genesys Cloud (botón «Iniciar Tiempo en Turno», avatar circular con el indicador del estado ACD y lista unificada de estados → auxiliares → sub-auxiliares en cascada por hover/clic) y menú lateral colapsable con pin y expansión automática por hover |
| 15 | Dropdown de estados: altura máxima con scroll interno en el panel y en los submenús, y submenús en cascada posicionados dentro de los límites de la ventana |
| 16 | Segmentos de actividad dentro del turno (contenedor de la AP), validación de pago / billing (auxiliar primario vs secundarios pagados), motor de adherencia con Out of Adherence y Unpaid Excess Login, justificaciones respaldadas por AP aprobada |
| 17 | Planificación WFM estilo Nice IEX: filtros jerárquicos (Management Unit, cliente / marca, Operations Director → Operations Manager → Account Supervisor → Team Manager), barra de segmentos con drag & drop, grilla horizontal por intervalos, vista histórica del agente desde su contratación |
| 18 | Ajustes de la planificación IEX: panel de filtros plegable, barra compacta de iconos con flechas, segmentos como línea delgada con icono cada 15 min, granularidad al segundo (modelos, SQL Server y UI), cadena de mando centralizada en el roster y audit trail por agente y fecha |
| 19 | Reglas de asistencia y respaldo legal en WFM: Lateness automático bloqueado (solo se reemplaza con AP), Unjustified Absence con Legal Benefit Lunch, categorías del Time Utilization con desplegable en la barra, segmentos que exigen AP, ventana flotante del día (edición / lectura) y cola de aprobación de WFM |
| 20 | Planilla automática y boletas físicas: parámetros salariales de El Salvador con vigencia (ISSS, AFP, Renta, INSAFORP, horas extra, nocturnidad, vacaciones), cálculo por periodo de pago con el Web Timer, las AP de pago, los segmentos de WFM y la adherencia; cierre con generación masiva de boletas (sello SHA-256) e inventario de RRHH por lote: impresas, firmadas y archivadas |
| 21 | Refinamiento operativo y nómina avanzada: menú con flechas ▲/▼, tiempos en HH:MM:SS u horas decimales, suspensiones (antigüedad congelada), terminación con indicador de recontratación, reingreso con alerta formal, roles por tipo de AP; motor de planilla 100 % por horas (estándar BPO) con pre-cierre, boletas preliminares y excepciones; séptimo opcional por cuenta; calendario de feriados con Holiday Segments; liquidaciones e indemnizaciones con lotes de pago y cheques |
| 22 | Optimización final: Apariencia (día / noche, paleta, tiempos), chevrons, retiro del mock de asistencias, centro de notificaciones, justificaciones y permisos con / sin goce como AP, roster automático por AP, planilla por cortes con prorrateo, tipos de contrato del Excel de referencia, boletas en PDF, moneda por país, estadísticas de datos y ERD interactivo |
| 23 | Seguridad jerárquica y marca: selector de colaboradores por jerarquía (SQL `fn_EmployeesUnderLeader`) en las AP, paleta dual (global y personal en el perfil), Django Admin con la misma paleta y logos, calendario de feriados interactivo (mes / año, copia de año con Semana Santa) y los tres logos corporativos en barra, documentos / PDF y favicons |
| 24 | Anuncios y evidencias: el logotipo lleva a los anuncios corporativos (maqueta), la planilla cuenta la asistencia en los cortes internos 25–9 / 10–24 (realineación de cortes abiertos) y las AP admiten adjuntos (imágenes, PDF, Office) con pestañas de evidencias y auditoría |
| 25 | Cierre y gobernanza: sesiones y usuarios en vivo en Estado del sistema (bloqueo por intentos, gestión de cuentas en `/admin/`), SQL Server en esquemas por módulo (`sec`, `adm`, `hcm`, `org`, `wfm`, `acd`, `pa`, `fin`, `com`) con catálogo de vistas / SP / triggers, periódico virtual con acuse de recibo y compliance, y boleta desglosada por día de los cortes internos |

```
MetamorphERP/
├── database/                       # Esquema de DOMINIO SQL-first (fuente de verdad)
│   ├── deploy.ps1                  # Ejecuta scripts en orden (idempotentes)
│   └── scripts/
│       ├── 001_schemas_and_core_catalogs.sql
│       ├── 010_core_employee_code.sql       # ID corporativo por país (SP + Luhn)
│       ├── 020_hcm_employees_and_digital_files.sql
│       ├── 040_fin_payroll_deductions.sql
│       ├── 050_core_cost_center.sql         # Fase 2: centros de costos
│       ├── 060_hcm_employee_cost_center.sql # Fase 3: Employee.CostCenterId con FK compuesta (mismo país)
│       ├── 090_seed_reference_data.sql
│       ├── 095_hcm_digital_file_media.sql   # Fase 5: documentos sensibles, PROFILE_PHOTO, solo PNG/JPEG
│       ├── 096_hcm_employee_lifecycle.sql   # Fase 7: estados Activo / Inactivo / Terminado
│       └── 097_drop_wfm_attendance_mock.sql # Fase 22: retira el mock de asistencias (esquema wfm)
├── backend/
│   ├── manage.py
│   ├── config/                     # settings (.env), urls, wsgi/asgi
│   ├── apps/
│   │   ├── common/                 # core: países, secuencia, centros de costos; helpers de campos
│   │   ├── hcm/                    # Empleados, Expediente digital; services/employee_code.py
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
│   │   │   ├── masks.py            #   Fase 7: máscaras de entrada (# dígito, @ letra, * alfanumérico)
│   │   │   └── migrations/         #   0001 tablas; 0002 FKs a core/hcm; 0003 semilla (atributos + plantillas SV/GT/MX/CO); 0004 layout + documentos; 0005 bancos + máscaras
│   │   ├── operations/             # Fase 7: catálogos operativos ops_client / ops_brand / ops_line_of_business / ops_sub_line_of_business
│   │   ├── general_ids/            # Fase 7: General IDs (herramientas, tipos, IDs por empleado con vigencia; trigger + vista)
│   │   ├── personnel_actions/      # Fase 9: Acciones de Personal (tipos EAV, firmas por rol, efecto horario / salario)
│   │   ├── acd/                    # Fase 11: estados y auxiliares ACD (Genesys Cloud), grupos, sesiones, segmentos, reporte
│   │   │   └── migrations/         #   0001 tablas acd_*; 0002 FKs + triggers 50060–50062 + vistas + catálogos de referencia
│   │   ├── scheduling/             # Fases 8–11: horarios vigentes (por AP), nocturnidad, almuerzo, periodos de pago y cortes, tiempo
│   │   │   ├── engine.py           #   motor puro: bloques por día, división por día calendario, almuerzo, nocturnidad, periodos
│   │   │   ├── fields.py           #   WallClockDateTimeField: hora local de la operación, sin conversión a UTC
│   │   │   └── migrations/         #   0001 tablas; 0002 FKs + triggers 50040–50044 + vistas; 0003 parámetros de referencia;
│   │   │                           #   0005–0006 (Fase 10) reglas de almuerzo, modo de asignación, triggers 50045–50047;
│   │   │                           #   0007–0009 (Fase 11) sch_attendance_cutoff, triggers 50043–50049, vistas de planilla
│   │   ├── roster/                 # Fase 6: roster operativo (dominio independiente de la ficha)
│   │   │   ├── models.py           #   RosterDimension/Item (jerarquías), RosterAttribute (EAV), RosterAssignment (temporal)
│   │   │   ├── services.py         #   reglas temporales: cortes por fecha efectiva, «Now», correcciones sin borrar
│   │   │   └── migrations/         #   0001 tablas; 0002 FKs + trigger anti-superposición + vista; 0003 semilla
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
        ├── roster/                 # Fase 6: RosterPanel (pestaña del expediente), RosterField, consulta cruzada
        ├── generalIds/             # Fase 7: GeneralIdsPanel (pestaña del expediente), consulta y buscador de IDs
        ├── personnelActions/       # Fase 9: bandeja, detalle con firmas, nueva AP (EAV), WeeklyScheduleEditor, pestaña del expediente
        ├── scheduling/             # Fases 8–11: SchedulePanel (pestaña «Horario»), reporte, desglose diario, periodos y cortes
        ├── acd/                    # Fase 11: consola del agente, agentes en vivo, reporte de estados, grupos y auxiliares
        └── {wfm,payroll,system}/
```

## Persistencia: quién crea qué

| Tablas | Origen | En Django |
|--------|--------|-----------|
| `core.*`, `hcm.*`, `fin.*` | `database/scripts` (SQL-first) | modelos `managed = False` |
| **Fase 25:** todas las tablas, vistas, SP, funciones y triggers del ERP pasan de `dbo` a su esquema de módulo (`system/0015`); las filas siguientes muestran el **prefijo original** | migraciones de Django | `db_table = "[esquema].[tabla]"` |
| `com.com_announcement`, `com_announcement_ack`, `com_compliance_snapshot` (triggers 50120–50124, vista `vw_AnnouncementCompliance`, SP `usp_AnnouncementComplianceReport`); `fin.pay_payroll_day` (trigger 50099, vista `vw_PayPayrollDay`); `adm.vw_SystemSqlObject` | migraciones de Django (Fase 25) | modelos administrados |
| `dbo.accounts_customuser`, `auth_*`, `django_session`, `django_admin_log`, `django_content_type` | migraciones de Django | modelos administrados |
| `dbo.hcm_attribute_definition`, `hcm_employee_template`, `hcm_employee_attribute_value`, `hcm_import_batch`, `hcm_import_batch_row` | migraciones de Django (Fase 3) | modelos administrados |
| `dbo.sys_platform_settings`, `sys_user_session`, `sys_audit_event` | migraciones de Django (Fase 5) | modelos administrados |
| `dbo.roster_dimension`, `roster_dimension_item`, `roster_attribute`, `roster_assignment`, vista `vw_RosterAssignment` | migraciones de Django (Fase 6) | modelos administrados |
| `dbo.hcm_bank`; `ops_client`, `ops_brand`, `ops_line_of_business`, `ops_sub_line_of_business`, vista `vw_OpsClientBrand`; `gid_source_tool`, `gid_id_type`, `gid_id_type_client`, `gid_id_type_brand`, `gid_employee_general_id`, vista `vw_EmployeeGeneralId` | migraciones de Django (Fase 7) | modelos administrados |
| `dbo.sch_schedule_assignment`, `sch_night_rule`, `sch_lunch_rule`, `sch_pay_cycle`, `sch_pay_period`, `sch_attendance_cutoff`, `sch_time_record`, `sch_time_record_day`; vistas `vw_SchTimeByOccurrenceDate`, `vw_SchScheduleAssignment`, `vw_SchScheduleDay`, `vw_SchPayPeriod`, `vw_SchAttendanceCutoff`, `vw_SchPayrollHours`, `vw_SchLunchRule` | migraciones de Django (Fases 8–11) | modelos administrados |
| `dbo.acd_division`, `acd_primary_status`, `acd_aux_code`, `acd_agent_group`, `acd_group_aux`, `acd_agent_member`, `acd_agent_session`, `acd_status_segment`; vistas `vw_AcdStatusSegment`, `vw_AcdAgentSession` | migraciones de Django (Fase 11) | modelos administrados |
| `dbo.pa_action_type`, `pa_action_attribute`, `pa_approval_step`, `pa_action`, `pa_action_value`, `pa_action_signature`, `pa_folio_sequence`; vista `vw_PersonnelAction` | migraciones de Django (Fase 9) | modelos administrados |
| `dbo.pay_setting`, `pay_concept`, `pay_payroll_run`, `pay_payroll_line`, `pay_payslip_batch`, `pay_payslip`; vistas `vw_PayPayrollDetail`, `vw_PayPayslipInventory`; triggers sobre `fin.Payroll` / `fin.PayrollDetail` / `fin.PayrollDeduction` | migraciones de Django (Fase 20) | modelos administrados |
| `dbo.pa_action_attachment` (triggers 50110–50113, vista `vw_PaActionAttachment`) | migraciones de Django (Fase 24) | modelos administrados |
| `dbo.sys_user_preference`; función `fn_EmployeesUnderLeader`, `fn_EasterSunday`; procedimiento `usp_HolidayCopyYear`; vista `vw_HolidayCalendar` | migraciones de Django (Fase 23) | modelos administrados |
| `dbo.sys_notification_read`; procedimientos `usp_SystemTableStats`, `usp_SystemTableColumns`; vista `vw_SystemForeignKeys` | migraciones de Django (Fase 22) | modelos administrados |
| `dbo.pa_employment_event`, `hol_holiday`, `hol_holiday_segment`, `pay_account_rule`, `pay_payroll_iteration`, `pay_payroll_exception`, `pay_settlement`, `pay_settlement_line`, `pay_settlement_batch`; vistas `vw_EmployeeTenure`, `vw_HolidaySegment`, `vw_PaySettlement` | migraciones de Django (Fase 21) | modelos administrados |

`accounts.0002` y `employees.0002` crean FKs reales hacia tablas SQL-first (`hcm.Employee`, `core.catCountry`,
`core.catCostCenter`). Por eso **`deploy.ps1` va antes de `migrate`**.

| Concepto | Tabla |
|----------|-------|
| Empleados | `hcm.Employee` (`EmployeeCode` lo genera `core.usp_GenerateEmployeeCode`) |
| ExpedientesDigitales | `hcm.DigitalFile` (+ `DigitalFileDocument`, `catDocumentType`) |
| Asistencias | `dbo.adh_schedule_segment` (grilla IEX), `adh_adherence_day`, `sch_time_record` (Web Timer) — Fase 22 |
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
| roster.view / roster.manage (Fase 6) | ✔ / ✔ | ✔ / ✔ | ✔ / ✔ | |
| general_ids.view / general_ids.manage (Fase 7) | ✔ / ✔ | ✔ / ✔ | ✔ / ✔ | |
| schedules.view / schedules.manage (Fase 8) | ✔ / ✔ | ✔ / ✔ | ✔ / ✔ | |
| actions.view / actions.create (Fase 9; firmar depende del rol de cada paso) | ✔ / ✔ | ✔ / ✔ | ✔ / ✔ | |
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
| `/hcm/employees` | Lista con búsqueda y filtros por país, estado (activos / inactivos / terminados) y centro de costos; orden y paginación. Los filtros viven en la URL. | hcm.view |
| `/hcm/employees/:ID` | Ficha: datos base, vínculo laboral y «Datos requeridos por {país}» con las etiquetas de su plantilla | hcm.view |
| `/hcm/employees/new` | Alta: se elige país y fecha de ingreso → se consulta la plantilla vigente y se renderizan sus campos (obligatorios, recomendados, patrones con ejemplo, listas de opciones, centros de costos del país) | hcm.manage |
| `/hcm/employees/:ID/edit` | Edición con las mismas reglas; país e ID corporativo bloqueados; estado laboral y fecha de terminación | hcm.manage |
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

## Roster operativo (Fase 6)

**Dos dominios separados.** La *ficha* (hcm.Employee + EAV de la plantilla del país + expediente, cuenta y
documentos) describe a la persona. El *roster* (`apps/roster`, tablas `roster_*`) describe su asignación operativa en
el tiempo. Ninguno modifica al otro; se cruzan solo por el empleado.

| Atributo (semilla) | Tipo | Regla |
|--------------------|------|-------|
| Cliente · Marca | dimensión `CLIENT` · `BRAND` | la marca debe pertenecer al cliente vigente |
| Línea de negocio · Sub-línea | `LOB` · `SUB_LOB` | la sub-línea debe pertenecer a la línea vigente |
| Wave de training | texto (60) | |
| Inicio de training · Inicio de nesting · Fin de nesting · Inicio a operaciones | fecha | cada una ≥ la anterior (`not_before`) |
| Documento de identidad para reportes | dimensión `REPORT_ID_TYPE` (por país) | DUI, DPI, CURP, CC… (referencia) |

* **Configurable sin código**: en `/admin/` › Roster operativo se crean dimensiones (y sus elementos: clientes,
  marcas, líneas…) y atributos (texto, número, fecha, sí/no, lista, dimensión; dependencia jerárquica; reglas
  `pattern`, `max_length`, `min`/`max`, `not_before`/`not_after`). La interfaz React los dibuja y valida sola.
  Clientes, marcas y líneas no vienen sembrados: son datos del negocio.
* **Temporalidad**: cada valor vale en `[desde, hasta]`; `hasta` vacío = **Now**. Un cambio «desde D» corta el
  intervalo vigente en D-1; los cambios pueden ser futuros (quedan como «próximo cambio») o retroactivos (no pisan
  lo programado). Quitar un valor cierra su intervalo. Nada se borra: las correcciones marcan la fila como
  reemplazada (`superseded_at/by`) y quedan en el historial; cada cambio se audita (`roster_changed`).
* **Integridad en SQL Server**: FK a `hcm.Employee`, `CHECK` de fechas, un solo «Now» por atributo (índice filtrado) y
  el trigger `TR_roster_assignment_no_overlap`, que rechaza intervalos superpuestos aunque se escriba directo en la
  tabla. `dbo.vw_RosterAssignment` expone los intervalos vigentes con ID corporativo y descripciones (Power BI / SQL).
* **React**: pestaña **Roster** del expediente (vigente a cualquier fecha, próximo cambio, historial por atributo con
  correcciones, editor con fecha efectiva, motivo, «Validar sin guardar» y filtros jerárquicos) y menú
  **Roster operativo › Consulta de roster** (ficha + asignaciones por rango, filtros por país, estado y dimensión,
  exportación CSV en formato largo).

| Método | Ruta (`/api/v1`) | Permiso |
|--------|------------------|---------|
| GET | `/roster/attributes/` · `/roster/dimensions/` | roster.view |
| GET | `/roster/employees/{ID}/?as_of=&include=employee` (roster vigente; `include=employee` agrega la ficha con su RBAC) | roster.view (+ hcm.view) |
| GET | `/roster/employees/{ID}/history/?attribute=&include_superseded=1` | roster.view |
| POST | `/roster/employees/{ID}/changes/` · `/changes/validate/` — `{effective_date, reason, values: {código: valor \| null}}` | roster.manage |
| GET | `/roster/report/?from=&to=&country=&status=&cost_center=&search=&attribute=&value=&assigned=1&export=csv` | roster.view |

## Refinamiento y General IDs (Fase 7)

### Ficha y alta del empleado

* **Máscaras de entrada** (regla `mask` de la plantilla JSON, también por tipo de documento en `patterns_by_type`):
  `#` dígito, `@` letra, `*` letra o dígito; lo demás es literal. El usuario escribe solo los caracteres
  significativos (`012345678` → `01234567-8`); con una lista se elige la máscara que calce
  (NIT SV: `["########-#", "####-######-###-#"]`). El backend aplica la misma regla al validar (formulario y
  cargas masivas) y `pattern` sigue siendo la validación final. Semilla: DUI, DPI (GT), NIT (SV) y teléfonos por país.
* **Catálogo de bancos** (`hcm_bank`, por país, `/admin/` › Bancos): la regla `"catalog": "BANK"` convierte un campo de
  texto en lista desplegable. Se guarda el código del banco; en cargas masivas se acepta el código o el nombre.
  Un banco desactivado se conserva en los expedientes (advertencia). Un valor de texto libre registrado antes del
  catálogo se conserva mientras no se cambie y se pide elegir uno de la lista. Los bancos sembrados son de referencia.
* **Corrección de vigencia**: el alta la decide la **plantilla** del país vigente a la fecha de ingreso.
  `core.catCountry.EffectiveStartDate` (fecha de registro del país en el catálogo, 2026-01-01) ya no bloquea ingresos
  anteriores, ni en la validación ni en `core.usp_GenerateEmployeeCode`; solo un país dado de baja
  (`EffectiveEndDate`) rechaza ingresos posteriores a la baja.
* **Ciclo de vida**: `ACTIVE` Activo, `INACTIVE` Inactivo, `TERMINATED` **Terminado** (exige fecha de terminación).
  `096_hcm_employee_lifecycle.sql` migra `SUSPENDED` → `INACTIVE` y actualiza el `CHECK`. Filtro `status=NOT_ACTIVE`
  = inactivos + terminados.

### Vincular una cuenta Metamorph existente

En el alta («¿Desea crear un perfil…?» › *Vincular una cuenta existente*) o en la pestaña *Cuenta Metamorph* del
expediente se busca una cuenta **sin empleado** y se vincula. La cuenta conserva su usuario, contraseña y rol y toma
el centro de costos del empleado. Solo se listan las cuentas cuyo rol puede administrar quien vincula
(RRHH no ve ni vincula Administradores). Se audita como `user_linked`.

| Método | Ruta (`/api/v1`) | Permiso |
|--------|------------------|---------|
| GET | `/hcm/user-account-candidates/?search=` · `/hcm/employees/{ID}/user-account/candidates/` | users.update |
| POST | `/hcm/employees/{ID}/user-account/link/` — `{user_id}` · en el alta: `user_account: {"mode": "link", "user_id": 12}` | users.update |

### Catálogos operativos (`apps/operations`)

`/admin/` › Catálogos operativos: **Clientes** (con sus marcas y los General IDs que aplican), **Marcas (brands)**,
**Líneas de negocio (LOB)** y **Sub-líneas** (tablas `ops_*`). Son la fuente de verdad. Cada registro sincroniza su
elemento en las dimensiones `CLIENT`, `BRAND`, `LOB` y `SUB_LOB` del roster, que por eso ya no se editan desde
el admin del roster.
* El código no cambia después de creado y nada se borra (se desactiva).
* Desactivar un cliente desactiva sus marcas; desactivar una LOB desactiva sus sub-líneas.
* Cada cambio queda en la auditoría (categoría *Catálogos operativos*).

Lectura: `GET /operations/catalogs/` (roster.view).

### General IDs (`apps/general_ids`, independiente del roster)

Llaves para cruces (JOINs) en reportes: ACD ID, Payroll Tool ID, etc.

| Tabla | Contenido |
|-------|-----------|
| `gid_source_tool` | herramientas / software de origen (catálogo propio, con categoría y proveedor) |
| `gid_id_type` | tipos de ID: herramienta, **nivel de registro** (global / por cliente / por marca), *varios activos por empleado*, *valor único*, patrón, ejemplo, longitud y normalización |
| `gid_id_type_client` · `gid_id_type_brand` | **restricciones en cascada**, configuradas en la ficha del cliente y de la marca: sin restricciones = aplica a todos; cliente habilitado = el cliente y **todas** sus marcas; marca habilitada = solo esa marca |
| `gid_employee_general_id` | valor del ID del empleado con **vigencia** `[desde, hasta]` (vacío = «Now»), cliente/marca, notas y quién lo registró |

* Un empleado puede tener **varios IDs activos a la vez**: uno por tipo, o varios del mismo tipo si este lo permite
  (p. ej. un ACD ID por cliente/marca).
* Con *valor único*, un valor identifica a un solo registro en cada fecha. El trigger
  `TR_gid_employee_general_id_rules` lo garantiza en SQL Server (errores 50030 y 50031) aunque se escriba directo en la tabla.
* Los IDs no se borran: se **cierran** (fecha «hasta») o se **corrigen**, con auditoría (categoría *General IDs*).
* JOIN en SQL / Power BI con `dbo.vw_EmployeeGeneralId`:

```sql
SELECT g.EmployeeCode, g.FullName, a.*
FROM acd_interval_data AS a
JOIN dbo.vw_EmployeeGeneralId AS g
  ON g.IdTypeCode = 'ACD_ID' AND g.IdValue = a.agent_id
 AND a.call_date BETWEEN g.EffectiveStart AND ISNULL(g.EffectiveEnd, '9999-12-31');
```

* React: pestaña **General IDs** del expediente (registrar, cerrar, corregir, vigentes a una fecha o historial) y
  menú **General IDs › Consulta de General IDs** (buscador «¿a quién pertenece este ID?», filtros y CSV).
* Semilla de referencia: herramientas `ACD` y `PAYROLL_TOOL`; tipos `ACD_ID` (por cliente, varios activos) y
  `PAYROLL_TOOL_ID` (global, uno vigente). Renómbrelos o agregue los reales en `/admin/` › General IDs.

| Método | Ruta (`/api/v1`) | Permiso |
|--------|------------------|---------|
| GET | `/general-ids/catalogs/` (herramientas, tipos con restricciones, clientes y marcas) | general_ids.view |
| GET | `/general-ids/employees/{ID}/?as_of=&history=1` | general_ids.view |
| POST | `/general-ids/employees/{ID}/` · `/validate/` — `{id_type, value, client, brand, effective_start, effective_end, notes}` | general_ids.manage |
| PATCH · POST | `/general-ids/employees/{ID}/{pk}/` (corregir) · `/{pk}/close/` `{effective_end}` | general_ids.manage |
| GET | `/general-ids/lookup/?type=ACD_ID&value=5001&date=` | general_ids.view |
| GET | `/general-ids/report/?from=&to=&type=&tool=&client=&brand=&country=&search=&export=csv` | general_ids.view |

Migraciones de la Fase 7: `database/scripts/096_hcm_employee_lifecycle.sql` y `010_core_employee_code.sql`
(re-ejecutable; corrige el SP) con `deploy.ps1`, y luego `python manage.py migrate`.

## Horarios, tiempo y cortes de nómina (Fase 8)

App `apps/scheduling` (tablas `sch_*`). El cálculo vive en `engine.py` (funciones puras, probadas aparte);
SQL Server es la última barrera con triggers.

### Horario atómico por día (JSON)

Desde la Fase 9 **no hay turnos predefinidos**: cada horario se escribe día por día en una Acción de Personal y se
guarda en la asignación vigente con sus horas diurnas y nocturnas calculadas:

```json
{
  "days": {
    "mon": {"start": "22:00", "end": "06:00", "lunch_minutes": 30, "day_minutes": 0, "night_minutes": 450},
    "tue": {"start": "14:00", "end": "23:00", "lunch_minutes": 60, "day_minutes": 267, "night_minutes": 213},
    "sat": null, "sun": null
  },
  "lunch_allocation": "PROPORTIONAL"
}
```

* Jornada por día de la semana (`mon` … `sun`; también se aceptan `lunes` … `domingo`). `null` o ausente = descanso.
* `lunch_minutes` es **solo la duración** asignada al almuerzo (30, 60…). La hora exacta la programa WFM: se rechazan
  claves como `lunch_start` / `lunch_end`.
* Si `end` ≤ `start`, la jornada **cruza la medianoche**. Se valida que no pise la jornada del día siguiente.
* `lunch_allocation`: cómo se descuenta el almuerzo cuando la jornada cae en dos fechas (su hora no se conoce):
  `PROPORTIONAL` (predeterminado), `START_DAY` o `LONGEST_SEGMENT`.
* `day_minutes` / `night_minutes` (horas diurnas y nocturnas programadas, netas de almuerzo) las calcula el sistema con
  la regla de nocturnidad del país vigente a la fecha efectiva. Si se envían, deben coincidir con el cálculo.
* En cargas masivas se acepta la notación compacta `L-V 08:00-17:00 60; S 08:00-12:00` (días L M X J V S D, rangos y
  listas; el número final son los minutos de almuerzo).

### Fecha de ocurrencia y turnos que cruzan la medianoche

Toda hora, programada o laborada, cuenta en el **día calendario en que ocurrió**. Un turno lunes 22:00 – martes
06:00 aporta 2 h al lunes y 6 h al martes. Ambas porciones conservan `shift_date` = lunes: es **un** turno, no
dos. Los registros de tiempo (`sch_time_record`) se guardan completos y su reparto por día queda en
`sch_time_record_day`, una fila por fecha de ocurrencia, con minutos nocturnos y la regla aplicada.

* Entrada/salida en **hora local de la operación** (`AAAA-MM-DD HH:MM`, sin zona horaria). Se guarda tal cual
  (`WallClockDateTimeField`), sin conversión a UTC.
* También se aceptan horas reportadas para un día (`occurrence_date` + `minutes` u `hours`).
* Cada registro se enlaza al turno programado con el que más se traslapa (trazabilidad). Si no hay ninguno queda
  «sin turno».
* No se aceptan traslapes por empleado (trigger **50041**), fechas futuras, fechas fuera de la relación laboral
  ni fechas dentro de un corte cerrado.

### Horarios vigentes por fechas efectivas (los crea una AP)

`sch_schedule_assignment` guarda el horario de cada AP de horario aprobada, con `effective_start_date` = fecha
efectiva de la AP y fin «Now». La AP siguiente cierra el horario anterior el día previo. Un empleado no tiene dos
horarios en la misma fecha (trigger **50040**). Una AP de horario no puede tener fecha igual o anterior a la de un
horario ya aplicado, ni caer en un corte cerrado. No hay altas ni ediciones manuales de horarios.

### Nocturnidad parametrizable (`/admin/` › Reglas de nocturnidad)

* Por país y con vigencia: ventana horaria (puede cruzar la medianoche) y % de recargo.
* No se permiten dos reglas activas del mismo país con vigencias que se cruzan (trigger **50042**).
* Semilla: El Salvador 19:00–06:00 con 25 % (Código de Trabajo, arts. 161 y 168). Los demás países se configuran
  con su norma.
* El reporte muestra los minutos nocturnos y su **equivalente de recargo** en minutos (no calcula montos).

### Ciclos de pago: periodos de pago y cortes internos de asistencia (Fase 11)

Dos dimensiones **independientes**, cada una en su tabla y con sus propias reglas de traslape:

| | Periodo de pago (`sch_pay_period`) | Corte interno de asistencia (`sch_attendance_cutoff`) |
|---|---|---|
| Qué es | Fechas oficiales de devengo y pago | Ventana operativa en la que se cuentan las horas |
| Ejemplo BPO | 1–15 (pago el 15) y 16–fin (pago el último día) | 25 del mes anterior al 9, y del 10 al 24 |
| Regla (`/admin/` › Ciclos de pago) | `period_rule`, día de inicio, fin de la primera quincena, `payment_lag_days` | `cutoff_start_day` + `cutoff_first_end_day` (ventanas propias) o `cutoff_lag_days` (derivadas: N días antes del fin del periodo; 0 = igual al periodo) |
| SQL Server | **50043** colisión · **50045** hueco / colisión contra el periodo anterior | **50044** colisión · **50046** hueco / colisión contra el corte anterior · **50049** fechas de un corte cerrado |
| Estado | — | Abierto / cerrado (bloquea horarios y tiempos en su ventana) |

* **Mapeo**: cada corte se paga en el periodo de pago **más próximo**: el que contiene su fecha de cierre (el corte
  25/12–09/01 se paga en la quincena 1–15 de enero; el 10–24 en la 16–fin). SQL Server lo exige (**50048**) al guardar
  un corte y al cambiar las fechas de un periodo.
* **Motor de horas para planilla**: las horas de un periodo de pago son las de los cortes mapeados a él
  (`GET /pay-periods/{id}/hours/`, CSV, y `dbo.vw_SchPayrollHours` por empleado × corte × periodo). Un día que cae en
  la quincena 1–15 pero en el corte 10–24 se paga en la quincena siguiente.
* `PayCycle.period_rule`: `HALF_MONTH` (dos periodos por mes), `MONTH` (del día de inicio al anterior del mes
  siguiente) o `FIXED_DAYS` (bloques de N días desde una fecha ancla; su corte siempre es derivado).
* «Generar periodos y cortes» crea, por separado, los periodos de pago del año y los cortes que se pagan en ellos.
  Lo existente (incluido lo ajustado a mano) no se toca; cada uno continúa el día siguiente al último de su misma
  dimensión (un cambio de regla produce un periodo / corte de transición). Saltarse un año entero se rechaza.
* Cada periodo pertenece al **año en que inicia**; la pantalla agrupa por año y frecuencia y muestra junto a cada
  periodo de pago los cortes que paga, con cierre y reapertura por corte.
* Migración de datos (0008): cada ventana de corte que existía en los periodos se copió como corte (`C-<periodo>`),
  con su estado y ajustes manuales. El ejemplo `SV_QUINCENAL_BPO` quedó como pago 1–15 / 16–fin y asistencia
  25–9 / 10–24 (**no** predeterminado: márquelo como tal y desmarque `SV_QUINCENAL` si la operación lo usa).
* El ciclo de un empleado es el predeterminado de su país y frecuencia de pago.

### React

* Pestaña **Horario** del expediente: horario principal por día (según su AP), asignaciones adicionales vigentes,
  historial por AP, botones «Nueva AP de cambio de horario» y «Asignación adicional», y la semana del empleado por
  fecha de ocurrencia.
* Menú **Horarios y tiempo**:
  * Horas teóricas vs reales: por rango libre, por periodo de pago (sus cortes o sus fechas oficiales) o por un
    corte, con filtros, tolerancia, totales por empleado y CSV (cada fila muestra la o las AP de horario de origen).
  * Ciclos de pago y cortes: por año y frecuencia; cada periodo de pago con los cortes que paga; generar, cerrar y
    reabrir cortes; «Horas para planilla» y su CSV.
* **Desglose diario** (`/scheduling/employees/:ID/days/:fecha`, Fase 10): toda fecha de ocurrencia del reporte y de
  la semana del expediente es un enlace. Muestra los bloques que aportan horas ese día (AP, principal o adicional,
  fecha de turno, porción del día, almuerzo, nocturnas), el tiempo registrado, el corte, la nocturnidad, las reglas
  de almuerzo y las AP con fecha efectiva ese día (base para auditoría).
* **Registros de tiempo manuales: retirados** (Fase 10) por el riesgo de manipulación. La pantalla ya no existe y los
  endpoints de escritura responden 403 (`SCHEDULING_MANUAL_TIME_ENTRY=false`). Los registros existentes se siguen
  consultando; la tabla `sch_time_record` y el origen `WEB_TIMER` quedan listos para el futuro Web Timer interno.

### API (`/api/v1/scheduling`)

| Método | Ruta | Permiso |
|--------|------|---------|
| GET | `/catalogs/` · `/night-rules/` · `/lunch-rules/` · `/pay-cycles/?year=&frequency=` · `/employees/{ID}/assignments/` | schedules.view |
| GET | `/employees/{ID}/days/{AAAA-MM-DD}/` (desglose de una fecha de ocurrencia) | schedules.view |
| POST | `/schedule-preview/` `{schedule, country, effective_date}` | schedules.view |
| GET | `/employees/{ID}/timeline/?from=&to=` | schedules.view |
| GET | `/time-records/` (consulta) | schedules.view |
| POST · DELETE | `/time-records/` · `/time-records/{pk}/` · `/time-records/upload/` — **403** mientras la carga manual esté retirada | schedules.manage |
| GET | `/report/?from=&to=` o `?period=&basis=cutoff\|period` o `?cutoff=`, `country`, `flag`, `tolerance`, `search`, `export=csv` | schedules.view |
| GET | `/pay-periods/{id}/hours/` (`?export=csv`): horas para planilla = suma de los cortes mapeados | schedules.view |
| POST | `/pay-cycles/{code}/generate/` `{year}` · `/cutoffs/{id}/close/` · `/cutoffs/{id}/reopen/` | payroll.manage |

Para Power BI / SQL: `dbo.vw_SchTimeByOccurrenceDate` (tiempo real por fecha de ocurrencia, con turno de origen,
recargo y corte), `dbo.vw_SchScheduleAssignment` (horario vigente con el folio de su AP), `dbo.vw_SchScheduleDay`
(una fila por **bloque** de cada día, con inicio, fin, almuerzo, minutos diurnos / nocturnos y tipo de asignación),
`dbo.vw_SchPayPeriod` (periodo de pago con el resumen de sus cortes), `dbo.vw_SchAttendanceCutoff`,
`dbo.vw_SchPayrollHours` y `dbo.vw_SchLunchRule`.
Las horas **teóricas por día calendario** las calcula el motor (endpoint `/report/` y su CSV), porque un turno que
cruza la medianoche reparte sus horas entre dos fechas.

## Acciones de Personal (Fase 9)

App `apps/personnel_actions` (tablas `pa_*`). Cada AP tiene **folio único** por prefijo y año
(`APH-2026-000001`), **fecha efectiva**, empleado, **observaciones / justificación**, **estado de aprobación** y
**firmas digitales** por rol.

### Tipos parametrizables con EAV (`/admin/` › Acciones de personal › Tipos)

* **Tipo**: categoría, prefijo del folio, permisos para verla / crearla (p. ej. el ajuste salarial exige permisos de
  planilla, así que WFM no lo ve), opción «quien envía firma el primer paso» y opción «firmantes distintos».
* **Efecto al aprobarse**:
  * `SCHEDULE`: aplica el horario desde la fecha efectiva.
  * `SALARY`: actualiza el salario base. Si la fecha es futura, lo aplica `python manage.py apply_due_personnel_actions`
    (prográmelo a diario).
  * `NONE`: solo registro.
* **Campos (EAV)**: texto, texto largo, entero, decimal, fecha, sí/no, lista de opciones y **horario semanal**, con
  obligatoriedad, rangos y ayuda. Los valores se guardan en `pa_action_value`, en la columna que corresponde a su tipo.
* **Cadena de firmas**: pasos ordenados, cada uno con el rol que firma (jerarquía por roles). El Administrador puede
  firmar cualquier paso.

Tipos sembrados:

| Tipo | Folio | Firmas |
|------|-------|--------|
| Primera AP de asignación de horario (fundacional) | APH | RRHH |
| Cambio de horario (motivo + horario) | APH | WFM → RRHH |
| Ajuste salarial (tipo + nuevo salario) | APS | RRHH → Administración |

### Flujo y firmas digitales

`Borrador → En aprobación → Aprobada | Rechazada`; un borrador o una AP en aprobación también se puede **anular**,
con motivo.

* Al enviar la AP se **sella** su contenido (SHA-256 de tipo, empleado, fecha, justificación y valores). Desde ahí no
  cambia: los triggers **50051** (valores) y **50052** (encabezado y estados resueltos) lo impiden.
* Cada firma registra quién, con qué rol, la decisión, la hora y un **HMAC-SHA256**. El HMAC usa una clave del
  servidor y cubre el folio, el paso, el firmante y el sello del contenido. El detalle verifica la integridad y
  avisa si algo se alteró. Las firmas son inmutables (trigger **50050**).
* Rechazar exige un comentario. Una AP aprobada no se edita: se corrige con otra AP.

### Primera AP de asignación de horario (alta)

* El alta, por formulario o por carga masiva (columna `schedule`), **exige el horario**. En la misma transacción
  se crea la AP fundacional con fecha efectiva = fecha de ingreso y se envía a firma.
* Con la cadena sembrada, RRHH o el Administrador que da el alta firma el único paso, así que la AP queda aprobada y
  el horario vigente.
* Si falta el horario, no se crea el empleado.
* Los empleados creados antes de la Fase 9 aparecen en «sin Primera AP» (bandeja y pestaña Horario) para
  regularizarlos. Un cambio de horario exige que exista la AP fundacional.

### API (`/api/v1/personnel-actions`)

| Método | Ruta | Permiso |
|--------|------|---------|
| GET | `/types/` · `/` (`status`, `type`, `employee`, `search`, `pending_for_me=1`) · `/{folio}/` · `/employees/{ID}/` · `/missing-initial/` | actions.view (+ permiso del tipo) |
| POST | `/` · `/validate/` `{action_type, employee_code, effective_date, justification, values, submit}` · `/{folio}/submit/` · `/{folio}/cancel/` | actions.create (+ permiso del tipo) |
| PATCH | `/{folio}/` (solo borradores) | actions.create |
| POST | `/{folio}/sign/` `{decision: APPROVED\|REJECTED, comment}` | rol del paso pendiente |
| POST | `/schedule-preview/` `{schedule, country \| employee_code, effective_date}` | actions.view |

React: menú **Acciones de personal** (bandeja con «pendientes de mi firma», nueva AP con formulario dinámico EAV y
editor de horario por día, detalle con la cadena de firmas), pestaña **Acciones de personal** del expediente y
sección **Primera AP de asignación de horario** en el alta. Vista SQL: `dbo.vw_PersonnelAction`.

## Correcciones BPO (Fase 10)

### Varios bloques y varias AP el mismo día

* Un día del horario puede tener hasta **4 bloques** (turno partido 08:00–12:00 + 14:00–18:00). En el JSON el día es
  una lista de bloques; un objeto solo sigue valiendo como un bloque. Notación compacta para cargas masivas:
  `L-V 08:00-12:00 + 14:00-18:00; S 08:00-12:00`.
* Además del horario **principal**, un empleado puede tener **asignaciones adicionales** (doble asignación, refuerzo,
  otra campaña) con la AP «Asignación adicional de horario» (`AP_HORARIO_ADICIONAL`, firmas WFM → RRHH, campo
  obligatorio `vigente_hasta`). Conviven con el principal y sus horas programadas se **suman** por fecha de
  ocurrencia (reporte, desglose, CSV). Un cambio de horario reemplaza solo el principal.
* Ningún par de bloques puede pedir las mismas horas: se valida al elaborar y al aprobar la AP (código
  `schedule_collision`). SQL Server sigue impidiendo dos horarios **principales** en fechas que se cruzan (50040), y
  una asignación adicional siempre tiene fecha de fin (`ck_sch_assign_additional_end`).
* En `/admin/` › Tipos de AP, el campo «asignación de horario» (principal / adicional) define el comportamiento.

### Almuerzo sin valor fijo: reglas por país (`/admin/` › Reglas de almuerzo)

* `lunch_minutes` es opcional (0 si se omite) en cada bloque.
* `sch_lunch_rule`: país, **jornada continua mínima** (minutos de un bloque), **almuerzo mínimo** y aplicación
  «Advertencia» (no bloquea) u «Obligatorio» (bloquea la AP), con vigencia. Admite tramos (≥ 5 h → 30 min,
  ≥ 9 h → 60 min): aplica el de umbral más alto que alcanza el bloque. Un turno partido no necesita almuerzo si
  ningún bloque llega al umbral. Trigger **50047**: un umbral por país y fechas.
* Semilla de referencia SV: bloques de 6 h o más → 30 min, en modo advertencia. **Valide el umbral y la duración con
  Legal / Planilla.**

## Estados y auxiliares ACD (Fase 11)

Modelo y flujo estilo **Genesys Cloud** (`apps/acd`, tablas `acd_*`).

### Catálogos (`/admin/` › Estados y auxiliares ACD)

* **Estados operativos** (presencias primarias, códigos fijos): Offline, Available, On Queue (tiempo productivo), Busy,
  Away, Break, Meal (no pagado), Meeting, Training, Idle. Se ajustan etiqueta del reporte, nombre, color y si cuentan
  como sesión, productivo o pagado.
* **Auxiliares** (presencias secundarias) bajo un estado primario y **sub-auxiliares** de un solo nivel (Coaching →
  Calidad / Supervisor), con pagado, productivo, máximo de minutos por uso y «restringido por grupo». SQL Server:
  **50062** (un nivel y mismo estado que el padre).
* **Divisiones** (Division Id = UUID estable, Division Name).
* Semilla de referencia: división «Home», los 10 estados, 11 auxiliares comunes de BPO (Break, Personal, Lunch, ACW,
  Back Office, System Issue, Coaching y sus 2 sub-auxiliares, Team Meeting, Training) y el grupo `GENERAL` sin agentes.
  Ajústelos a la operación.

### Grupos / perfiles de agentes (menú ACD › Grupos y auxiliares, WFM)

* Cada grupo tiene división y **auxiliares permitidos**: un auxiliar restringido solo lo ven y usan los grupos con
  acceso; dar acceso al padre incluye sus sub-auxiliares. Los no restringidos los ven todos.
* Un agente pertenece a **un** grupo activo (índice único filtrado). Moverlo o retirarlo requiere que no tenga sesión
  abierta.

### Flujo del agente (menú ACD › Mi estado)

* **Iniciar sesión** → Available. **On Queue** = tiempo productivo. O un estado con su auxiliar / sub-auxiliar
  permitido. **Cerrar sesión** → Offline.
* Cada cambio cierra el segmento anterior y abre otro con la **hora del servidor** en UTC con milisegundos (Start Time,
  End Time, Duration): el navegador no envía horas. Un solo segmento y una sola sesión abiertos por agente; sin
  traslapes (**50060**); el auxiliar pertenece al estado del segmento (**50061**).
* Al cerrar sesión, el tiempo **pagado** (sin Meal ni auxiliares no pagados) se envía a horarios como registros
  `WEB_TIMER` (hora local, al minuto): son las horas reales del reporte teórico vs real y de los cortes de planilla.
  Si un corte de asistencia está cerrado, la sesión queda «con error» y el detalle se ve en la consola y en
  `vw_AcdAgentSession`, sin deshacer el cierre de sesión.
* Supervisión (ACD › Agentes en vivo): estado y tiempo en estado por agente, alertas al exceder el máximo de un
  auxiliar y cierre de sesión forzado (queda como origen «Supervisor» con su motivo).

### Reporte de estados (formato de exportación de Genesys Cloud)

Columnas: `Interval Start`, `Interval End`, `Interval Complete`, `Employee Id`, `Employee Name`, `Division Id`,
`Division Name`, `Start Time`, `End Time`, `Primary Status`, `Secondary Status`, `Duration`.

* `Duration` en **milisegundos**; horas ISO-8601 con milisegundos y desfase de la zona elegida (`tz`, por defecto
  `America/El_Salvador`), p. ej. `2026-10-06T08:15:00.000-06:00`.
* Intervalos de 30 min, 1 h, día o todo el rango: cada segmento se recorta a cada intervalo que toca.
  `Interval Complete` = `TRUE` si el intervalo ya terminó. Un segmento en curso sale sin `End Time`, con la duración
  hasta ahora. `Secondary Status` de un sub-auxiliar = «Padre - Nombre» (p. ej. `Coaching - Calidad`).
* `Employee Id` = ID corporativo. CSV en UTF-8 con BOM (Excel). Máximo 31 días por consulta.
* SQL: `dbo.vw_AcdStatusSegment` (un segmento por fila, horas UTC) y `dbo.vw_AcdAgentSession`.

### Permisos y API (`/api/v1/acd`)

| Permiso | Roles |
|---------|-------|
| `acd.agent` (consola) | todos (el Administrador técnico sin expediente no puede ser agente) |
| `acd.view` (tablero, reporte, grupos) | Administrador, RRHH, WFM |
| `acd.manage` (grupos, acceso, agentes, cierre forzado) | Administrador, WFM |

| Método | Ruta | Permiso |
|--------|------|---------|
| GET | `/catalogs/` | acd.view |
| GET · POST | `/me/` · `/me/login/` · `/me/status/` `{primary_status, aux_code}` · `/me/logout/` | acd.agent |
| GET | `/agents/?group=&division=&status=&search=` | acd.view |
| POST | `/agents/{ID}/logout/` `{reason}` | acd.manage |
| GET | `/report/?from=&to=&interval=30\|60\|1440\|range&tz=&group=&division=&employee=&status=&export=csv` | acd.view |
| GET · POST · PATCH | `/groups/` · `/groups/{code}/` `{name, division, is_active, aux_codes}` | view · manage |
| POST · DELETE | `/groups/{code}/members/` `{employee_code}` · `/groups/{code}/members/{ID}/` | acd.manage |

## Barra superior y menú lateral (Fase 14)

* **Barra superior** (`components/layout/UserPresenceMenu.jsx`), a la derecha:
  * **Botón de turno**: «Iniciar Tiempo en Turno» abre la sesión ACD (Available). En turno muestra el tiempo de la
    sesión y «Finalizar» (pide confirmación y pasa a Offline). Solo aparece para usuarios con expediente, permiso
    `acd.agent` y grupo ACD activo; sin grupo queda deshabilitado con el motivo.
  * **Avatar circular**: foto de perfil del expediente (o iniciales) con un anillo y un punto del color del estado
    actual. La foto la sirve `GET /api/v1/auth/me/photo/` (solo la propia, sin requerir `hcm.view`); `/auth/me/`
    incluye `photo_url`.
  * **Clic en el avatar**: panel con el estado actual y su cronómetro (rojo si excede el máximo del auxiliar), la
    **lista unificada** de estados y los enlaces de cuenta (consola del agente, «Finalizar turno y salir del sistema»,
    «Salir sin finalizar el turno»). Los estados con auxiliares despliegan un **submenú en cascada** al pasar el cursor
    (o con clic / Enter / ← en teclado y pantallas táctiles); un auxiliar con sub-auxiliares abre un tercer nivel. Cada
    submenú incluye «sin auxiliar». En pantallas ≤ 640 px los submenús se abren en línea (acordeón).
* **Estado compartido** (`modules/acd/AgentPresenceContext.jsx`): la barra y la consola «Mi estado» usan el mismo
  estado (`/acd/me/`), refrescado cada 60 s con la pestaña visible y al volver a ella; cualquier cambio se ve en ambos.
  Los avisos de cada cambio aparecen como notificación bajo la barra.
* **Menú lateral** (`components/layout/Sidebar.jsx`), en escritorio (≥ 900 px):
  * **Pin**: el botón en la cabecera del menú (o ☰) alterna entre menú fijo (248 px) y contraído (barra de íconos de
    60 px). La preferencia se recuerda en el navegador (`localStorage`).
  * **Expansión por hover**: contraído, al pasar el cursor (o al llegar con Tab) se expande sobre el contenido mostrando
    etiquetas y submenús, y se contrae al salir; Escape lo cierra. El ícono del módulo activo queda resaltado.
  * El contenido usa el ancho restante (`minmax(0, 1fr)`): al fijar o contraer el menú, tablas y formularios se
    reacomodan sin desbordar la página (las tablas anchas desplazan dentro de su contenedor).
  * En móvil el menú sigue siendo el panel deslizable de ☰.
* **Límites del dropdown (Fase 15)**: el panel del avatar nunca es más alto que el espacio bajo la barra
  (`max-height` + scroll interno propio, sin desplazar la página). Los submenús en cascada (`Flyout` en
  `UserPresenceMenu.jsx`) son `position: fixed` y se colocan contra la ventana: se abren a la izquierda y, si no caben,
  a la derecha; suben para no salirse por abajo, siguen a su elemento al desplazar el panel y, si tienen más elementos
  que la altura de la ventana, hacen scroll dentro del submenú. En móvil siguen en línea dentro del panel.

## Segmentos de actividad y adherencia (Fase 16)

App `apps.adherence` (tablas `adh_*`), pantallas en **Workforce (WFM)**. Ver: `wfm.view`; editar: `wfm.manage`
(rol WFM y Administrador; RRHH solo consulta).

* **Contenedor y segmentos.** El contenedor de cada agente es el bloque entrada-salida de su horario vigente
  (`sch_schedule_assignment`, creado por la AP de horario). En **Planificador de segmentos** WFM inserta segmentos
  preconfigurados (`adh_schedule_segment`: inicio, fin y actividad) para uno o varios agentes y un rango de fechas:
  Break, Almuerzo, Capacitación, Coaching, Back Office, Reunión… El tiempo del contenedor que no cubre ningún segmento
  es de la **actividad predeterminada** (Producción). Un segmento siempre queda dentro del contenedor de su fecha de
  turno (en un turno nocturno 22:00–06:00, «02:00» es el día siguiente), no se traslapa con otro (servicio + SQL
  **50070**) y no se toca en fechas de un corte de asistencia cerrado. Si el horario trae minutos de almuerzo sin
  segmento de almuerzo programado, el planificador lo advierte.
* **Actividades** (`adh_activity_type` + `adh_activity_status`): por actividad, si es pagada, si es facturable
  (billing), su color, duración sugerida y **qué estados / auxiliares ACD la cumplen**, con su rol:
  * **Auxiliar primario** = trabajo principal (On Queue en Producción, Busy · Back Office en Back Office…).
  * **Auxiliar secundario pagado** = auxiliar permitido y pagado por diseño del segmento (Busy · ACW dentro de
    Producción). Un auxiliar padre incluye sus sub-auxiliares (Coaching → Coaching - Calidad).
* **Motor de adherencia** (`apps/adherence/engine.py`, sin BD): cruza plan vs estados reales del ACD / Web Timer
  (UTC → hora local de la operación) segundo a segundo:
  * Dentro del contenedor, estado permitido por la actividad del momento → **en adherencia**; si no, **Out of
    Adherence** (también si está programado y sin sesión).
  * **Válido para pago**: tiempo dentro del contenedor en estado pagado (o auxiliar secundario pagado).
    **Facturable**: además en adherencia y en actividad facturable. Se separan *trabajo principal* y *auxiliares
    secundarios pagados*.
  * Sesión **fuera** de todo contenedor → **Unpaid Excess Login** (no se paga).
  * **Adherencia %** = en adherencia / (programado − programado justificado). **Conformidad %** = con sesión dentro del
    contenedor / programado. Solo se evalúa hasta la hora actual.
* **Justificaciones (AP)** (`adh_exception`): ventana ligada a una AP **aprobada** del mismo empleado (servicio + SQL
  **50071**); ese tiempo no se marca como desviación y se paga si así se indica. Se agrega el tipo de AP de referencia
  **AP_JUSTIFICACION_TIEMPO** (permiso, cita médica, misión oficial, falla de sistema, tiempo extra autorizado; firmas
  WFM → RRHH).
* **Adherencia** (pantalla): KPIs, tabla por agente y día, y detalle con la línea de tiempo programado / real /
  desviaciones. **Guardar resultados** persiste los días terminados (`adh_adherence_day` + `adh_deviation`) para
  nómina y control de calidad; omite las fechas de cortes cerrados.
* **SQL Server**: `dbo.vw_AdhScheduleSegment`, `dbo.vw_AdhAdherenceDay` (con corte de asistencia y periodo de pago) y
  `dbo.vw_AdhDeviation`.
* API: `/api/v1/adherence/` → `catalogs`, `activities`, `planner`, `segments` (+ `bulk`), `exceptions`, `report`,
  `detail`, `compute` (detalle en `apps/adherence/views.py`).

## Planificación estilo IEX y jerarquía operativa (Fase 17)

Pantalla **WFM › Planificación (grilla IEX)** (`/wfm/planner`) y **Roster › Cadena de mando** (`/roster/hierarchy`; desde la Fase 18,
antes WFM › Jerarquía operativa).

* **Jerarquía operativa** (`ops_leader`): Operations Director → Operations Manager → Account Supervisor → Team Manager.
  Cada líder es un colaborador (FK a `hcm.Employee`) que reporta a un líder **activo del nivel inmediato superior**
  (servicio + SQL **50080**); no se desactiva con subordinados activos. Cada líder se sincroniza con su dimensión del
  roster (`OPS_DIRECTOR`, `OPS_MANAGER`, `ACCOUNT_SUPERVISOR`, `TEAM_MANAGER`, con el jefe como padre). Al agente se
  le asigna su **Team Manager** en el roster (atributo temporal `team_manager`, con fechas); los niveles superiores
  se derivan de la cadena. Vistas: `dbo.vw_OpsLeaderHierarchy` y `dbo.vw_RosterAgentHierarchy`.
* **Panel izquierdo de filtros**: Management Unit (grupo de agentes ACD), cliente y marca (roster vigente en la
  fecha) y desplegables **encadenados** de la jerarquía (cada nivel muestra solo los líderes bajo el elegido arriba;
  manda el nivel más bajo elegido).
* **Barra superior fija** con los cuadros (icono + color + duración sugerida) de los segmentos de la **cuenta**
  elegida: `adh_activity_type.icon` y `adh_activity_client` (sin cuentas = todas), editables en «Actividades».
* **Grilla horizontal** por intervalos (15 / 30 / 60 min) con columnas fijas de agente y adherencia: el turno
  vigente (AP de horario) es el **pre-contenedor gris**; encima, los segmentos; debajo, la actividad real del ACD
  (color del estado) y las marcas de Out of Adherence / Unpaid Excess Login. Metadatos en `adh_grid_setting`
  (intervalo, ajuste al soltar y margen; global o por Management Unit).
* **Drag & drop**: arrastrar un cuadro de la barra y soltarlo en la pista del agente crea el segmento a esa hora
  (ajustada al «snap», con la duración sugerida y encajada dentro del pre-contenedor); arrastrar un segmento lo
  mueve. Alternativa táctil / teclado: clic en el cuadro y clic en la hora. Cada cambio se guarda en el backend y
  devuelve la **adherencia del día recalculada**; si ese día ya estaba guardado para nómina y calidad
  (`adh_adherence_day`), se vuelve a guardar con el plan nuevo.
* **Vista 1 – Grilla de grupo**: varios agentes en paralelo para una fecha, con KPIs y programación masiva.
  **Vista 2 – Agente (histórico)**: todas las líneas de tiempo del colaborador **desde su fecha de contratación**,
  día por día en páginas de 14 días (máx. 31), con su cadena de mando y la adherencia de cada día.
* API: `/api/v1/adherence/grid/` (`filters/`, `agent/`, `settings/`, `audit/`) y `/api/v1/roster/hierarchy/leaders/` (Fase 18). Ver: `wfm.view`;
  editar: `wfm.manage`.

## Ajustes de la planificación, segundos, cadena de mando en el roster y audit trail (Fase 18)

* **Panel de filtros plegable** (igual que el menú de módulos): el botón de la cabecera lo fija o lo contrae a una
  barra de íconos (Management Unit, cuenta, cadena de mando, búsqueda; un punto marca los que filtran). Contraído, se
  despliega SOBRE la grilla al pasar el cursor o con el foco del teclado, sin moverla, y se vuelve a contraer al salir
  (Esc también). La preferencia se recuerda en el navegador. En pantallas angostas queda arriba y muestra solo su cabecera.
* **Barra compacta de actividades**: un cuadrado por actividad (solo el icono sobre su color) en una tira horizontal
  continua, sin barra de desplazamiento nativa; las flechas laterales (y la rueda del ratón) la desplazan y se
  desactivan en los extremos. El nombre, la duración sugerida y si es pagada / facturable aparecen en un tooltip
  flotante (hover o foco). Se siguen arrastrando a la grilla o se eligen con clic y luego clic en la hora.
* **Segmentos como línea delgada** dentro del pre-contenedor gris, con el icono de la actividad repetido cada 15 minutos
  desde su inicio (patrón visual); el detalle va en el tooltip.
* **Granularidad al segundo**:
  * La API acepta `HH:MM:SS` en segmentos (`start` / `end`) y `AAAA-MM-DDTHH:MM:SS` en justificaciones; devuelve
    `seconds` (exacto) y `minutes` con decimales en segmentos, bloques del plan y contenedores. El mínimo de un segmento
    es de 60 s (antes 5 min).
  * `adh_activity_type.default_seconds` (antes `default_minutes`) y `adh_grid_setting.snap_seconds` (antes
    `snap_minutes`): ajuste al soltar de **1 s**, 15 s, 30 s, 1, 5, 15 o 30 min. Con 1 s la hora queda donde se suelta.
  * SQL Server: los CHECK `ck_adh_segment_whole_seconds`, `ck_adh_exception_whole_seconds` y
    `ck_adh_deviation_whole_seconds` exigen segundos enteros (sin fracciones). `vw_AdhScheduleSegment` calcula con
    `DATEDIFF(SECOND)` (`DurationSeconds` y `Minutes` decimal). Antes, `DATEDIFF(MINUTE)` contaba fronteras de
    minuto, así que 10:00:50–10:01:10 daba 1 minuto. `vw_AdhAdherenceDay` agrega las columnas `…Seconds`.
  * El motor ya calculaba en segundos. Los eventos del ACD se guardan con milisegundos (`datetimeoffset(7)`,
    `duration_ms`) y se cruzan con el plan al segundo. La interfaz muestra `H:MM:SS` y edita con `step=1`.
  * El tiempo pagado que el ACD envía a nómina como marcaciones WEB_TIMER sigue siendo al minuto, porque las marcaciones
    de nómina (`sch_time_record`) son por minuto.
* **Cadena de mando en el roster**: la gestión pasó a **Roster › Cadena de mando** (`/roster/hierarchy`, permisos
  `roster.view` / `roster.manage`, auditoría en la categoría ROSTER); `/wfm/hierarchy` redirige allí y la API
  `/api/v1/operations/leaders/` se reemplazó por `/api/v1/roster/hierarchy/leaders/`.
  * En el expediente › Roster, la sección **Cadena de mando** muestra, a la fecha consultada, su Team Manager (del
    roster) y los niveles derivados. Si el colaborador es líder, muestra su rol, a quién reporta y cuántos le reportan,
    y permite asignar o editar el rol sin salir del roster.
  * La **Consulta de roster** agrega la columna «Cadena de mando» y los filtros encadenados Director → Manager →
    Supervisor → Team Manager. Los mismos datos alimentan los filtros y la grilla de WFM.
* **Audit trail por línea / fecha**: un clic en la cabecera de una fila de la grilla (agente) o de la vista del agente
  (fecha), o en su ícono de reloj, abre un panel lateral (`GET /api/v1/adherence/grid/audit/?employee=&date=`). Muestra
  en orden cronológico inverso, con filtros Cambios / Aprobaciones / Acciones / Sistema:
  * segmentos programados, movidos y eliminados, con el **antes y el después** al segundo, y la programación masiva;
  * justificaciones;
  * la AP de horario que creó el pre-contenedor y las AP que justifican tiempo: elaboración, envío, cada firma de
    aprobación o rechazo (paso, firmante, comentario) y su aplicación;
  * el Team Manager del roster vigente y sus correcciones;
  * las sesiones ACD del día;
  * el resultado guardado para nómina y calidad y su recálculo tras cambiar el plan;
  * el cierre del corte de asistencia.

  Los eventos nuevos guardan en `sys_audit_event.details` la fecha de turno y el antes / después. Los eventos
  anteriores a la Fase 18 se reconocen por la fecha escrita en su descripción.

## Asistencia automática, Time Utilization, AP obligatoria y ventana del día (Fase 19)

* **Lateness automático (bloqueado)**: si el agente inicia sesión en el ACD / Web Timer después de la entrada del
  bloque en curso + la **tolerancia** de su Management Unit (`adh_grid_setting.lateness_grace_seconds`, 60 s por
  defecto), el sistema inserta un segmento **Lateness** que cubre el retraso al segundo (origen «Automático»,
  `is_locked`). No se elimina ni se mueve: solo se **reemplaza** con un segmento documentado y el folio de una **AP
  aprobada** del agente (`POST /api/v1/adherence/segments/{id}/replace/`). Si el reemplazo cubre solo una parte, lo
  demás sigue bloqueado. SQL Server lo protege con `TR_adh_schedule_segment_locked` (50073); solo el servicio de
  reemplazo lo libera (`SESSION_CONTEXT N'adh.replace_locked'`).
* **Unjustified Absence + Legal Benefit Lunch**: si en todo el bloque del turno no hubo sesión ACD, el contenedor se
  marca como **Unjustified Absence** (bloqueado), salvo un bloque de **Legal Benefit Lunch** donde estaba el almuerzo
  (o al centro del turno), con la duración del almuerzo del horario. Los segmentos del plan que exigían sesión (break,
  almuerzo, coaching…) quedan sin efecto y su antes queda en la auditoría.
  * Se mantiene **separado** el personal inactivo (no activo, aún no contratado o dado de baja en la fecha) y el que
    tiene permiso / licencia (justificación por AP o actividades sin sesión que cubren el turno): no se marcan como
    ausentes.
  * La grilla muestra el estado por fila (Lateness, Ausencia injustificada, Permiso / licencia, Inactivo) y la
    **dotación neta** (con turno − ausentes − permisos − inactivos).
  * Se concilia con el botón **Conciliar asistencia** de la grilla (`POST /api/v1/adherence/attendance/reconcile/`),
    al **Guardar adherencia** (antes del cálculo de los días terminados; `reconcile: false` lo omite) o a diario con
    `python manage.py adh_reconcile_attendance [--date AAAA-MM-DD] [--group CODIGO]` (por defecto, ayer). Es idempotente.
  * El motor de adherencia ahora distingue actividades que **no exigen sesión ACD** (`requires_acd_login`): permisos de
    RRHH, fallas de sistema, Worked Time Unlogged o el almuerzo legal cuentan como en adherencia sin sesión y se pagan /
    facturan según la actividad. Lateness y ausencia no son pagados y cuentan como Out of Adherence.
* **Categorías del Time Utilization** (`adh_activity_category`), tomadas de *Time Utilization Project - Kevin
  Duran.xlsx* (Departamento → Segmento principal → Sub segmento): Billable - Regular Segments, Out of the Phone Work,
  Worked Time Unlogged, Training, System Issues, HR Confidential Paid / Unpaid y Asistencia automática; 97 sub
  segmentos sembrados como actividades más las 3 del sistema. Las actividades existentes se clasificaron (Break 1 / 2,
  Open y Back Office Work corresponden a Break, Producción y Back Office).
  * La matriz de cada sub segmento queda en la actividad: requiere sesión ACD, día completo / parcial, **requiere AP**,
    pagado (nómina), pagado por el cliente (obligatorio / opcional) y áreas que revisan (ECD, WFM, IT, HR, FIN, OM, UM).
    **La matriz del archivo venía vacía**: los valores iniciales son por categoría (p. ej. los permisos de RRHH exigen AP
    y no exigen sesión) y se ajustan en **WFM › Actividades**, que ahora filtra por categoría y busca.
  * En la planificación, un **desplegable de categorías** junto a la barra muestra solo los segmentos de la categoría
    elegida (se recuerda en el navegador); los que exigen AP llevan un punto rojo y lo dicen en el tooltip. Las
    actividades del sistema no se ofrecen en la barra (SQL 50074 las rechaza si no las inserta el sistema).
* **Restricción por AP**: WFM coloca libremente los segmentos operativos; exigen el folio de una **AP aprobada del
  mismo empleado** (`folio` en el segmento, `adh_schedule_segment.personnel_action`):
  * las actividades marcadas «requiere AP» (respaldo legal ante el Ministerio de Trabajo);
  * los segmentos que cubren el **día completo** del turno;
  * los **cambios mayores**: duración ≥ `ap_required_seconds` de la Management Unit (4 h por defecto; 0 = solo los dos
    casos anteriores). Ambos umbrales se editan en «Grilla» de la planificación.
  * La programación masiva no acepta actividades que exigen AP. SQL Server: `TR_adh_schedule_segment_rules` (50072).
* **Ventana flotante de detalle**: al hacer clic en una actividad o en el pre-contenedor se abre un modal (reemplaza a
  la barra de edición superior) con la tabla del día: actividad, inicio, fin, duración, notas / observaciones y respaldo
  (origen, AP, quién la programó). `GET /api/v1/adherence/day/?employee=&date=`.
  * **WFM con `wfm.manage`**: edita, agrega, elimina y reemplaza (Lateness / ausencia con AP; la ausencia puede
    reemplazarse completa con un permiso de día completo).
  * **Modo lectura** para el propio agente, su **supervisor** (cadena de mando del roster en la fecha) y WFM de solo
    lectura: las correcciones de segmentos se envían a la **cola de aprobación de WFM**; los cambios del **día completo**
    no pasan por la cola y llevan al flujo de **AP**.
  * Agentes y supervisores lo usan desde **ACD › Mi plan y mi equipo** (`/acd/my-plan`, `GET /api/v1/adherence/my-plan/`).
* **Cola de aprobación WFM** (`/wfm/requests`, `adh_change_request`, vista `vw_AdhChangeRequest`): agregar, cambiar o
  quitar segmentos, con el antes, la propuesta, la AP de respaldo y el motivo. WFM aprueba (se aplica al plan con origen
  «solicitud aprobada» y se recalcula la adherencia) o rechaza con comentario; nadie aprueba su propia solicitud y quien
  la pidió puede anularla. API: `GET|POST /api/v1/adherence/requests/`, `POST …/{id}/decide/` y `…/{id}/cancel/`.
* Todo queda en el **audit trail** de la línea: Lateness / ausencia detectados, reemplazos con AP, solicitudes y su
  resolución (aprobaciones). `vw_AdhScheduleSegment` agrega origen, bloqueo, AP de respaldo, departamento y categoría.

## Planilla automática y boletas físicas (Fase 20)

> Desde la **Fase 21** el motor calcula **por horas** (ver más abajo): los descuentos por días de esta sección (ausencia, Lateness, permisos y tiempo no laborado) quedaron retirados, porque las horas no laboradas simplemente no se pagan.

* **Parámetros salariales** (`/payroll/settings`, `pay_setting`, por país y con vigencia): días por mes (30), horas por
  día (8), recargo de horas extra (100 %), prima de vacaciones (30 %) y qué penalizaciones se descuentan: Unjustified
  Absence (un día) con **pérdida del séptimo día** por semana, Lateness no reemplazado con AP, permisos sin goce
  (actividades no pagadas, salvo el almuerzo) y tiempo no laborado (programado pagado que la adherencia no validó). Una
  vigencia que respaldó una planilla cerrada ya no se edita: se crea otra (la anterior se cierra el día previo).
  * Retenciones de ley en `fin.catDeductionType` / `fin.DeductionBracket` (SQL-first): ISSS y AFP laborales y
    patronales, Renta por tramos e **INSAFORP** patronal (1 %). Se agregan la tabla de Renta **quincenal** (la mensual
    entre dos) y, si una frecuencia no tiene tramos, se proyecta la mensual. Un cambio de tasa, tope o tabla es una
    **nueva vigencia** desde la pantalla. El recargo nocturno sale de la regla de nocturnidad del país (Fase 8).
  * **Valores de referencia**: valídelos contra la normativa vigente antes de producción.
  * Conceptos de la boleta (`pay_concept`): salario, descuentos de tiempo, nocturnidad, horas extra, bonificación, prima
    de vacaciones y descuentos por AP, con su afectación a ISSS / AFP y a Renta (editable).
* **Motor de cálculo** (`apps/payroll/engine.py`, funciones puras): salario del periodo proporcional a los días
  contratados (salario base **mensual** del expediente); salario diario = mensual / 30; hora = diario / 8.
  * Insumos por **ventana de asistencia** (los cortes internos mapeados al periodo de pago, Fase 11):
    * Web Timer y demás registros: minutos y nocturnidad.
    * Segmentos de WFM: Unjustified Absence, Lateness, permisos sin goce.
    * Adherencia guardada: Out of Adherence sin estado pagado.
    * **AP aprobadas** con el nuevo efecto «Concepto de planilla».
  * Tipos de AP sembrados: `AP_HORAS_EXTRA` (diurnas / nocturnas; sin ella el Unpaid Excess Login no se paga),
    `AP_BONIFICACION`, `AP_VACACIONES` (prima) y `AP_DESCUENTO` (después de retenciones; el líquido nunca es negativo).
    Una AP se paga una sola vez (índice único y SQL 50093); si su planilla ya cerró, la toma la siguiente.
  * ISSS / AFP con tope proporcional al periodo; Renta sobre devengado gravado − ISSS − AFP laborales.
* **Flujo** (`/payroll`, una planilla por periodo de pago del ciclo predeterminado):
  * **Calcular** se puede repetir mientras la planilla esté abierta.
  * **Cerrar** exige los cortes de asistencia cerrados y un cálculo posterior a su cierre. Congela la planilla y
    **genera en masa las boletas** (folio, contenido congelado con sello SHA-256) y un **lote por departamento**
    (centro de costos).
  * **Pagar**; **anular** (solo abierta) libera las AP.
  * También: `python manage.py payroll_calculate --cycle SV_QUINCENAL --date AAAA-MM-DD [--approve]`.
  * Resultado en `fin.Payroll` / `fin.PayrollDetail` / `fin.PayrollDeduction` y el desglose por línea en
    `pay_payroll_line` (origen y AP de cada monto). Exportación CSV y vista `vw_PayPayrollDetail` (ISSS, AFP y Renta por
    colaborador).
* **Inventario de boletas físicas** (`/payroll/inventory`, solo RRHH / Administración, `pay_payslip` y
  `pay_payslip_batch`): lotes por quincena / mes y departamento con su avance y ubicación de archivo. Cada boleta lleva
  su estado:
  * **impresa** o faltante por imprimir, con el número de impresiones;
  * **firmada en físico** o pendiente de firma, con la fecha de firma;
  * **archivada**, con su ubicación.
  * Acciones masivas y reversión con motivo; todo queda en la auditoría.
  * Filtros por año, mes, quincena, departamento, impresión, firma y archivo. Vista `vw_PayPayslipInventory`.
  * Impresión en el navegador, una boleta por página con el espacio de firma: «Imprimir y registrar» suma la impresión.
* **SQL Server**:
  * 50090: una planilla cerrada o pagada no cambia su detalle, retenciones ni líneas.
  * 50091: el estado solo avanza y los totales de una planilla cerrada no cambian.
  * 50092: las boletas solo nacen de una planilla cerrada, coinciden con su línea, no se eliminan y su contenido no
    cambia; solo cambia el control físico.
  * 50093: la AP de una línea debe estar aprobada, ser del mismo empleado y ser un concepto de planilla.

## Refinamiento operativo, ciclo de vida y nómina por horas (Fase 21)

* **Menú lateral**: cada módulo se expande (▲) o se contrae (▼); por defecto solo el módulo activo y se recuerda en el
  navegador.
* **Formato dual de tiempos**: el selector «Tiempos» de la barra superior alterna al instante entre **HH:MM:SS** y
  **horas decimales** (dos decimales) en todos los totales: horas teóricas vs reales, adherencia, planificación, reporte
  de estados ACD, planilla, boletas, feriados y horarios (`src/app/timeFormat.js`).
* **Ciclo de vida por AP** (pestaña «Ciclo de vida» del expediente, `pa_employment_event`, vista `vw_EmployeeTenure`):
  * `AP_SUSPENSION` (Generalista de RRHH → Administración): el colaborador queda **Inactivo** los días indicados, sin
    goce (la planilla no programa ni paga esos días) y su **antigüedad se congela**; vuelve a Activo solo al terminar
    (tarea diaria `apply_due_personnel_actions`). No se cruzan dos suspensiones.
  * `AP_TERMINACION` (motivo, **indicador interno de recomendación de recontratación** y observaciones; solo la ve
    quien administra empleados): estado Terminado en la fecha efectiva y apertura automática de su **liquidación**.
  * `AP_REINGRESO`: reactiva a un terminado; la fecha efectiva es su nueva fecha de ingreso y la **antigüedad se
    reinicia** (el historial conserva el ingreso y la terminación anteriores). Si su última terminación **no lo
    recomendó**, la validación emite una **alerta formal** con su historial y antecedentes; el generalista debe
    reconocerla expresamente para continuar (queda en la auditoría).
  * SQL Server 50094: el historial laboral no se elimina ni cambia (solo se registra la reactivación automática).
* **Roles por tipo de AP** (`/personnel-actions/roles`): qué perfiles **elaboran** cada tipo (Generalista de RRHH, WFM,
  Administrador) y qué rol **firma** cada paso; con «firma estricta» el Administrador tampoco firma pasos de otro rol.
  Solo el Administrador la cambia.
* **Motor de planilla 100 % por horas** (estándar BPO, `apps/payroll/engine.py`):
  * Salario del periodo = mensual × 50 % (quincena) × fracción contratada y no suspendida.
  * **Rate por hora** = salario del periodo ÷ **horas programadas** del corte interno (horario vigente de las AP).
  * Salario = rate × **horas reales pagables**: lo validado por la adherencia guardada o, sin ella, el Web Timer hasta lo
    programado. Los días de vacaciones (AP) se pagan como programados; el exceso sin AP de horas extra no se paga.
  * Recargos: nocturnidad (rate × 25 % de la regla del país, 19:00–06:00), horas extra de AP (× 2; nocturnas × 2 ×
    1.25) y feriado laborado (rate × recargo del feriado: pago doble). Luego ISSS, AFP y Renta (DGII) por tramos.
  * **Séptimo día opcional**: apagado por defecto; cada **cuenta** (cliente del roster) lo activa en Parámetros
    salariales › Séptimo día por cuenta (`pay_account_rule`).
* **Pre-cierre**: el motor se corre las veces que haga falta antes del cierre (manual o diario con
  `python manage.py payroll_calculate --scheduled`, desde N días antes del fin del corte; p. ej. desde el 10 para el corte
  que cierra el 24). Cada corrida queda en `pay_payroll_iteration` y publica la **boleta preliminar** en el portal del
  colaborador (**Mi portal › Mis boletas**). El agente reporta **excepciones** a su Team Manager vigente (o Planillas las
  atiende en **Mi portal › Excepciones de planilla**); el **cierre (freeze) exige que no queden abiertas**.
* **Calendario de feriados** (`/scheduling/holidays`, `hol_holiday`; nacionales de El Salvador 2026–2027 sembrados):
  si un colaborador labora en un feriado se genera automáticamente su **Holiday Segment** (`hol_holiday_segment`, el
  contenedor del turno con las horas laboradas). Va aparte de los segmentos de WFM: no cambia la adherencia y en un
  feriado la conciliación **no marca Unjustified Absence ni Lateness**. SQL 50097: un feriado con Holiday Segments no
  cambia de fecha ni se elimina. También `python manage.py holiday_segments --from --to`.
* **Liquidaciones e indemnizaciones** (`/payroll/settlements`, separadas de la planilla ordinaria):
  * Se abren al aplicarse la AP de terminación. Indemnización por despido sin causa (30 días por año, tope 4 salarios
    mínimos, mínimo 15 días), prestación por renuncia voluntaria (2 o más años: 15 días por año, tope 2 mínimos),
    vacaciones proporcionales con prima y aguinaldo proporcional (15 / 19 / 21 días; exento hasta 2 mínimos), con
    ajustes manuales y retenciones de ley. Los días laborados hasta la terminación los paga la planilla ordinaria.
  * Aprobar **sella** el contenido (SHA-256, SQL 50095). Se pagan en **lotes propios** (cheque con número correlativo o
    transferencia): cerrar → imprimir cheques / comprobantes con el **monto en letras** → pagado (SQL 50096).
  * Parámetros (salario mínimo, días y topes) en Parámetros salariales; **valores de referencia** a validar.

## UI minimalista, APs unificadas, roster automático y planilla por cortes (Fase 22)

* **Sistema › Apariencia y configuraciones visuales** (`/system/appearance`, para todos): el formato de tiempos
  (HH:MM:SS u horas decimales) sale de la barra superior y vive aquí junto al **modo día / noche** (o según el sistema),
  la **densidad** de la interfaz y la **paleta corporativa** (Azul, Verde azulado, Vino, Grafito, Bosque o personalizada),
  que el Administrador fija para todos (`sys_platform_settings.brand_palette`, entregada en `/system/client-config/`).
* **Menú lateral**: chevron minimalista (media rombo sin relleno, SVG) que gira al expandir.
* **Retiro del mock «Asistencias y downtimes»**: se eliminaron la página, la app `apps.wfm`, el script 030 y las semillas;
  las tablas `wfm.*` y el esquema se borran con `system.0009` / `database/scripts/097_drop_wfm_attendance_mock.sql`.
  La asistencia vive en la grilla IEX, la adherencia y la asistencia automática.
* **Centro de notificaciones** (campana de la barra superior y **Mi portal › Notificaciones**, sondeo de 30 s;
  `GET/POST /system/notifications/`, lecturas en `sys_notification_read`): AP pendientes de **su** firma, planillas y
  liquidaciones por aprobar, excepciones de planilla y solicitudes de WFM pendientes, **altas** de empleados de los
  últimos 7 días bajo su jerarquía (o todas con `hcm.manage`) y **ausentismo (no-shows)** del día de su equipo.
* **Justificaciones y permisos en el módulo regular de AP** (registro en **Acciones de personal › Justificaciones y
  permisos**; `/wfm/justifications` redirige allí). Nuevos tipos de campo `TIME`, `ACTIVITY` (sub-segmento del Time
  Utilization, filtrable por prefijo) y `ROSTER`; nuevos efectos:
  * `JUSTIFY` — **Justificación de tiempo** (desde / hasta, actividad opcional, pagado): al aprobarse registra la ventana
    en la adherencia (`adh_exception`) y, con actividad, coloca el segmento en la grilla (reemplaza lo que hubiera,
    incluso Lateness / ausencia).
  * `LEAVE` — **Permiso con goce** (`AP_PERMISO_CON_GOCE`, Paid Time Off) y **sin goce** (`AP_PERMISO_SIN_GOCE`,
    Unpaid Time Off): **día laborable completo** (todo el turno de cada día del rango, hasta 31 días) o **por horas**.
    Con goce se paga como programado (también sin adherencia guardada); sin goce no se paga pero no cuenta como
    Unjustified Absence ni Lateness.
* **Roster automático por AP** (efecto `ROSTER` y el ajuste salarial): `AP_PROMOCION` (puesto, salario, Team Manager,
  línea) y `AP_CAMBIO_ORGANIZACIONAL` (cliente, marca, línea, sub-línea, Team Manager, puesto, tipo de contrato y centro
  de costos) actualizan el **roster temporal** (historial bitemporal, motivo = folio) y el **expediente** (salario base,
  centro de costos) en su fecha efectiva. Nuevos atributos del roster: Puesto y Tipo de contrato. Los valores se
  validan contra el roster al elaborar la AP.
* **Planilla alineada a los cortes internos**: el **rate por hora** = 50 % del mensual ÷ horas programadas del **corte
  completo** (el horario se proyecta a los días previos al ingreso o posteriores al retiro); el colaborador cobra rate ×
  sus horas pagables (prorrateo exacto de los actuals, línea «Horas programadas del corte completo»).
* **Validación con el Optimum ES Payroll Hours**: mismas fórmulas (rate, nocturnidad = rate ÷ 4, horas extra × 2,
  feriado, ISSS 3 % con tope, AFP 7.25 %, Renta quincenal por tramos, redondeo a 2 decimales) y **tipos de contrato**:
  PERMANENTE (ISSS + AFP + tabla), PERMANENTE JB (sin ISSS), SERVICIOS PROFESIONALES (Renta fija 10 %, sin ISSS / AFP)
  y SERVICIOS PROF. INTERNACIONAL (Renta 20 %). El catálogo del Time Utilization Project coincide con las actividades.
* **Boletas en PDF** (generador nativo, sin dependencias): `GET /payroll/payslips/{id}/pdf/`,
  `/payroll/runs/{id}/employees/{code}/pdf/` (preliminar si aún no hay boleta) y `/payroll/me/payslips/{final|preliminary}/{id}/pdf/`.
  Botones «Descargar PDF» en el desglose, el inventario y el portal.
* **Moneda por país**: símbolos dinámicos ($, Q, MX$, COL$) en planillas, boletas, liquidaciones y monto en letras
  (dólares, quetzales, pesos).
* **Sistema › Datos y modelo ER** (Administrador): filas, espacio de datos / índices, columnas, FK y triggers por tabla
  (procedimiento `dbo.usp_SystemTableStats`) y el **ERD interactivo** (SVG: desplazar, acercar, mover tablas y resaltar
  relaciones; `dbo.usp_SystemTableColumns`, vista `dbo.vw_SystemForeignKeys`).

## Seguridad jerárquica, paleta dual, marca y calendario de feriados (Fase 23)

* **Selector jerárquico en las AP**: el formulario ya no pide el ID a mano; un buscador (typeahead por nombre, ID o
  documento; `GET /personnel-actions/employees/picker/?q=`) ofrece **únicamente** a los colaboradores bajo la jerarquía
  **directa o indirecta** del usuario (función de SQL Server `dbo.fn_EmployeesUnderLeader`: CTE recursiva sobre
  `ops_leader` + agentes de sus Team Managers en el roster vigente). El servidor rechaza cualquier otro (`out_of_scope`),
  y nadie se elabora AP a sí mismo. El Administrador ve a toda la organización; las áreas de soporte **sin equipo a
  cargo** (por defecto RRHH y WFM) también, configurable en `/admin/` › Parámetros (`ap_full_scope_roles`; vacío =
  estrictamente jerárquico).
* **Paleta dual** (Sistema › Apariencia): la **global por defecto** (Administrador; `sys_platform_settings.brand_palette`)
  es el respaldo de fábrica; cada usuario puede elegir **su paleta personal** (y modo, densidad y formato de tiempos),
  guardada en su **perfil** (`sys_user_preference`, `GET/PUT/DELETE /system/appearance/me/`) y aplicada en cualquier
  equipo. «Restablecer la predeterminada» vuelve a la global.
* **Django Admin con la identidad del ERP** (`backend/templates/admin/base_site.html` + `apps.system.theme.admin_theme`):
  la misma paleta efectiva del usuario (personal o global) en barra, enlaces, botones y migas, también en modo oscuro;
  el modo sigue la preferencia del perfil; logotipo de letras blancas y favicon de la mariposa.
* **Calendario de feriados en React** (`/scheduling/holidays`): vistas **Mes** (clic en un día libre para agregar, en un
  feriado para editar, desactivar o eliminar) y **Año** (12 meses), más la lista con Holiday Segments; **copiar al año
  siguiente** (`POST /holidays/copy-year/`, procedimiento `dbo.usp_HolidayCopyYear`, que recalcula Jueves, Viernes y
  Sábado Santo con `dbo.fn_EasterSunday`); vista `dbo.vw_HolidayCalendar`.
* **Logos corporativos** (originales en `logos/`; `python manage.py brand_assets` genera las versiones optimizadas en
  `frontend/public/brand/` y `apps/system/static/brand/`; el logotipo de la barra se limpia del «polvo» del recorte):
  * `favicon_logo.png` → favicons del ERP y del admin, ícono de la app y marca reducida del menú lateral;
  * `app_header_logo.png` (letras blancas) → barra superior del ERP y del Django Admin (y el acceso en modo noche);
  * `doc_header_logo.png` (fondo blanco) → cabecera de las boletas (pantalla, impresión y **PDF**), los cheques de
    liquidación y el acceso en modo día. Los documentos se ven siempre como papel blanco, también en modo noche.

## Anuncios, planilla por cortes internos y evidencias en las AP (Fase 24)

* **Logotipo → Anuncios de la empresa** (`/announcements`): el logotipo de la barra superior y el inicio (`/`) llevan a la
  página de comunicados corporativos (visible para todo usuario). Es una **maqueta temporal**: el aviso general vigente
  (`/admin/` › Parámetros) es real; los comunicados son contenido de ejemplo del frontend (no se guardan en la base) hasta
  que exista el módulo de comunicaciones.
* **Planilla alineada a los cortes internos** del ciclo predeterminado: las horas efectivas, *actuals* y cumplimiento se
  cuentan **del 25 al 9 y del 10 al 24**; el devengo y la fecha de pago siguen en la quincena 1–15 / 16–fin que contiene
  el cierre del corte. La migración `scheduling/0010` fija la regla (inicio 10, fin de la primera ventana 24) en los ciclos
  quincenales predeterminados que derivaban el corte del periodo y **realinea sus cortes abiertos**
  (`scheduling.services.realign_cutoffs`, también como acción del admin «Realinear los cortes abiertos a la regla del
  ciclo»): los cortes cerrados o pagados en una planilla cerrada no se tocan y la primera ventana nueva es de transición.
  La elegibilidad de la planilla incluye a quien solo laboró dentro del corte (p. ej. se retiró el 28 y el corte 25–9 se
  paga en la quincena siguiente). **Recalcule las planillas abiertas** después de realinear.
* **Adjuntos en las AP** (`pa_action_attachment`): imágenes PNG / JPG, PDF y documentos de Office (DOCX, XLSX, DOC, XLS),
  validados por extensión, tamaño (`/admin/` › Parámetros › `max_attachment_mb`, 10 MB por defecto) y **firma binaria**;
  bytes originales en el almacenamiento privado con su SHA-256. Se adjuntan al elaborar la AP (se suben antes de enviarla
  a aprobación) o desde el detalle mientras está en borrador o en aprobación (quien la elabora o quien firma el paso en
  curso). Nunca se borran: se **retiran con motivo**. En SQL Server: sin DELETE (50110), sin adjuntos en AP resueltas o
  anuladas (50111), contenido inmutable (50112), retiro con motivo e irreversible (50113); vista
  `dbo.vw_PaActionAttachment`. API: `POST /personnel-actions/{folio}/attachments/`,
  `GET /personnel-actions/attachments/{id}/content/` (`?download=1`), `POST /personnel-actions/attachments/{id}/remove/`.
* **Detalle de la AP con pestañas** (como el expediente): **Detalle**, **Evidencias** (miniaturas, categoría, tamaño,
  SHA-256, quién y en qué etapa se adjuntó, retirados), **Firmas** (cadena con verificación) y **Auditoría** (bitácora de
  la AP: elaboración, envío, firmas, adjuntos, aplicación y anulación, con usuario, fecha e IP, y el sello SHA-256). Los
  listados de AP (general y del expediente del colaborador) muestran cuántas evidencias tiene cada una.

## Cierre: sesiones, esquemas por módulo, periódico virtual y boleta diaria (Fase 25)

* **Estado del sistema › Usuarios y sesiones** (Administrador, se actualiza cada 15 s): sesiones activas en tiempo real
  (usuario, rol, IP, navegador, inicio, última actividad e inactividad, con «Cerrar sesión»), usuarios totales, activos,
  bloqueados, inactivos y con cambio de contraseña pendiente, intentos fallidos y bloqueos de las últimas 24 h, la política
  de sesión vigente y enlaces al panel. API: `GET /system/overview/`, `POST /system/sessions/{id}/close/`.
* **Bloqueo de cuentas**: tras N contraseñas incorrectas consecutivas (`/admin/` › Parámetros › `max_failed_logins`, 5 por
  defecto; 0 = no bloquear) la cuenta queda **bloqueada** (`locked_at`, `lock_reason`) y sus sesiones se cierran; no entra
  ni con la contraseña correcta (backend `apps.accounts.backends.LockAwareModelBackend`). Todo queda en la auditoría.
* **Usuarios en el panel de Django** (`/admin/accounts/customuser/`): se editan nombre, correo, rol, cuenta activa, cambio
  de contraseña obligatorio y bloqueo (con motivo); filtros por acceso (bloqueadas, inactivas, cambio pendiente, con sesión
  activa) y acciones masivas (desbloquear, bloquear, exigir cambio de contraseña, cerrar sesiones, activar / desactivar).
  Mismas reglas que la API: roles otorgables según quien edita, nunca sobre la propia cuenta, nunca sin un administrador
  activo y solo un superusuario gestiona otro superusuario. Las cuentas se siguen **creando** desde la aplicación.
* **Esquemas por módulo en SQL Server** (`system/0015_phase25_module_schemas`, reversible): las tablas se mueven con
  `ALTER SCHEMA … TRANSFER` (índices, FK, restricciones y triggers incluidos) y las vistas, procedimientos, funciones y
  triggers se recrean en su esquema con sus referencias reescritas. `sec` seguridad · `adm` plataforma · `hcm` capital
  humano y General IDs · `org` estructura operativa y roster · `wfm` horarios, tiempo, cortes, feriados y adherencia ·
  `acd` ACD · `pa` acciones de personal · `fin` planillas · `com` comunicados · `core` catálogos. En `dbo` solo quedan las
  tablas internas del framework de Django (`auth_*`, `django_*`) y los diagramas de SSMS. Los modelos declaran
  `db_table = "[esquema].[tabla]"`; el motor `apps.common.db` (mssql-django con introspección por esquema) permite que las
  migraciones futuras sigan funcionando sobre esas tablas. El propósito de cada objeto queda en SQL Server como
  `MS_Description` (catálogo en `apps/system/sqlcatalog.py`).
* **Datos y modelo ER**: sin los vínculos redundantes debajo de las tarjetas (el filtro de módulo es el desplegable, con
  tablas y filas por módulo) y una pestaña nueva **«Vistas, SP y triggers»**: estado (activo, deshabilitado o con
  referencias sin resolver), esquema, tipo, tabla y eventos de cada trigger, propósito, fecha de modificación y, con
  `VIEW SERVER STATE`, las ejecuciones desde el último reinicio (vista `adm.vw_SystemSqlObject`, `GET /system/data/objects/`).
* **Periódico virtual** (`/announcements`, pantalla de bienvenida del logotipo): comunicados reales por categoría
  (noticias, blog, formularios, avisos de RRHH, planillas, cultura, operaciones, **seguridad** y **cambio organizacional**),
  fijados, audiencia por rol, vigencia y enlace (obligatorio en formularios). **Publicar comunicado** (`announcements.manage`:
  Administrador y RRHH) con borradores, vista previa, edición y archivo. Los comunicados **críticos** (seguridad y cambios
  organizacionales) exigen **acuse de recibo**: cada confirmación guarda fecha, IP y la huella SHA-256 del texto, y al
  publicarse su contenido queda **congelado** (SQL 50122). Los pendientes aparecen en un aviso permanente y en el centro de
  notificaciones. **Cumplimiento** (`announcements.compliance`): resumen y reporte por usuario (confirmado, fuera de plazo,
  pendiente, vencido) con CSV y el historial de fotos; **reporte automático** diario y al vencer el plazo con
  `python manage.py announcements_compliance` (programarlo a diario), además de una foto al archivar. SQL Server: acuses
  inmutables (50120) y solo sobre comunicados publicados con acuse (50121), sin borrar publicados (50123), fotos inmutables
  (50124). La maqueta de la Fase 24 se retiró.
* **Boleta desglosada por día** (portal «Mis boletas» y detalle de planilla): cada fecha de los **cortes internos**
  (p. ej. 25/09–09/10) con su tipo de día (laborado, parcial, feriado, vacaciones, ausencia, descanso, suspensión…), horas
  programadas, pagables y nocturnas, y su **traducción exacta a dinero**: salario por horas, vacaciones, nocturnidad,
  recargo de feriado y séptimo día, repartidos al centavo desde las líneas de la boleta (la suma de los días cuadra con
  ellas); además, otros devengos (AP) y retenciones. Se guarda en `fin.pay_payroll_day` al calcular (bloqueada al cerrar la
  planilla, 50099) y se congela en el contenido de la boleta final. **Recalcule las planillas abiertas** para generar su
  desglose diario.

## Login, datos de prueba, limpieza técnica y ayudas en tooltip (Fase 26)
* **Login rediseñado** (referencia `login-page-example-saleskip.png`): panel de marca con degradado de la paleta
  corporativa (respeta la paleta global / personal y el modo noche), saludo, propuesta de valor y el formulario a la
  derecha con campos de línea inferior, mostrar / ocultar contraseña y aviso de Bloq Mayús. En móvil el panel se reduce a
  una franja superior. El cambio obligatorio de contraseña usa el mismo marco (`auth/AuthShell.jsx`).
* **Datos de prueba**: `python manage.py demo_data` (desde `backend/`) genera con los mismos servicios de la interfaz
  (validaciones, AP, triggers y auditoría):
  * 3 clientes, 5 marcas, 3 líneas de negocio y 7 sub-líneas (sincronizados con el roster);
  * 28 colaboradores con expediente completo (datos personales, ISSS / AFP / NIT, banco, contacto de emergencia,
    documentos obligatorios con imagen de muestra «sin validez legal» y fotografía), Primera AP de horario aprobada y
    roster (cliente, marca, línea, sub-línea, Team Manager, puesto, tipo de contrato);
  * cadena de mando Operations Director → Operations Manager → 2 Account Supervisors → 4 Team Managers → 16 agentes
    (Tier 1 y Tier 2) en el grupo ACD general;
  * segmentos de la grilla (breaks, almuerzo, reunión de equipo, coaching y capacitación) del corte **10–24 de
    noviembre de 2026** y la asistencia ACD de los días ya transcurridos;
  * 8 comunicados del periódico virtual (seguridad y cambio organizacional con acuse obligatorio).

  Escribe `accesos_prueba.txt` en la raíz con usuario y contraseña de un representante por rol (RRHH, WFM, Director,
  Manager, Account Supervisor, Team Manager, Agente Tier 1 y Tier 2) y la lista completa de cuentas. **No se crea ningún
  Administrador de prueba.** El archivo está en `.gitignore`. Es idempotente: lo existente se reutiliza y cada ejecución
  asigna contraseñas nuevas. `--dry-run` valida todo y revierte; `--output RUTA` cambia la ubicación del archivo.
  Lo generado se identifica por el dominio de correo `@demo.metamorph.test` y los usuarios `demo.*`.
* **Sin metadatos técnicos para el usuario final**: las páginas ya no muestran vistas, tablas, SP, triggers ni comandos
  de consola; los mensajes de error dicen «El sistema rechazó…» (sin nombres de restricciones ni el texto del motor, que
  queda en el log del servidor). `GET /health/db` solo devuelve base, versión, tablas faltantes y detalle del error al
  Administrador. Los detalles siguen disponibles en Sistema › Datos y modelo ER y en `/admin/`.
* **Ayudas de campo en tooltip** (`components/ui/FieldHint.jsx`): los textos largos bajo las cajas de texto pasan a un
  ícono «i» en la esquina del rótulo; la explicación aparece al pasar el cursor sobre el campo o al enfocarlo, encima del
  rótulo (no tapa lo que se escribe). Los formularios en cuadrícula quedan simétricos; los errores de validación siguen
  visibles bajo el campo.

## Boletas por corte, roster jerárquico, autocompletado y grilla IEX diferida (Fase 27)

**Boletas por corte (portal › Mis boletas).** Nueva sección «Historial por corte de asistencia»: cada corte interno en el
que el colaborador estuvo activo (ventana del corte ∩ [ingreso, baja u hoy]) es una sub-sección desplegable con su
desglose diario, del más reciente al más antiguo. Estado por corte: *Pagado (boleta final)*, *Preliminar* (boleta
publicada antes del cierre) o *Pendiente de cálculo*. Filtro por año, 3/6/12/24 cortes por página y paginación servida
por el backend (`GET /api/v1/payroll/me/cutoffs/?year=&page=&page_size=`). Las boletas finales también se filtran por año
y se paginan (`/payroll/me/payslips/?year=&page=`, bloque `final_page`), y el desglose diario de una boleta que cubre
varios cortes se navega corte por corte («Ver los N cortes» los muestra todos).

**Datos de prueba con jerarquía real.** `python manage.py demo_data` ahora además:
* completa el roster de cada agente con la wave de capacitación y las fechas de capacitación, nesting y salida a
  producción, y el tipo de documento de reportes (DUI) para todos;
* registra General IDs: *Payroll Tool ID* (`PT######`) para los 28 colaboradores y *ACD ID* por cuenta (cliente y marca;
  `NV`/`AU`/`VX` + número) para los 16 agentes;
* verifica que cada agente quede bajo SU Team Manager con la cadena completa (Team Manager → Account Supervisor →
  Operations Manager → Director); si no, aborta y revierte.

**Autocompletado de colaboradores.** Componente `EmployeeAutocomplete` (typeahead con teclado: flechas, Enter, Esc) que
busca por nombre, apellidos, ID corporativo o documento sin distinguir acentos
(`GET /api/v1/hcm/employee-lookup/?q=&scope=acd`). Reemplaza los campos donde se digitaba el ID a mano: Planificación WFM
(vista del agente), Adherencia, Reporte de estados ACD, Grupos ACD (asignar agente), Justificaciones y Cadena de mando
(registrar líder). Las AP siguen con su selector jerárquico de la Fase 23.

**Grilla IEX con carga diferida.** La grilla de grupo ya no se consulta al entrar: muestra un estado inicial con acceso
rápido por Management Unit y solo dispara la consulta cuando hay al menos un filtro (Management Unit, cliente/marca,
cadena de mando o búsqueda). El backend rechaza la consulta sin filtros (`filters_required`), resuelve los filtros como
subconsultas en SQL Server (sin listas de ids, apto para plantillas de miles de agentes) y devuelve los agentes por
páginas de 25/50/100/200 (`page`, `page_size`; bloque `paging`): solo la página pedida se evalúa contra el ACD.

## Fuera de alcance (por ahora)
* JWT / SSO (la API usa sesión + CSRF; el SPA no maneja tokens).
* Restablecimiento de contraseña por correo (no hay servicio de correo; el reseteo lo hace RRHH/Administración).
* Listado general de usuarios en React: las cuentas se gestionan desde el expediente de cada empleado.
  Las cuentas técnicas sin empleado se crean con `createsuperuser` o la API `/users/`.
* Edición de plantillas desde React (se administran en `/admin/`) y procesamiento asíncrono de lotes
  (hoy síncrono, límite 5000 filas).
* Documentos del expediente en PDF (la Fase 5 acepta solo imágenes PNG/JPG/JPEG; las boletas sí se descargan en PDF
  desde la Fase 22) y antivirus en las cargas.
* Notificaciones push / correo (el centro de notificaciones consulta cada 30 s) y la «Otras variables» con Renta del
  10 % del Excel de referencia (las bonificaciones se configuran por concepto).
* Pantalla React para administrar catálogos (clientes, marcas, líneas, bancos, herramientas y tipos de ID): hoy en
  `/admin/` (rol Administrador).
  No existe un rol «QA»: los reportes de roster los consultan Administrador, RRHH y WFM.
* Reportes y Power BI (el mock de ingesta `wfm.*` se retiró en la Fase 22). La planilla no calcula el aguinaldo anual de
  diciembre (solo el proporcional de las liquidaciones), el recálculo anual de Renta (junio / diciembre) ni envía
  planillas al ISSS / AFP / banco; los cheques se imprimen en papel en blanco (sin formato del banco).
* Programación exacta del almuerzo y descansos (responsabilidad operativa de WFM).
* AP masivas (un cambio de horario para muchos colaboradores a la vez). Las firmas siguen asignándose por rol; la
  jerarquía (Fase 23) limita a quién se le elabora la AP.
* Terminar antes de tiempo una asignación adicional (hoy rige hasta su `vigente_hasta`; para extenderla se elabora
  otra AP adicional).
* ACD: integración con una plataforma de telefonía real (colas, interacciones, ACW automático), estado Idle por
  inactividad y cierre automático de sesiones abandonadas (hoy el supervisor las cierra desde el tablero).
