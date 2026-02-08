"""
Weather Tool - God Tier Edition 🌤️
Advanced weather with caching, forecasts, alerts, and smart suggestions
"""
import requests
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# Cache configuration
CACHE_FILE = Path(__file__).parent.parent / 'data' / 'weather_cache.json'
CACHE_FILE.parent.mkdir(exist_ok=True)
CACHE_DURATION = 1800  # 30 minutes

def _get_cache():
    """Load cache from file"""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def _save_cache(cache):
    """Save cache to file"""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except:
        pass

def _get_weather_suggestions(conditions, temp_f, humidity, wind_mph):
    """Generate smart suggestions based on weather"""
    suggestions = []
    
    conditions_lower = conditions.lower()
    temp_num = int(temp_f) if str(temp_f).isdigit() else 70
    
    # Temperature suggestions
    if temp_num < 40:
        suggestions.append("🧥 Wear a heavy jacket")
    elif temp_num < 60:
        suggestions.append("🧥 Bring a light jacket")
    elif temp_num > 85:
        suggestions.append("💧 Stay hydrated")
    
    # Weather condition suggestions
    if any(word in conditions_lower for word in ['rain', 'shower', 'drizzle']):
        suggestions.append("☂️ Bring an umbrella")
    elif 'snow' in conditions_lower:
        suggestions.append("⛄ Dress warmly, roads may be icy")
    elif 'storm' in conditions_lower or 'thunder' in conditions_lower:
        suggestions.append("⚠️ Stay indoors if possible")
    elif 'fog' in conditions_lower or 'mist' in conditions_lower:
        suggestions.append("🚗 Drive carefully, low visibility")
    
    # Humidity suggestions
    try:
        humidity_num = int(humidity) if str(humidity).replace('%', '').isdigit() else 50
        if humidity_num > 70:
            suggestions.append("💧 High humidity, may feel warmer")
    except:
        pass
    
    # Wind suggestions
    try:
        wind_num = int(wind_mph) if str(wind_mph).isdigit() else 0
        if wind_num > 20:
            suggestions.append("💨 Windy conditions, secure loose items")
    except:
        pass
    
    return suggestions


def run(action: str = "current", location: str = "", days: int = 3, **kwargs):
    """
    God-Tier Weather Tool
    
    Args:
        action: current, forecast, tomorrow, week, alerts
        location: Location (optional, cached from previous use)
        days: Number of days for forecast (1-7, default: 3)
    """
    action = action.lower().strip()
    
    # Load cache
    cache = _get_cache()
    
    # Get location from cache or env
    if not location:
        location = cache.get('last_location', '')
    if not location:
        location = (os.getenv("USER_CITY") or os.getenv("USER_LOCATION") or "").strip()
    if not location:
        return {"status": "fail", "reason": "missing_location", 
                "message": "Please specify a location"}
    
    # Save location to cache
    cache['last_location'] = location
    
    # Check cache for current weather
    cache_key = f"{location}_{action}"
    cached_data = cache.get(cache_key, {})
    cache_time = cached_data.get('timestamp', 0)
    
    if time.time() - cache_time < CACHE_DURATION and action == "current":
        cached_data['from_cache'] = True
        _save_cache(cache)
        return cached_data
    
    try:
        # Fetch weather data
        url = f"https://wttr.in/{location}?format=j1"
        r = requests.get(url, timeout=10)
        
        if not r.ok:
            return {"status": "error", "error": f"http_{r.status_code}",
                    "message": f"Failed to fetch weather for {location}"}
        
        data = r.json()
        
        if action == "current":
            current = data.get("current_condition", [{}])[0]
            
            temp_f = current.get("temp_F", "N/A")
            temp_c = current.get("temp_C", "N/A")
            feels_like_f = current.get("FeelsLikeF", temp_f)
            feels_like_c = current.get("FeelsLikeC", temp_c)
            desc = (current.get("weatherDesc", [{}])[0].get("value", "Unknown")).strip()
            humidity = current.get("humidity", "N/A")
            wind_mph = current.get("windspeedMiles", "N/A")
            wind_dir = current.get("winddir16Point", "")
            precip = current.get("precipMM", "0")
            uv_index = current.get("uvIndex", "N/A")
            visibility = current.get("visibility", "N/A")
            pressure = current.get("pressure", "N/A")
            cloud_cover = current.get("cloudcover", "N/A")
            
            # Generate smart suggestions
            suggestions = _get_weather_suggestions(desc, temp_f, humidity, wind_mph)
            
            result = {
                "status": "success",
                "location": location,
                "temperature_f": temp_f,
                "temperature_c": temp_c,
                "feels_like_f": feels_like_f,
                "feels_like_c": feels_like_c,
                "conditions": desc,
                "humidity": humidity,
                "wind_mph": wind_mph,
                "wind_direction": wind_dir,
                "precipitation_mm": precip,
                "uv_index": uv_index,
                "visibility_miles": visibility,
                "pressure_mb": pressure,
                "cloud_cover_percent": cloud_cover,
                "suggestions": suggestions,
                "message": f"🌤️ {location}: {temp_f}°F ({desc}), feels like {feels_like_f}°F | Humidity: {humidity}% | UV: {uv_index}",
                "timestamp": time.time()
            }
            
            # Cache result
            cache[cache_key] = result
            _save_cache(cache)
            return result
        
        elif action in ["forecast", "week", "tomorrow"]:
            # Multi-day forecast
            weather_list = data.get("weather", [])
            
            if not weather_list:
                return {"status": "fail", "reason": "no_forecast_data"}
            
            # Determine days
            if action == "tomorrow":
                days = 1
                start_idx = 1
            elif action == "week":
                days = 7
                start_idx = 0
            else:
                days = min(max(1, days), 7)
                start_idx = 0
            
            forecasts = []
            for i in range(start_idx, min(start_idx + days, len(weather_list))):
                day_data = weather_list[i]
                date = day_data.get("date", "")
                max_temp_f = day_data.get("maxtempF", "N/A")
                min_temp_f = day_data.get("mintempF", "N/A")
                max_temp_c = day_data.get("maxtempC", "N/A")
                min_temp_c = day_data.get("mintempC", "N/A")
                hourly = day_data.get("hourly", [{}])
                desc = (hourly[len(hourly)//2].get("weatherDesc", [{}])[0].get("value", "Unknown")).strip() if hourly else "Unknown"
                uv_index = day_data.get("uvIndex", "N/A")
                
                forecasts.append({
                    "date": date,
                    "max_temp_f": max_temp_f,
                    "min_temp_f": min_temp_f,
                    "max_temp_c": max_temp_c,
                    "min_temp_c": min_temp_c,
                    "conditions": desc,
                    "uv_index": uv_index
                })
            
            return {
                "status": "success",
                "location": location,
                "forecasts": forecasts,
                "days": len(forecasts),
                "message": f"📅 {len(forecasts)}-day forecast for {location}"
            }
        
        elif action == "alerts":
            # Weather alerts (simplified - ideally use a dedicated API)
            current = data.get("current_condition", [{}])[0]
            alerts = []
            
            # Check for extreme conditions
            temp_f = int(current.get("temp_F", 70))
            wind_mph = int(current.get("windspeedMiles", 0))
            uv = int(current.get("uvIndex", 0))
            
            if temp_f > 95:
                alerts.append({"type": "heat", "severity": "high", "message": "⚠️ Extreme heat warning"})
            elif temp_f < 20:
                alerts.append({"type": "cold", "severity": "high", "message": "⚠️ Extreme cold warning"})
            
            if wind_mph > 30:
                alerts.append({"type": "wind", "severity": "medium", "message": "💨 High wind advisory"})
            
            if uv > 8:
                alerts.append({"type": "uv", "severity": "medium", "message": "☀️ High UV index, use sunscreen"})
            
            return {
                "status": "success",
                "location": location,
                "alerts": alerts,
                "count": len(alerts),
                "message": f"🚨 {len(alerts)} active alert(s) for {location}" if alerts else f"✅ No active alerts for {location}"
            }
        
        else:
            return {"status": "fail", "reason": "invalid_action",
                    "message": "Valid actions: current, forecast, tomorrow, week, alerts"}
    
    except Exception as e:
        return {"status": "error", "error": str(e),
                "message": f"Weather error: {str(e)}"}


import time  # Add missing import
