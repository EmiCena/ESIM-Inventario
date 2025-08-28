from django.contrib import admin
from .models import Item, Prestamo, Mantenimiento, Reserva, Profile, DiscordLinkToken

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display=("code","tipo","estado","uso_acumulado_horas","usos_acumulados")
    list_filter=("tipo","estado")
    search_fields=("code",)

@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display=("item","nivel","carrera","anio","turno","inicio","fin_real","duracion_horas","solicitante","estado")
    list_filter=("nivel","carrera","anio","turno","estado")
    search_fields=("item__code","solicitante","aula")

@admin.register(Mantenimiento)
class MantAdmin(admin.ModelAdmin):
    list_display=("item","tipo","severidad","estado","fecha_apertura","fecha_cierre")
    list_filter=("estado","tipo","severidad")

@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display=("id","item","tipo","nivel","turno","solicitante","expira","estado")
    list_filter=("estado","tipo","turno","nivel")
    search_fields=("item__code","solicitante")

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display=("user","nivel","carrera","anio","discord_user_id")
    list_filter=("nivel","carrera","anio")
    search_fields=("user__username","discord_user_id")

@admin.register(DiscordLinkToken)
class DiscordLinkTokenAdmin(admin.ModelAdmin):
    list_display=("user","token","created_at","used_at")
    search_fields=("token","user__username")