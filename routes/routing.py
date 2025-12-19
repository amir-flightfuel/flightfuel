import networkx as nx
from .models import Waypoint, AirwaySegment
from django.contrib.gis.geos import LineString


class AirwayRouter:
    """
    مسیریاب مبتنی بر شبکه Airway
    فقط برای نقاطی که در شبکه Airway موجود باشند
    """
    
    def __init__(self):
        self.graph = nx.Graph()
        self.build_graph()
    
    def build_graph(self):
        """
        ساخت گراف از Segmentهای Airway
        """
        segments = AirwaySegment.objects.select_related('from_waypoint', 'to_waypoint', 'airway')
        for segment in segments:
            self.graph.add_edge(
                segment.from_waypoint.identifier,
                segment.to_waypoint.identifier,
                weight=segment.distance,
                airway=segment.airway.identifier
            )
    
    def find_route(self, departure_iata, arrival_iata):
        """
        پیدا کردن کوتاه‌ترین مسیر در شبکه Airway
        """
        try:
            # بررسی وجود nodeها در گراف
            if departure_iata not in self.graph or arrival_iata not in self.graph:
                return None
            
            # پیدا کردن کوتاه‌ترین مسیر
            path = nx.shortest_path(self.graph, departure_iata, arrival_iata, weight='weight')
            
            # محاسبه مسافت کل
            total_distance = 0
            for i in range(len(path) - 1):
                total_distance += self.graph[path[i]][path[i+1]]['weight']
            
            # جمع‌آوری اطلاعات Airwayهای استفاده شده
            airways_used = []
            for i in range(len(path) - 1):
                edge_data = self.graph[path[i]][path[i+1]]
                airway_id = edge_data.get('airway', 'UNKNOWN')
                if airway_id not in airways_used:
                    airways_used.append(airway_id)
            
            return {
                'waypoints': path,
                'total_distance': total_distance,
                'airways_used': airways_used,
                'segment_count': len(path) - 1
            }
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None


class FlightRouter:
    """
    مسیریاب نیمه‌اتوماتیک پرواز
    رویکرد عملیاتی: پیشنهاد چند مسیر + امکان اصلاح توسط اپراتور
    """
    
    def __init__(self):
        self.airway_router = AirwayRouter()
    
    def find_nearby_waypoints(self, point1, point2, max_distance_nm=100):
        """
        پیدا کردن Waypointهای بین دو نقطه در یک کریدور
        point1, point2: شی‌های Point
        max_distance_nm: حداکثر فاصله از خط مستقیم (مایل دریایی)
        """
        if not point1 or not point2:
            return []
        
        # ایجاد خط مستقیم بین دو نقطه
        line = LineString([point1, point2], srid=4326)
        
        nearby_points = []
        waypoints = Waypoint.objects.filter(is_active=True)
        
        for wp in waypoints:
            # فاصله از خط (بر حسب درجه)
            distance_deg = wp.location.distance(line)
            distance_nm = distance_deg * 60.11  # تبدیل به مایل دریایی
            
            if distance_nm <= max_distance_nm:
                # محاسبه فاصله تا نقطه شروع
                dist_to_start = wp.location.distance(point1) * 60.11
                
                nearby_points.append({
                    'waypoint': wp,
                    'distance_to_line_nm': round(distance_nm, 1),
                    'distance_to_start_nm': round(dist_to_start, 1)
                })
        
        # مرتب‌سازی: اول نزدیک‌ترین به خط، سپس بر اساس موقعیت روی مسیر
        return sorted(nearby_points, 
                     key=lambda x: (x['distance_to_line_nm'], x['distance_to_start_nm']))
    
    def suggest_routes(self, departure_id, arrival_id, max_deviation_nm=100):
        """
        پیشنهاد چندین مسیر مختلف بین دو Waypoint
        """
        try:
            departure_wp = Waypoint.objects.get(identifier=departure_id)
            arrival_wp = Waypoint.objects.get(identifier=arrival_id)
        except Waypoint.DoesNotExist:
            return {"error": "Waypoint پیدا نشد"}
        
        suggestions = []
        
        # ۱. مسیر مستقیم (Great Circle)
        direct_distance_deg = departure_wp.location.distance(arrival_wp.location)
        direct_distance_nm = direct_distance_deg * 60.11
        
        suggestions.append({
            'type': 'DIRECT',
            'name': 'مسیر مستقیم',
            'waypoints': [departure_id, arrival_id],
            'total_distance_nm': round(direct_distance_nm, 1),
            'description': 'کوتاه‌ترین مسیر (Great Circle)',
            'complexity': 'ساده',
            'fuel_efficiency': 'عالی',
            'flight_time_min': round(direct_distance_nm / 480 * 60)  # سرعت 480 گره
        })
        
        # ۲. مسیر از طریق شبکه Airway (اگر وجود داشته باشد)
        airway_route = self.airway_router.find_route(departure_id, arrival_id)
        if airway_route:
            suggestions.append({
                'type': 'AIRWAY_NETWORK',
                'name': 'مسیر هوایی استاندارد',
                'waypoints': airway_route['waypoints'],
                'total_distance_nm': round(airway_route['total_distance'], 1),
                'description': f'استفاده از Airwayهای {", ".join(airway_route["airways_used"])}',
                'complexity': 'استاندارد',
                'fuel_efficiency': 'خوب',
                'flight_time_min': round(airway_route['total_distance'] / 460 * 60),  # سرعت کمتر در Airway
                'segment_count': airway_route['segment_count']
            })
        
        # ۳. پیدا کردن Waypointهای نزدیک به خط مستقیم
        nearby = self.find_nearby_waypoints(
            departure_wp.location, 
            arrival_wp.location, 
            max_deviation_nm
        )
        
        # ۴. مسیر با Waypointهای میانی (اگر نقطه مناسبی پیدا شد)
        if nearby:
            # انتخاب Waypointهای کلیدی
            selected = []
            for point in nearby:
                # فقط نقاطی که خیلی نزدیک به مبدأ یا مقصد نباشند
                if (point['distance_to_start_nm'] > 50 and 
                    point['distance_to_start_nm'] < direct_distance_nm - 50):
                    selected.append(point['waypoint'])
                    if len(selected) >= 2:  # حداکثر ۲ نقطه میانی
                        break
            
            if selected:
                waypoint_ids = [departure_id] + [wp.identifier for wp in selected] + [arrival_id]
                
                # محاسبه مسافت این مسیر
                total_dist = 0
                for i in range(len(waypoint_ids) - 1):
                    wp1 = Waypoint.objects.get(identifier=waypoint_ids[i])
                    wp2 = Waypoint.objects.get(identifier=waypoint_ids[i + 1])
                    total_dist += wp1.location.distance(wp2.location) * 60.11
                
                suggestions.append({
                    'type': 'VIA_WAYPOINTS',
                    'name': 'مسیر با نقاط میانی',
                    'waypoints': waypoint_ids,
                    'total_distance_nm': round(total_dist, 1),
                    'description': f'استفاده از {len(selected)} نقطه ناوبری میانی',
                    'complexity': 'انعطاف‌پذیر',
                    'fuel_efficiency': 'متوسط',
                    'flight_time_min': round(total_dist / 470 * 60),
                    'intermediate_points': [wp.identifier for wp in selected]
                })
        
        # ۵. مسیر ترکیبی (اگر Waypoint نزدیک به وسط مسیر وجود داشت)
        if nearby:
            # پیدا کردن نزدیک‌ترین Waypoint به وسط مسیر
            mid_distance = direct_distance_nm / 2
            closest_to_mid = None
            min_diff = float('inf')
            
            for point in nearby:
                diff = abs(point['distance_to_start_nm'] - mid_distance)
                if diff < min_diff and point['distance_to_line_nm'] < 50:
                    min_diff = diff
                    closest_to_mid = point
            
            if closest_to_mid:
                waypoint_ids = [departure_id, closest_to_mid['waypoint'].identifier, arrival_id]
                
                # محاسبه مسافت
                total_dist = 0
                for i in range(len(waypoint_ids) - 1):
                    wp1 = Waypoint.objects.get(identifier=waypoint_ids[i])
                    wp2 = Waypoint.objects.get(identifier=waypoint_ids[i + 1])
                    total_dist += wp1.location.distance(wp2.location) * 60.11
                
                suggestions.append({
                    'type': 'HYBRID',
                    'name': 'مسیر ترکیبی',
                    'waypoints': waypoint_ids,
                    'total_distance_nm': round(total_dist, 1),
                    'description': 'ترکیب مسیر مستقیم و نقاط ناوبری',
                    'complexity': 'متوازن',
                    'fuel_efficiency': 'خوب',
                    'flight_time_min': round(total_dist / 475 * 60),
                    'mid_point': closest_to_mid['waypoint'].identifier
                })
        
        return {
            'departure': departure_id,
            'arrival': arrival_id,
            'departure_name': departure_wp.name,
            'arrival_name': arrival_wp.name,
            'direct_distance_nm': round(direct_distance_nm, 1),
            'suggestions': suggestions,
            'nearby_waypoints_count': len(nearby),
            'max_deviation_nm': max_deviation_nm,
            'timestamp': 'now'
        }
    
    def create_route_from_suggestion(self, suggestion, user, custom_waypoints=None, route_name=None):
        """
        ایجاد Route نهایی از پیشنهاد انتخاب شده
        امکان اصلاح Waypointها توسط اپراتور
        """
        from routes.models import Route
        from django.utils import timezone
        from django.db.models import Q
        
        # استفاده از Waypointهای اصلاح شده یا پیشنهادی
        waypoints = custom_waypoints if custom_waypoints else suggestion['waypoints']
        
        # محاسبه مسافت واقعی
        total_distance = 0
        for i in range(len(waypoints) - 1):
            try:
                wp1 = Waypoint.objects.get(identifier=waypoints[i])
                wp2 = Waypoint.objects.get(identifier=waypoints[i + 1])
                distance_deg = wp1.location.distance(wp2.location)
                total_distance += distance_deg * 60.11
            except Waypoint.DoesNotExist:
                continue
        
        # تولید نام Route
        if not route_name:
            date_str = timezone.now().strftime('%Y%m%d')
            last_seq = Route.objects.filter(
                Q(name__startswith=f"{waypoints[0]}-{waypoints[-1]}-{date_str}")
            ).count() + 1
            route_name = f"{waypoints[0]}-{waypoints[-1]}-{date_str}-{last_seq:03d}"
        
        # ایجاد Route
        route = Route.objects.create(
            name=route_name,
            departure=waypoints[0],
            arrival=waypoints[-1],
            waypoints=waypoints,
            total_distance=round(total_distance, 1),
            description=f"{suggestion.get('description', 'مسیر پرواز')} | نوع: {suggestion['type']}",
            created_by=user
        )
        
        return {
            'route_id': route.id,
            'route_name': route.name,
            'waypoints': waypoints,
            'total_distance_nm': route.total_distance,
            'created_at': route.created_at
        }
    
    def get_waypoint_details(self, waypoint_ids):
        """
        دریافت اطلاعات کامل Waypointها
        """
        waypoints = []
        for wp_id in waypoint_ids:
            try:
                wp = Waypoint.objects.get(identifier=wp_id)
                waypoints.append({
                    'identifier': wp.identifier,
                    'name': wp.name,
                    'type': wp.type,
                    'type_display': wp.get_type_display(),
                    'country': wp.country,
                    'frequency': wp.frequency,
                    'elevation': wp.elevation,
                    'is_active': wp.is_active,
                    'source': wp.source
                })
            except Waypoint.DoesNotExist:
                waypoints.append({
                    'identifier': wp_id,
                    'error': 'Waypoint پیدا نشد'
                })
        
        return waypoints
    
    def get_available_airways(self):
        """
        دریافت لیست Airwayهای موجود
        """
        airways = []
        for airway in AirwaySegment.objects.values('airway__identifier', 'airway__name').distinct():
            segment_count = AirwaySegment.objects.filter(airway__identifier=airway['airway__identifier']).count()
            airways.append({
                'identifier': airway['airway__identifier'],
                'name': airway['airway__name'],
                'segment_count': segment_count
            })
        
        return sorted(airways, key=lambda x: x['identifier'])
    
    def validate_route(self, waypoint_ids):
        """
        اعتبارسنجی مسیر (بررسی وجود Waypointها)
        """
        errors = []
        valid_waypoints = []
        
        for wp_id in waypoint_ids:
            if Waypoint.objects.filter(identifier=wp_id).exists():
                valid_waypoints.append(wp_id)
            else:
                errors.append(f"Waypoint '{wp_id}' پیدا نشد")
        
        if len(valid_waypoints) < 2:
            errors.append("حداقل ۲ Waypoint معتبر نیاز است")
        
        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'valid_waypoints': valid_waypoints,
            'valid_count': len(valid_waypoints),
            'total_count': len(waypoint_ids)
        }


# تابع کمکی برای تست سریع
def quick_route_suggestion(departure, arrival, max_dev=100):
    """
    تابع سریع برای تست مسیریابی
    """
    router = FlightRouter()
    return router.suggest_routes(departure, arrival, max_dev)


def get_router():
    """
    ایجاد instance از FlightRouter
    """
    return FlightRouter()
