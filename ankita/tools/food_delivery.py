"""
Food Delivery Tool
Orders food via delivery services
"""
import webbrowser
from tools.base_tool import BaseTool


class FoodDelivery(BaseTool):
    """Tool to order food delivery."""
    
    def __init__(self):
        super().__init__()
        self.name = "food.delivery"
        self.category = "food"
        
        # Popular delivery services
        self.services = {
            'ubereats': 'https://www.ubereats.com/search?q=',
            'doordash': 'https://www.doordash.com/search/?q=',
            'grubhub': 'https://www.grubhub.com/search?searchTerm=',
            'swiggy': 'https://www.swiggy.com/search?query=',
            'zomato': 'https://www.zomato.com/search?q='
        }
    
    def execute(self, cuisine=None, restaurant=None, service='ubereats', **params):
        """
        Order food delivery.
        
        Args:
            cuisine: Type of cuisine (pizza, chinese, etc.)
            restaurant: Specific restaurant name
            service: Delivery service to use (default: ubereats)
        
        Returns:
            dict: Success/error response
        """
        try:
            # Build search query
            query = restaurant or cuisine or params.get('food') or "food"
            
            # Validate service
            service_lower = service.lower() if service else 'ubereats'
            if service_lower not in self.services:
                available = ', '.join(self.services.keys())
                return self._error(
                    f"Unknown service '{service}'. Available: {available}"
                )
            
            # Get service URL
            base_url = self.services[service_lower]
            url = f"{base_url}{query.replace(' ', '+')}"
            
            # Open in browser
            webbrowser.open(url)
            
            return self._success(
                f"Opened {service_lower.title()} for '{query}'",
                {
                    'service': service_lower,
                    'query': query,
                    'url': url
                }
            )
        
        except Exception as e:
            return self._error(f"Failed to open food delivery: {str(e)}", e)


# Tool registration
def get_tool():
    """Factory function for tool registry."""
    return FoodDelivery()


# CLI test
if __name__ == '__main__':
    tool = FoodDelivery()
    result = tool.execute(cuisine='pizza')
    print(result)
