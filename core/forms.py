from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.conf import settings as djsettings

from .models import (
    Prestamo, Item, EstadoItem, Nivel, Turno,
    TipoItem, CarreraSup, AnioSup
)

User = get_user_model()

# ------------- Préstamo -------------
class PrestamoRapidoForm(forms.Form):
    tipo = forms.ChoiceField(choices=TipoItem.choices, label="Tipo de ítem")
    code = forms.ChoiceField(choices=[], label="Número")

    nivel = forms.ChoiceField(choices=Nivel.choices, label="Nivel")
    carrera = forms.ChoiceField(choices=[("", "—")] + list(CarreraSup.choices), required=False, label="Carrera (Superior)")
    anio = forms.ChoiceField(choices=[("", "—")] + list(AnioSup.choices), required=False, label="Año (Superior)")

    turno = forms.ChoiceField(choices=Turno.choices, label="Turno", required=False)
    aula = forms.CharField(
        required=False, label="Aula",
        widget=forms.NumberInput(attrs={"min": 0, "step": 1, "inputmode": "numeric", "pattern": "[0-9]*"})
    )
    solicitante = forms.CharField(required=False, help_text="Se usará tu usuario de la plataforma.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tipo = self.data.get("tipo") or self.initial.get("tipo") or TipoItem.NOTEBOOK
        items = Item.objects.filter(tipo=tipo, estado=EstadoItem.DISPONIBLE).order_by("code")
        self.fields["code"].choices = [(i.code, i.code) for i in items]

    def clean_aula(self):
        aula = self.cleaned_data.get("aula", "")
        if aula in ("", None):
            return ""
        s = str(aula).strip()
        if not s.isdigit():
            raise forms.ValidationError("El aula debe ser un número entero.")
        return s

    def clean(self):
        data = super().clean()

        code = data.get("code")
        if not code:
            self.add_error("code", "Elegí un número disponible.")
            return data
        try:
            item = Item.objects.get(code=code)
        except Item.DoesNotExist:
            self.add_error("code", "El código no existe.")
            return data
        if item.estado != EstadoItem.DISPONIBLE:
            self.add_error("code", "El ítem no está disponible.")
            return data
        data["item"] = item

        if data.get("nivel") == Nivel.SUPERIOR:
            if not data.get("carrera") or not data.get("anio"):
                raise forms.ValidationError("Para Nivel Superior seleccioná Carrera y Año.")
            data["turno"] = Turno.NOCHE
        else:
            if not data.get("turno"):
                self.add_error("turno", "Elegí un turno.")

        return data

    def save(self):
        item = self.cleaned_data["item"]
        p = Prestamo.objects.create(
            item=item,
            nivel=self.cleaned_data["nivel"],
            carrera=self.cleaned_data.get("carrera") or None,
            anio=int(self.cleaned_data["anio"]) if self.cleaned_data.get("anio") else None,
            turno=self.cleaned_data["turno"],
            aula=str(self.cleaned_data.get("aula") or ""),
            solicitante=self.cleaned_data.get("solicitante", ""),
            fin_prevista=None,
        )
        item.estado = EstadoItem.EN_USO
        item.save(update_fields=["estado"])
        return p

# ------------- Devolución -------------
class DevolucionForm(forms.Form):
    code = forms.CharField(label="Código (ej: NB-03)", max_length=10)
    def clean(self):
        data = super().clean()
        code = data.get("code")
        try:
            self.prestamo = Prestamo.objects.filter(item__code=code, fin_real__isnull=True).latest("inicio")
        except Prestamo.DoesNotExist:
            raise forms.ValidationError("No hay préstamo activo para ese código.")
        return data
    def save(self):
        self.prestamo.cerrar()
        return self.prestamo

# ------------- Registro (Signup) -------------
class SignupForm(UserCreationForm):
    first_name = forms.CharField(label="Nombre", max_length=30)
    last_name  = forms.CharField(label="Apellido", max_length=30)

    nivel   = forms.ChoiceField(choices=Nivel.choices, label="Nivel")
    carrera = forms.ChoiceField(choices=[("", "—")] + list(CarreraSup.choices), required=False, label="Carrera (Superior)")
    anio    = forms.ChoiceField(choices=[("", "—")] + list(AnioSup.choices), required=False, label="Año (Superior)")

    join_code = forms.CharField(label="Código de registro", help_text="Proporcionado por la institución")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username","first_name","last_name","password1","password2","nivel","carrera","anio","join_code")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        u = self.fields["username"]
        u.error_messages["invalid"] = "Ingresá un nombre de usuario válido (letras, números y @/./+/-/_). Sin espacios."
        u.help_text = "Ejemplos: juan.perez, profe_marta, operador-1 (sin espacios)."

    def clean(self):
        data = super().clean()
        nivel = data.get("nivel")
        code = (data.get("join_code") or "").strip()

        # En desarrollo permitimos vacío; en prod exigimos los códigos
        if djsettings.DEBUG and not code:
            pass
        else:
            ok = (
                (nivel == "SEC" and code == getattr(djsettings, "JOIN_CODE_SEC", "SEC-123")) or
                (nivel == "SUP" and code == getattr(djsettings, "JOIN_CODE_SUP", "SUP-123")) or
                (nivel == "PER" and code == getattr(djsettings, "JOIN_CODE_STAFF", "STAFF-123"))
            )
            if not ok:
                raise forms.ValidationError("Código de registro inválido para el nivel seleccionado.")

        if nivel == "SUP" and (not data.get("carrera") or not data.get("anio")):
            raise forms.ValidationError("Para Nivel Superior elegí Carrera y Año.")
        return data

    def save(self, commit=True):
        user = super().save(commit=True)
        p = user.profile  # creado por signal o get_or_create en la vista
        cd = self.cleaned_data
        p.nivel = cd["nivel"]
        if p.nivel == "SUP":
            p.carrera = cd.get("carrera") or None
            p.anio = int(cd["anio"]) if cd.get("anio") else None
        p.save()

        # Asignación de grupos simple
        from django.contrib.auth.models import Group
        group_name = "ALUMNO_SUP" if p.nivel == "SUP" else ("STAFF" if p.nivel == "PER" else "ALUMNO_SEC")
        grp, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(grp)
        return user