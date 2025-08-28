from django import template
register = template.Library()

@register.simple_tag
def has_role(user, *names):
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name__in=names).exists()