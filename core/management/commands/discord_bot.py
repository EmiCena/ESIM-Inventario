import os
import django
import discord
from discord import app_commands
from datetime import timedelta
from django.utils import timezone
from asgiref.sync import sync_to_async

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.management.base import BaseCommand
from core.models import (
    Item, Prestamo, Reserva, Profile,
    Nivel, Turno, TipoItem, EstadoItem,
    DiscordLinkToken
)
from core.discord import send_discord

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

intents = discord.Intents.default()

# ---- Helpers async (ORM envuelto) ----

@sync_to_async
def profile_exists_sync(discord_id: int) -> bool:
    return Profile.objects.filter(discord_user_id=str(discord_id)).exists()

@sync_to_async
def get_perfil_dict_by_discord_sync(discord_id: int) -> dict:
    p = Profile.objects.select_related("user").get(discord_user_id=str(discord_id))
    return {
        "user_username": p.user.username,
        "full_name": p.user.get_full_name(),
        "nivel": p.nivel,
        "carrera": p.carrera,
        "anio": p.anio,
        "discord_user_id": p.discord_user_id,
    }

@sync_to_async
def link_user_by_token_sync(token: str, discord_user_id: int):
    # Ya vinculado
    if Profile.objects.filter(discord_user_id=str(discord_user_id)).exists():
        p = Profile.objects.select_related("user").get(discord_user_id=str(discord_user_id))
        return ("already", p.user.username)

    tok = (DiscordLinkToken.objects
           .filter(token=token, used_at__isnull=True)
           .select_related("user").order_by("-created_at").first())
    if not tok:
        return ("bad", None)

    prof, _ = Profile.objects.get_or_create(user=tok.user)  # <— acá aseguramos que exista
    if prof.discord_user_id and prof.discord_user_id != str(discord_user_id):
        return ("user_has_other", tok.user.username)

    prof.discord_user_id = str(discord_user_id)
    prof.save(update_fields=["discord_user_id"])
    tok.used_at = timezone.now()
    tok.save(update_fields=["used_at"])
    return ("ok", tok.user.username)

@sync_to_async
def get_available_codes_sync(tipo: str) -> list[str]:
    return list(Item.objects.filter(tipo=tipo, estado=EstadoItem.DISPONIBLE)
                .order_by("code").values_list("code", flat=True))

@sync_to_async
def has_active_reserva_or_prestamo_sync(discord_user_id: int) -> bool:
    # Bloquear múltiples reservas simultáneas del mismo usuario
    r_count = Reserva.objects.filter(discord_user_id=str(discord_user_id), estado="activa").count()
    return r_count > 0

@sync_to_async
def reserve_first_available_sync(tipo: str, nivel: str, turno: str,
                                 aula: str, solicitante_username: str, discord_user_id: str,
                                 expira) -> str | None:
    it = Item.objects.filter(tipo=tipo, estado=EstadoItem.DISPONIBLE).order_by("code").first()
    if not it:
        return None
    it.estado = EstadoItem.RESERVADO
    it.save(update_fields=["estado"])
    Reserva.objects.create(
        item=it, tipo=tipo, nivel=nivel, turno=turno,
        aula=aula, solicitante=solicitante_username,
        discord_user_id=str(discord_user_id),
        expira=expira, estado="activa"
    )
    return it.code

@sync_to_async
def start_prestamo_sync(code: str, perfil: dict, turno: str, aula: str):
    try:
        it = Item.objects.get(code=code)
    except Item.DoesNotExist:
        return {"error": "noexist"}
    if it.estado == EstadoItem.EN_USO:
        return {"error": "inuse"}

    res = Reserva.objects.filter(item=it, estado="activa").order_by("-inicio").first()
    if res and (res.discord_user_id and res.discord_user_id != (perfil.get("discord_user_id") or "")):
        return {"error": "reserved"}

    if res:
        res.estado = "convertida"
        res.save(update_fields=["estado"])

    solicitante = perfil["user_username"]  # SIEMPRE username
    p = Prestamo.objects.create(
        item=it, nivel=perfil["nivel"],
        carrera=perfil["carrera"] or None, anio=perfil["anio"] or None,
        turno=turno, aula=aula, solicitante=solicitante, fin_prevista=None
    )
    it.estado = EstadoItem.EN_USO
    it.save(update_fields=["estado"])
    return {"ok": True, "nivel_disp": p.get_nivel_display(), "turno_disp": p.get_turno_display()}

@sync_to_async
def entregar_prestamo_sync(code: str):
    try:
        p = Prestamo.objects.filter(item__code=code, fin_real__isnull=True).latest("inicio")
    except Prestamo.DoesNotExist:
        return {"error": "noactive"}
    p.cerrar()
    return {"ok": True, "dur": float(p.duracion_horas or 0)}

@sync_to_async
def activos_list_sync() -> list[str]:
    qs = (Prestamo.objects.filter(fin_real__isnull=True)
          .select_related("item").order_by("-inicio")[:10])
    return [
        f"- {p.item.code} · {p.get_nivel_display()} {p.get_turno_display()} · {p.solicitante or 'N/D'} · {p.inicio.astimezone().strftime('%H:%M')}"
        for p in qs
    ]

@sync_to_async
def status_sync(code: str):
    try:
        it = Item.objects.get(code=code)
    except Item.DoesNotExist:
        return {"error": "noexist"}
    out = {"code": code, "tipo": it.get_tipo_display(), "estado": it.get_estado_display(), "extra": ""}
    if it.estado == EstadoItem.EN_USO:
        p = Prestamo.objects.filter(item=it, fin_real__isnull=True).latest("inicio")
        out["extra"] = f" · En uso desde {p.inicio.astimezone().strftime('%d/%m %H:%M')} · {p.solicitante or 'N/D'}"
    return out

# ---- Bot ----

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.synced = False
    async def on_ready(self):
        print(f"Conectado como {self.user} (id: {self.user.id})")
        if not self.synced:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                tree.copy_global_to(guild=guild)
                await tree.sync(guild=guild)
                print(f"Slash sincronizados en guild {GUILD_ID}")
            else:
                await tree.sync()
                print("Slash sincronizados globalmente (pueden tardar hasta 1h)")
            self.synced = True
            for g in bot.guilds:
                print(f"Guild: {g.name} · ID: {g.id}")

bot = MyBot()
tree = app_commands.CommandTree(bot)

def is_linked():
    async def predicate(interaction: discord.Interaction) -> bool:
        return await profile_exists_sync(interaction.user.id)
    return app_commands.check(predicate)

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        msg = "Vinculá tu cuenta: en la web /accounts/discord/ generá un token y acá usá /vincular TOKEN."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    else:
        print("Slash error:", repr(error))

@tree.command(name="ping", description="Prueba que el bot está vivo")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong 🏓", ephemeral=True)

@tree.command(name="serverid", description="Muestra el ID del servidor")
async def serverid(interaction: discord.Interaction):
    await interaction.response.send_message(f"Server ID: {interaction.guild_id}", ephemeral=True)

@tree.command(name="vincular", description="Vincula tu Discord a tu usuario del sistema")
async def vincular(interaction: discord.Interaction, token: str):
    await interaction.response.defer(ephemeral=True)
    status, uname = await link_user_by_token_sync(token, interaction.user.id)
    msg = {
        "ok": "✅ Cuenta vinculada correctamente.",
        "already": "Ya estabas validado: tu cuenta de Discord ya está vinculada.",
        "bad": "Token inválido o ya usado.",
        "user_has_other": "Ese token pertenece a un usuario que ya tiene Discord vinculado."
    }[status]
    await interaction.followup.send(msg, ephemeral=True)

def _choice_tipo():
    return [
        app_commands.Choice(name="Notebooks", value="NB"),
        app_commands.Choice(name="Tablets", value="TB"),
        app_commands.Choice(name="Alargues", value="AL"),
    ]

@tree.command(name="disponibles", description="Lista códigos disponibles de un tipo")
@app_commands.choices(tipo=_choice_tipo())
@is_linked()
async def disponibles(interaction: discord.Interaction, tipo: app_commands.Choice[str]):
    codes = await get_available_codes_sync(tipo.value)
    cods = ", ".join(codes) if codes else "Sin disponibilidad"
    await interaction.response.send_message(f"Disponibles {tipo.name}: {cods}", ephemeral=True)

def guess_turno(nivel: str) -> str:
    hour = timezone.now().astimezone().hour
    if nivel == Nivel.SUPERIOR:
        return Turno.NOCHE
    return Turno.MANANA if hour < 13 else Turno.TARDE

@tree.command(name="reservar", description="Reserva un ítem por N minutos")
@app_commands.choices(tipo=_choice_tipo())
@is_linked()
async def reservar(interaction: discord.Interaction,
                   tipo: app_commands.Choice[str],
                   minutos: app_commands.Range[int, 5, 180] = 20,
                   aula: int | None = None):
    await interaction.response.defer(ephemeral=True)
    if await has_active_reserva_or_prestamo_sync(interaction.user.id):
        await interaction.followup.send("Ya tenés una reserva o préstamo activo. Entregá o cancelá antes de reservar nuevamente.", ephemeral=True)
        return
    perfil = await get_perfil_dict_by_discord_sync(interaction.user.id)
    turno = Turno.NOCHE if perfil["nivel"] == Nivel.SUPERIOR else guess_turno(perfil["nivel"])
    expira = timezone.now() + timedelta(minutes=int(minutos))
    code = await reserve_first_available_sync(
        tipo.value, perfil["nivel"], turno, aula,
        str(aula) if aula is not None else "",
        perfil["user_username"],
        perfil["discord_user_id"] or str(interaction.user.id),
        expira
    )
    if not code:
        await interaction.followup.send(f"No hay {tipo.name} disponibles.", ephemeral=True)
        return
    send_discord(f"🔒 {perfil['user_username']} reservó {code} por {minutos} min (vence {expira.astimezone().strftime('%H:%M')}).")
    await interaction.followup.send(f"🔒 Reservado {code} por {minutos} min. Expira {expira.astimezone().strftime('%H:%M')}.", ephemeral=True)

@tree.command(name="prestar", description="Inicia un préstamo de un código")
@is_linked()
async def prestar(interaction: discord.Interaction, code: str, aula: int | None = None):
    await interaction.response.defer(ephemeral=True)
    perfil = await get_perfil_dict_by_discord_sync(interaction.user.id)
    turno = Turno.NOCHE if perfil["nivel"] == Nivel.SUPERIOR else guess_turno(perfil["nivel"])
    res = await start_prestamo_sync(code, perfil, turno, str(aula) if aula is not None else "")
    if "error" in res:
        msg = {"noexist":"Código inexistente.","inuse":"El ítem ya está en uso.","reserved":"Este ítem está reservado por otra persona."}[res["error"]]
        await interaction.followup.send(msg, ephemeral=True)
        return
    send_discord(f"✅ {perfil['user_username']} inició préstamo de {code} ({res['nivel_disp']} - {res['turno_disp']}).")
    await interaction.followup.send(f"✅ Préstamo registrado: {code}.", ephemeral=True)

@tree.command(name="entregar", description="Cierra el préstamo activo de un código")
@is_linked()
async def entregar(interaction: discord.Interaction, code: str):
    await interaction.response.defer(ephemeral=True)
    res = await entregar_prestamo_sync(code)
    if "error" in res:
        await interaction.followup.send("No hay préstamo activo para ese código.", ephemeral=True)
        return
    send_discord(f"📦 {interaction.user.name} entregó {code}. Duración: {res['dur']} h")
    await interaction.followup.send(f"📦 Entregado {code}. Duración: {res['dur']} h", ephemeral=True)

@tree.command(name="activos", description="Lista hasta 10 préstamos activos")
@is_linked()
async def activos(interaction: discord.Interaction):
    lines = await activos_list_sync()
    if not lines:
        await interaction.response.send_message("No hay préstamos activos.", ephemeral=True)
        return
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@tree.command(name="status", description="Estado de un código")
@is_linked()
async def status(interaction: discord.Interaction, code: str):
    d = await status_sync(code)
    if "error" in d:
        await interaction.response.send_message("Código inexistente.", ephemeral=True)
        return
    await interaction.response.send_message(f"{d['code']} · {d['tipo']} · {d['estado']}{d['extra']}", ephemeral=True)

class Command(BaseCommand):
    help = "Inicia el bot de Discord"
    def handle(self, *args, **options):
        tok = os.getenv("DISCORD_BOT_TOKEN")
        if not tok:
            self.stderr.write("Falta DISCORD_BOT_TOKEN en .env"); return
        bot.run(tok)