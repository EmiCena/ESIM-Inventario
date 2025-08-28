# ESIM Inventario (Django)

Sistema de gestión de préstamos para la Escuela Secundaria de Innovación de Misiones (notebooks, tablets y alargues), con:
- Préstamo y entrega “en el momento” (login requerido).
- Medición por horas y dashboard con filtros por tipo, nivel, carrera y año.
- Reservas y mantenimiento básico.
- Notificaciones a Discord (webhook) y bot con comandos slash.
- Estilo visual alineado al sitio actual.

Demo de rutas
- Inicio: /
- Préstamo: /prestamo/
- Entrega: /devolucion/
- En uso ahora (solo operadores/staff): /prestamos/activos/
- Dashboard: /dashboard/
- Admin: /admin/
- Registro/Login: /accounts/signup/ y /accounts/login/
- Vincular Discord: /accounts/discord/

Requisitos
- Python 3.10+
- pip y venv
- (Opcional) Git
- Windows, Linux o macOS. Nota: en Windows, las tareas programadas se corren con el Programador de tareas.

Instalación rápida
1) Clonar y dependencias
```bash
git clone <tu-repo> esi-inventario
cd esi-inventario
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2) Variables de entorno
```bash
cp .env.example .env
```
Editar .env y completar si hace falta:
- SECRET_KEY: algo aleatorio (en dev podés dejar el default).
- DEBUG=True en desarrollo.
- TIME_ZONE=America/Argentina/Buenos_Aires
- JOIN_CODE_SEC=SEC-123, JOIN_CODE_SUP=SUP-123, JOIN_CODE_STAFF=STAFF-123 (para registro por nivel).
- DISCORD_WEBHOOK_URL=URL del webhook del canal (opcional).
- DISCORD_BOT_TOKEN=token del bot (opcional).
- DISCORD_GUILD_ID=ID del servidor (opcional pero recomendado para que aparezcan al instante los slash).

3) Base de datos y datos iniciales
```bash
python manage.py migrate
python manage.py seed_items        # Crea NB-01..15, TB-01..05, AL-01..06
python manage.py bootstrap_roles   # Crea grupos y usuario operador/operador123
python manage.py createsuperuser   # (opcional) admin
```

4) Datos de prueba (para ver el dashboard)
```bash
python manage.py seed_fake_data
```

5) Levantar
```bash
python manage.py runserver
```
Entrar a http://127.0.0.1:8000/

Usuarios y permisos
- Registro: /accounts/signup/ (ingresar un “Código de registro” según el nivel; los defaults están en .env).
- Login requerido para Préstamo y Entrega (cualquier usuario logueado).
- “En uso ahora” solo operadores/staff. Para dar permisos:
  - Admin → Users → tu usuario → Groups → agregá “OPERADOR” o “STAFF”.
  - o por consola (ejemplo):
    ```python
    python manage.py shell -c "from django.contrib.auth.models import User,Group; u=User.objects.get(username='tu_usuario'); u.groups.add(Group.objects.get(name='OPERADOR'))"
    ```

Frontend (flujo rápido)
- Préstamo: elegí tipo (NB/TB/AL) → número disponible → nivel (y si es SUP, carrera y año) → aula → solicitante (si es SEC) → Registrar.
- Entrega: ingresá el código (ej. NB-03) → Registrar.
- En uso ahora: lista de préstamos activos con quién, dónde y desde cuándo.
- Dashboard: top por horas (colores por tipo), uso por turno, filtros por tipo, días, nivel, carrera, año.

Discord: notificaciones (webhook)
1) Crear webhook en tu canal de Discord
- Channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL.
- Pegá la URL en .env: DISCORD_WEBHOOK_URL=...

2) Probar
```bash
python manage.py shell -c "from core.discord import send_discord; send_discord('Prueba de webhook ✅')"
```

Discord: bot con slash commands
1) Crear la app y el bot
- https://discord.com/developers/applications → New Application.
- Bot → Add Bot → Reset Token → copiá el token → DISCORD_BOT_TOKEN en .env.
- Installation (o OAuth2 → URL Generator):
  - Scopes: bot y applications.commands
  - Permisos: View Channels, Send Messages, Read Message History, (opcional) Embed Links, Attach Files.
  - Usá el Install Link para invitar el bot a TU servidor (necesitás “Manage Server”).

2) DISCORD_GUILD_ID (para que los slash aparezcan al instante)
- En Discord: activá Developer Mode → click derecho al servidor → Copy Server ID → pegalo en .env como DISCORD_GUILD_ID=123...

3) Correr el bot (otra terminal)
```bash
python manage.py discord_bot
```
- Vas a ver: “Conectado como ...” y “Slash sincronizados en guild ...”.

4) Vincular tu usuario y probar
- Web: /accounts/discord/ → Generar token.
- En tu servidor: escribí “/” y elegí los comandos del menú (no como texto):
  - /vincular TOKEN
  - /ping → “Pong 🏓”
  - /disponibles NB
  - /reservar NB
  - /prestar NB-01
  - /status NB-01
  - /entregar NB-01
  - /activos

Notas:
- Las respuestas del bot son ephemerales (solo las ves vos).
- Si los slash no aparecen: verificá el DISCORD_GUILD_ID, reiniciá el bot, y que “Use Application Commands” esté permitido en el canal. Sin GUILD_ID, los comandos globales pueden demorar hasta 1 h.

Tareas programadas (reservas y reportes)
- Expirar reservas: python manage.py expire_reservas
- Reporte semanal: python manage.py weekly_report

Linux
```bash
python manage.py crontab add
python manage.py crontab show
```
Windows (recomendado)
- Programador de tareas → Crear tarea:
  - Acción: cmd
  - Argumentos: /c cd C:\ruta\esi-inventario && C:\ruta\python.exe manage.py expire_reservas
  - Disparador: cada 5 minutos
  - Otra tarea (semanal): manage.py weekly_report (viernes 18:00)

Configuración visual
- Logo: static/img/logo-esi-blanco.png
- Estilos: static/css/theme.css (paleta: lima, fucsia, violeta, cian, naranja).
- Los charts usan Chart.js y se adaptan a mobile.

Estructura (resumen)
- config/: settings, urls, wsgi/asgi
- core/:
  - models.py (Item, Prestamo, Reserva, Mantenimiento, Profile, DiscordLinkToken)
  - forms.py (PrestamoRapidoForm, DevolucionForm, SignupForm)
  - views.py (préstamo, entrega, activos, KPIs, auth)
  - admin.py
  - management/commands/ (seed_items, seed_fake_data, weekly_report, expire_reservas, discord_bot, bootstrap_roles)
  - discord.py (webhook)
  - templatetags/roles.py
- templates/: base y páginas
- static/: css, imágenes

Solución de problemas frecuentes
- “no such table: core_...” → faltan migraciones
  ```bash
  python manage.py makemigrations core
  python manage.py migrate
  ```
- 403 en /prestamo/ → ahora alcanza login (si ves 403, limpiá caché o revisá que no hayas dejado el mixin de operador).
- “Los slash no aparecen” → DISCORD_GUILD_ID mal, permisos del canal, o no se invitó con applications.commands.
- “Application didn’t respond” → el bot no está corriendo; volvé a iniciar python manage.py discord_bot.
- Webhook no envía → verificá DISCORD_WEBHOOK_URL y probá con requests (status 204 es OK).
- “database is locked” (SQLite + OneDrive) → mové el proyecto fuera de OneDrive o pausá la sincronización.

Comandos útiles
```bash
# iniciar servidor
python manage.py runserver

# crear ítems base
python manage.py seed_items

# datos demo
python manage.py seed_fake_data

# dashboard (ver)
http://127.0.0.1:8000/dashboard/

# bot
python manage.py discord_bot

# webhook (test)
python manage.py shell -c "from core.discord import send_discord; send_discord('Ping ✅')"
```
