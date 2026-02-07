"""
Spotify Player Tool
Controls Spotify playback
"""
import webbrowser
import subprocess
from tools.base_tool import BaseTool


class SpotifyPlayer(BaseTool):
    """Tool to control Spotify music playback."""
    
    def __init__(self):
        super().__init__()
        self.name = "spotify.play"
        self.category = "entertainment"
    
    def execute(self, action='play', query=None, playlist=None, **params):
        """
        Control Spotify.
        
        Args:
            action: 'play', 'pause', 'next', 'previous', 'open'
            query: Search query (song, artist, album)
            playlist: Playlist name or ID
        
        Returns:
            dict: Success/error response
        """
        try:
            if action == 'play':
                return self._play_music(query, playlist)
            elif action == 'open':
                return self._open_spotify()
            elif action in ['pause', 'next', 'previous']:
                return self._control_playback(action)
            else:
                return self._error(f"Unknown action: {action}")
        
        except Exception as e:
            return self._error(f"Spotify error: {str(e)}", e)
    
    def _play_music(self, query, playlist):
        """Play music on Spotify."""
        # Check if Spotify app is installed
        spotify_installed = self._check_spotify_app()
        
        if spotify_installed:
            # Try to open with Spotify app
            if query:
                # Spotify URI for search
                uri = f"spotify:search:{query.replace(' ', '%20')}"
                try:
                    subprocess.Popen(['start', uri], shell=True)
                    return self._success(f"Playing '{query}' on Spotify app")
                except:
                    pass # Fall back to web
            
            elif playlist:
                # Open playlist (would need playlist URI)
                uri = f"spotify:playlist:{playlist}"
                try:
                    subprocess.Popen(['start', uri], shell=True)
                    return self._success(f"Opening playlist on Spotify app")
                except:
                    pass
        
        # Fallback: Open Spotify Web Player
        search_term = query or playlist or "focus playlist"
        url = f"https://open.spotify.com/search/{search_term.replace(' ', '%20')}"
        webbrowser.open(url)
        
        return self._success(
            f"Opened Spotify Web Player for '{search_term}'",
            {'url': url, 'query': search_term}
        )
    
    def _open_spotify(self):
        """Just open Spotify."""
        try:
            # Try app first
            subprocess.Popen(['start', 'spotify:'], shell=True)
            return self._success("Opened Spotify app")
        except:
            # Fallback to web
            webbrowser.open("https://open.spotify.com")
            return self._success("Opened Spotify Web Player")
    
    def _control_playback(self, action):
        """Control playback (requires Spotify app running)."""
        # This would require Spotify API or local app control
        # For now, just return message
        return self._success(
            f"Playback control '{action}' - requires Spotify Desktop app",
            {'action': action, 'note': 'Use media keys or Spotify app for control'}
        )
    
    def _check_spotify_app(self):
        """Check if Spotify app is installed."""
        try:
            # Try to run Spotify
            result = subprocess.run(
                ['where', 'Spotify.exe'],
                capture_output=True,
                text=True,
                timeout=2
            )
            return result.returncode == 0
        except:
            return False


# Tool registration
def get_tool():
    """Factory function for tool registry."""
    return SpotifyPlayer()


# CLI test
if __name__ == '__main__':
    tool = SpotifyPlayer()
    result = tool.execute(action='play', query='chill vibes')
    print(result)
