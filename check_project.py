import os
import sys
import django

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'flightfuel_project.settings')
django.setup()

from django.apps import apps

print("📋 لیست کامل پروژه")
print("=" * 50)

# ۱. همه اپ‌ها
print("\n۱. اپ‌های نصب‌شده:")
for app_config in apps.get_app_configs():
    print(f"   • {app_config.name}")
    
    # مدل‌های هر اپ
    for model in app_config.get_models():
        try:
            count = model.objects.count()
            print(f"     └── {model.__name__}: {count} رکورد")
        except:
            print(f"     └── {model.__name__}: (خطا در شمارش)")

# ۲. Airportهای نمونه
print("\n۲. نمونه فرودگاه‌ها:")
try:
    from airports.models import Airport
    airports = Airport.objects.all()[:5]
    for ap in airports:
        print(f"   • {ap.iata_code or ap.icao_code}: {ap.name}")
    print(f"   ... و {Airport.objects.count()-5} فرودگاه دیگر")
except Exception as e:
    print(f"   ❌ خطا: {e}")

# ۳. Waypointهای نمونه
print("\n۳. نمونه Waypointها:")
try:
    from routes.models import Waypoint
    waypoints = Waypoint.objects.all()[:5]
    for wp in waypoints:
        print(f"   • {wp.identifier}: {wp.name} ({wp.country})")
    print(f"   ... و {Waypoint.objects.count()-5} Waypoint دیگر")
except Exception as e:
    print(f"   ❌ خطا: {e}")

# ۴. Routes نمونه
print("\n۴. نمونه Routeها:")
try:
    from routes.models import Route
    routes = Route.objects.all()[:3]
    for rt in routes:
        print(f"   • {rt.name}: {rt.departure} → {rt.arrival}")
    print(f"   ... و {Route.objects.count()-3} Route دیگر")
except Exception as e:
    print(f"   ❌ خطا: {e}")

print("\n" + "=" * 50)
print("✅ بررسی کامل شد")
