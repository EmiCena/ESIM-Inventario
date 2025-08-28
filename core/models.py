from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.conf import settings

# Enums básicos
class Turno(models.TextChoices):
    MANANA = "M", "Mañana"
    TARDE = "T", "Tarde"
    NOCHE = "N", "Noche"

class Nivel(models.TextChoices):
    SECUNDARIO = "SEC", "Secundario"
    SUPERIOR   = "SUP", "Superior"
    PERSONAL   = "PER", "Personal/Docente"

class TipoItem(models.TextChoices):
    NOTEBOOK = "NB", "Notebook"
    TABLET   = "TB", "Tablet"
    ALARGUE  = "AL", "Alargue"

class EstadoItem(models.TextChoices):
    DISPONIBLE    = "DISP", "Disponible"
    EN_USO        = "USO",  "En uso"
    MANTENIMIENTO = "MANT", "Mantenimiento"
    RESERVADO     = "RES",  "Reservado"   # importante para reservas

# Superior
class CarreraSup(models.TextChoices):
    TCD  = "TCD",  "Tecnicatura en Ciencia de Datos"
    PTEC = "PTEC", "Profesorado en Tecnologías"

class AnioSup(models.IntegerChoices):
    PRIMERO = 1, "1°"
    SEGUNDO = 2, "2°"

# Inventario
class Item(models.Model):
    code = models.CharField(max_length=10, unique=True)  # NB-01 / TB-02 / AL-03
    tipo = models.CharField(max_length=2, choices=TipoItem.choices)
    estado = models.CharField(max_length=5, choices=EstadoItem.choices, default=EstadoItem.DISPONIBLE)
    uso_acumulado_horas = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    usos_acumulados = models.PositiveIntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.code

# Préstamos
class Prestamo(models.Model):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="prestamos")
    nivel = models.CharField(max_length=3, choices=Nivel.choices)
    # Para Superior:
    carrera = models.CharField(max_length=4, choices=CarreraSup.choices, null=True, blank=True)
    anio = models.IntegerField(choices=AnioSup.choices, null=True, blank=True)

    turno = models.CharField(max_length=1, choices=Turno.choices)
    aula = models.CharField(max_length=20, blank=True)
    solicitante = models.CharField(max_length=80, blank=True)

    inicio = models.DateTimeField(default=timezone.now)
    fin_prevista = models.DateTimeField(null=True, blank=True)
    fin_real = models.DateTimeField(null=True, blank=True)
    duracion_horas = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True,
                                         validators=[MinValueValidator(0)])
    estado = models.CharField(max_length=10, default="activo")  # activo/devuelto/atrasado
    observaciones = models.TextField(blank=True)

    def cerrar(self, cuando=None):
        if self.fin_real:
            return
        self.fin_real = cuando or timezone.now()
        delta = self.fin_real - self.inicio
        self.duracion_horas = round(delta.total_seconds() / 3600, 2)
        self.estado = "devuelto"
        self.save(update_fields=["fin_real", "duracion_horas", "estado"])

        it = self.item
        it.uso_acumulado_horas = round(float(it.uso_acumulado_horas) + float(self.duracion_horas), 2)
        it.usos_acumulados += 1
        it.estado = EstadoItem.DISPONIBLE
        it.save(update_fields=["uso_acumulado_horas", "usos_acumulados", "estado"])

# Mantenimiento
class Mantenimiento(models.Model):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="mantenimientos")
    tipo = models.CharField(max_length=15, choices=[("preventivo","Preventivo"),("correctivo","Correctivo")])
    severidad = models.IntegerField(default=1)  # 1-5
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=15, choices=[("abierto","Abierto"),("en_proceso","En proceso"),("cerrado","Cerrado")], default="abierto")
    fecha_apertura = models.DateTimeField(auto_now_add=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    def cerrar(self):
        self.estado = "cerrado"
        self.fecha_cierre = timezone.now()
        self.save(update_fields=["estado","fecha_cierre"])

# Reservas (para Discord y Web)
class Reserva(models.Model):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True, blank=True, related_name="reservas")
    tipo = models.CharField(max_length=2, choices=TipoItem.choices)
    nivel = models.CharField(max_length=3, choices=Nivel.choices)
    turno = models.CharField(max_length=1, choices=Turno.choices)
    aula = models.CharField(max_length=20, blank=True)
    solicitante = models.CharField(max_length=80, blank=True)
    discord_user_id = models.CharField(max_length=32, blank=True)
    inicio = models.DateTimeField(auto_now_add=True)
    expira = models.DateTimeField()
    estado = models.CharField(max_length=12, default="activa")  # activa/cancelada/convertida/expirada
    observaciones = models.TextField(blank=True)

    def expirar(self):
        if self.estado != "activa":
            return
        self.estado = "expirada"
        self.save(update_fields=["estado"])
        if self.item and self.item.estado == EstadoItem.RESERVADO:
            self.item.estado = EstadoItem.DISPONIBLE
            self.item.save(update_fields=["estado"])

# Usuarios y Discord
class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    nivel = models.CharField(max_length=3, choices=Nivel.choices, default=Nivel.SECUNDARIO)
    carrera = models.CharField(max_length=4, choices=CarreraSup.choices, null=True, blank=True)
    anio = models.IntegerField(choices=AnioSup.choices, null=True, blank=True)
    discord_user_id = models.CharField(max_length=32, blank=True, null=True, unique=True)
    def __str__(self): return f"{self.user.username} · {self.get_nivel_display()}"

class DiscordLinkToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="discord_tokens")
    token = models.CharField(max_length=8, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])