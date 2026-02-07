"""
Weather Tool - Get current weather and forecasts using wttr.in API
"""
import requests
import os


def run(action: str = "current", location: str = "", **kwargs):
    """
    Weather tool
    
    Args:
        action: current, forecast, tomorrow
        location: Location (optional, uses USER_CITY from .env if not provided)
    """
    action = action.lower().strip()
    
    # Get location from env if not provided
    if not location:
        location = (os.getenv("USER_CITY") or os.getenv("USER_LOCATION") or "").strip()
    
    if not location:
        return {"status": "fail", "reason": "missing_location"}
    
    try:
        if action == "current":
            # Get current weather
            url = f"https://wttr.in/{location}?format=j1"
            r = requests.get(url, timeout=10)
            
            if not r.ok:
                return {"status": "error", "error": f"http_{r.status_code}"}
            
            data = r.json()
            current = data.get("current_condition", [{}])[0]
            
            temp_f = current.get("temp_F", "N/A")
            temp_c = current.get("temp_C", "N/A")
            feels_like_f = current.get("FeelsLikeF", temp_f)
            desc = (current.get("weatherDesc", [{}])[0].get("value", "Unknown")).strip()
            humidity = current.get("humidity", "N/A")
            wind_mph = current.get("windspeedMiles", "N/A")
            precip = current.get("precipMM", "0")
            
            return {
                "status": "success",
                "location": location,
                "temperature_f": temp_f,
                "temperature_c": temp_c,
                "feels_like_f": feels_like_f,
                "conditions": desc,
                "humidity": humidity,
                "wind_mph": wind_mph,
                "precipitation_mm": precip,
                "message": f"Current weather in {location}: {temp_f}°F ({desc}), feels like {feels_like_f}°F. Humidity: {humidity}%"
            }
        
        elif action == "forecast" or action == "tomorrow":
            # Get forecast
            url = f"https://wttr.in/{location}?format=j1"
            r = requests.get(url, timeout=10)
            
            if not r.ok:
                return {"status": "error", "error": f"http_{r.status_code}"}
            
            data = r.json()
            weather_list = data.get("weather", [])
            
            if not weather_list:
                return {"status": "fail", "reason": "no_forecast_data"}
            
            # Get tomorrow's forecast (index 1)
            tomorrow = weather_list[1] if len(weather_list) > 1 else weather_list[0]
            
            date = tomorrow.get("date", "")
            max_temp_f = tomorrow.get("maxtempF", "N/A")
            min_temp_f = tomorrow.get("mintempF", "N/A")
            desc = (tomorrow.get("hourly", [{}])[0].get("weatherDesc", [{}])[0].get("value", "Unknown")).strip()
            
            return {
                "status": "success",
                "location": location,
                "date": date,
                "max_temp_f": max_temp_f,
                "min_temp_f": min_temp_f,
                "conditions": desc,
                "message": f"Forecast for {location} on {date}: High {max_temp_f}°F, Low {min_temp_f}°F. {desc}"
            }
        
        else:
            return {"status": "fail", "reason": "invalid_action"}
    
    except Exception as e:
        return {"status": "error", "error": str(e)}
