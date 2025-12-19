from django.http import JsonResponse
from django.views.generic import View
from .models import Airport

class AirportGeoJSON(View):
    def get(self, request):
        airports = Airport.objects.all()  # همه فرودگاه‌ها
        
        features = []
        for airport in airports:
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [airport.location.x, airport.location.y]
                },
                "properties": {
                    "name": airport.name,
                    "iata": airport.iata_code,
                    "icao": airport.icao_code,
                    "city": airport.city
                }
            }
            features.append(feature)
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        return JsonResponse(geojson)
