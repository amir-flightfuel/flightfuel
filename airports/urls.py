from django.urls import path
from .views import AirportGeoJSON

urlpatterns = [
    path('', AirportGeoJSON.as_view(), name='airports_geojson'),
]
