from django.core.management.base import BaseCommand
from core.models import Item, TipoItem

class Command(BaseCommand):
    help = "Crea items iniciales"

    def handle(self, *args, **kwargs):
        created = 0
        for i in range(1, 16):
            _, c = Item.objects.get_or_create(code=f"NB-{i:02}", defaults={"tipo": TipoItem.NOTEBOOK})
            created += int(c)
        for i in range(1, 6):
            _, c = Item.objects.get_or_create(code=f"TB-{i:02}", defaults={"tipo": TipoItem.TABLET})
            created += int(c)
        for i in range(1, 7):
            _, c = Item.objects.get_or_create(code=f"AL-{i:02}", defaults={"tipo": TipoItem.ALARGUE})
            created += int(c)
        self.stdout.write(self.style.SUCCESS(f"{created} items creados (o ya existían)."))