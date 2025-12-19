from django.contrib.gis.admin import GISModelAdmin
from django.contrib import admin
from .models import Airport

@admin.register(Airport)
class AirportAdmin(GISModelAdmin):
    list_display = ['name', 'iata_code', 'icao_code', 'city', 'country', 'airport_type']
    search_fields = ['name', 'iata_code', 'icao_code', 'city']
    list_filter = ['airport_type', 'country']
