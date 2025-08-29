from django.contrib import admin
from django.utils import timezone
from .models import Item, Prestamo, Mantenimiento, Reserva, Profile, DiscordLinkToken

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("code","tipo","estado","uso_acumulado_horas","usos_acumulados")
    list_filter  = ("tipo","estado")
    search_fields = ("code",)
    actions = ["poner_mantenimiento","sacar_mantenimiento"]

    def poner_mantenimiento(self, request, queryset):
        for it in queryset.exclude(estado="MANT"):
            Mantenimiento.objects.create(item=it, tipo="preventivo", severidad=1, descripcion="Puesta manual en mantenimiento")
            it.estado = "MANT"
            it.save(update_fields=["estado"])
        self.message_user(request, "Ítems en mantenimiento.")
    poner_mantenimiento.short_description = "Poner en mantenimiento"

    def sacar_mantenimiento(self, request, queryset):
        for it in queryset.filter(estado="MANT"):
            Mantenimiento.objects.filter(item=it, estado__in=["abierto","en_proceso"]).update(estado="cerrado", fecha_cierre=timezone.now())
            it.estado = "DISP"
            it.save(update_fields=["estado"])
        self.message_user(request, "Ítems fuera de mantenimiento.")
    sacar_mantenimiento.short_description = "Sacar de mantenimiento"

@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = ("item","nivel","carrera","anio_display","turno","inicio","fin_real","duracion_horas","estado","solicitante")
    list_filter  = ("nivel","carrera","anio","turno","estado")
    search_fields = ("item__code","solicitante","aula")
    def anio_display(self, obj):
        return obj.get_anio_display() if obj.anio is not None else "-"
    anio_display.short_description = "Año"
    anio_display.admin_order_field = "anio"

@admin.register(Mantenimiento)
class MantAdmin(admin.ModelAdmin):
    list_display = ("item","tipo","severidad","estado","fecha_apertura","fecha_cierre")
    list_filter  = ("estado","tipo","severidad")
    search_fields = ("item__code",)

@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ("id","item","tipo","nivel","turno","solicitante","expira","estado","aprobada_por","aprobada_at")
    list_filter  = ("estado","tipo","turno","nivel")
    search_fields = ("item__code","solicitante")
    actions = ["aprobar_convertir","cancelar_reserva"]

    def aprobar_convertir(self, request, queryset):
        count_ok = 0
        for r in queryset.filter(estado="activa"):
            p = r.aprobar_y_convertir(request.user)
            if p: count_ok += 1
        self.message_user(request, f"{count_ok} reservas aprobadas y convertidas a préstamo.")
    aprobar_convertir.short_description = "Aprobar y convertir a préstamo"

    def cancelar_reserva(self, request, queryset):
        for r in queryset.filter(estado="activa"):
            r.cancelar(user=request.user, motivo="Cancelado desde admin")
        self.message_user(request, "Reservas canceladas.")
    cancelar_reserva.short_description = "Cancelar reservas seleccionadas"

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user","nivel","carrera","anio_display","discord_user_id")
    list_filter  = ("nivel","carrera","anio")
    search_fields = ("user__username","discord_user_id")
    def anio_display(self, obj):
        return obj.get_anio_display() if obj.anio is not None else "-"
    anio_display.short_description = "Año"
    anio_display.admin_order_field = "anio"

@admin.register(DiscordLinkToken)
class DiscordLinkTokenAdmin(admin.ModelAdmin):
    list_display = ("user","token","created_at","used_at")
    search_fields = ("token","user__username")