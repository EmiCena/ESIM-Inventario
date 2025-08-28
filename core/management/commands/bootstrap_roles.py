from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, User

class Command(BaseCommand):
    help = "Crea grupos base y un usuario operador demo"

    def handle(self, *args, **kwargs):
        for name in ["ALUMNO_SEC","ALUMNO_SUP","STAFF","OPERADOR","TECNICO","DOCENTE"]:
            Group.objects.get_or_create(name=name)
        if not User.objects.filter(username="operador").exists():
            u = User.objects.create_user("operador", password="operador123")
            u.groups.add(Group.objects.get(name="OPERADOR"))
            self.stdout.write(self.style.SUCCESS("Usuario operador/operador123 creado."))
        self.stdout.write(self.style.SUCCESS("Grupos creados/actualizados."))