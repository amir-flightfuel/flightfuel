from django.contrib import admin
from django.contrib.gis import admin as gis_admin
from django.utils.html import format_html
from .models import Waypoint, Airway, AirwaySegment, Route, FlightInformationRegion


@admin.register(Waypoint)
class WaypointAdmin(gis_admin.GISModelAdmin):
    list_display = ('identifier', 'name', 'type_display', 'country', 'is_active', 'source_display')
    list_filter = ('type', 'country', 'is_active', 'source')
    search_fields = ('identifier', 'name', 'country')
    readonly_fields = ('location_map',)
    fieldsets = (
        ('اطلاعات اصلی', {'fields': ('identifier', 'name', 'type', 'country')}),
        ('اطلاعات فنی', {'fields': ('frequency', 'elevation', 'magnetic_variation'), 'classes': ('collapse',)}),
        ('موقعیت', {'fields': ('location', 'location_map')}),
        ('مدیریتی', {'fields': ('source', 'is_active'), 'classes': ('collapse',)}),
    )
    
    def type_display(self, obj):
        type_colors = {'AIRPORT': 'green', 'VOR': 'blue', 'NDB': 'orange', 'FIX': 'gray', 'SID': 'purple', 'STAR': 'red'}
        color = type_colors.get(obj.type, 'black')
        return format_html('<span style="color: {};">{}</span>', color, obj.get_type_display())
    type_display.short_description = 'نوع'
    
    def source_display(self, obj):
        sources = {'OURAIRPORTS': '🌐', 'AIP_IRAN': '🇮🇷', 'MANUAL': '✏️'}
        return format_html('{} {}', sources.get(obj.source, '❓'), obj.get_source_display())
    source_display.short_description = 'منبع'
    
    def location_map(self, obj):
        if obj.location:
            return format_html(
                '<a href="https://www.openstreetmap.org/?mlat={}&mlon={}&zoom=12" target="_blank">🗺️ مشاهده در نقشه</a>',
                obj.location.y, obj.location.x
            )
        return "بدون مختصات"
    location_map.short_description = 'نقشه'


class AirwaySegmentInline(admin.TabularInline):
    model = AirwaySegment
    extra = 1
    fields = ('sequence', 'from_waypoint', 'to_waypoint', 'distance', 'base_altitude')
    ordering = ('sequence',)


@admin.register(Airway)
class AirwayAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'name', 'type_display', 'segment_count', 'total_distance')
    list_filter = ('type',)
    search_fields = ('identifier', 'name')
    inlines = [AirwaySegmentInline]
    
    def type_display(self, obj):
        colors = {'A': 'red', 'B': 'blue', 'G': 'green', 'R': 'purple'}
        color = colors.get(obj.type, 'black')
        return format_html('<span style="color: {};">{}</span>', color, obj.get_type_display())
    type_display.short_description = 'نوع'
    
    def segment_count(self, obj):
        count = obj.segments.count()
        return format_html('<span style="color: {};">{}</span>', 'green' if count > 0 else 'red', count)
    segment_count.short_description = 'تعداد Segment'
    
    def total_distance(self, obj):
        total = sum(seg.distance for seg in obj.segments.all())
        return f"{total:.1f} NM"
    total_distance.short_description = 'طول کل'


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('name', 'departure', 'arrival', 'distance_display', 'waypoint_count', 'created_by', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'departure', 'arrival', 'description')
    readonly_fields = ('created_at', 'updated_at', 'coordinates_preview', 'waypoints_list')
    fieldsets = (
        ('اطلاعات مسیر', {'fields': ('name', 'departure', 'arrival', 'description')}),
        ('نقاط مسیر', {'fields': ('waypoints', 'waypoints_list')}),
        ('محاسبات', {'fields': ('total_distance', 'coordinates', 'coordinates_preview')}),
        ('تاریخ‌ها', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
        ('کاربران', {'fields': ('created_by', 'updated_by'), 'classes': ('collapse',)}),
    )
    
    def distance_display(self, obj):
        return f"{obj.total_distance} NM"
    distance_display.short_description = 'مسافت'
    
    def waypoint_count(self, obj):
        count = len(obj.waypoints) if obj.waypoints else 0
        return format_html('<span style="background: #e3f2fd; padding: 2px 6px; border-radius: 10px;">{}</span>', count)
    waypoint_count.short_description = 'تعداد WP'
    
    def waypoints_list(self, obj):
        if obj.waypoints:
            html = '<div style="direction: ltr; font-family: monospace;">'
            for i, wp in enumerate(obj.waypoints):
                html += f"{i+1:02d}. {wp}<br>"
            html += '</div>'
            return format_html(html)
        return "بدون Waypoint"
    waypoints_list.short_description = 'لیست Waypointها'
    
    def coordinates_preview(self, obj):
        if obj.coordinates:
            coords = list(obj.coordinates.coords)
            preview = f"({coords[0][0]:.4f}, {coords[0][1]:.4f}) → ({coords[-1][0]:.4f}, {coords[-1][1]:.4f})"
            return format_html('<code style="background: #f5f5f5; padding: 5px;">{}</code>', preview)
        return "بدون مختصات"
    coordinates_preview.short_description = 'پیش‌نمایش مختصات'


@admin.register(FlightInformationRegion)
class FlightInformationRegionAdmin(gis_admin.GISModelAdmin):
    list_display = ('identifier', 'name', 'country', 'icao_region', 'upper_limit', 'is_active', 'area_display')
    list_filter = ('country', 'icao_region', 'is_active')
    search_fields = ('identifier', 'name', 'country')
    readonly_fields = ('boundary_map', 'center_point_display', 'area_display')
    
    fieldsets = (
        ('اطلاعات شناسایی', {'fields': ('identifier', 'name', 'country', 'country_code')}),
        ('اطلاعات تماس', {'fields': ('frequency', 'emergency_frequency'), 'classes': ('collapse',)}),
        ('مرز هوایی', {'fields': ('boundary', 'boundary_map', 'center_point_display', 'area_display')}),
        ('محدودیت‌های پروازی', {'fields': ('upper_limit', 'lower_limit', 'icao_region'), 'classes': ('collapse',)}),
        ('وضعیت و یادداشت‌ها', {'fields': ('is_active', 'notes'), 'classes': ('collapse',)}),
    )
    
    def boundary_map(self, obj):
        if obj.boundary:
            center = obj.boundary.centroid
            return format_html(
                '<a href="https://www.openstreetmap.org/?mlat={}&mlon={}&zoom=6" target="_blank">🗺️ مشاهده FIR در نقشه</a>',
                center.y, center.x
            )
        return "بدون مرز"
    boundary_map.short_description = 'نقشه مرز'
    
    def center_point_display(self, obj):
        center = obj.get_center_point()
        if center:
            return format_html('{:.4f}°N, {:.4f}°E', center.y, center.x)
        return "تعریف نشده"
    center_point_display.short_description = 'مرکز جغرافیایی'
    
    def area_display(self, obj):
        try:
            area = obj.get_area_km2()
            if area > 0:
                formatted = f"{area:,.0f}"
                color = 'green' if area < 1000000 else 'blue'
                return format_html('<span style="color: {};">{} km²</span>', color, formatted)
        except:
            pass
        return "N/A"
    area_display.short_description = 'مساحت'


admin.site.register(AirwaySegment)
