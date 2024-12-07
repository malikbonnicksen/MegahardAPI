import socket
import random
from threading import Timer
import cherrypy
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from cryptography.fernet import Fernet
import os


class CredentialManager:
    """Manages encrypted Spotify credentials."""
    def __init__(self, credential_file='credentials.enc', key_file='key.key'):
        self.credential_file = credential_file
        self.key_file = key_file

    def get_credentials(self):
        if not os.path.exists(self.credential_file) or not os.path.exists(self.key_file):
            return self._prompt_and_save_credentials()
        return self._load_credentials()

    def _prompt_and_save_credentials(self):
        client_id = input("Enter your Spotify Client ID: ").strip()
        client_secret = input("Enter your Spotify Client Secret: ").strip()

        key = Fernet.generate_key()
        cipher = Fernet(key)

        with open(self.key_file, 'wb') as key_file:
            key_file.write(key)

        credentials = f"{client_id}\n{client_secret}".encode()
        encrypted_credentials = cipher.encrypt(credentials)

        with open(self.credential_file, 'wb') as cred_file:
            cred_file.write(encrypted_credentials)

        print("Credentials saved securely.")
        return client_id, client_secret

    def _load_credentials(self):
        with open(self.key_file, 'rb') as key_file:
            key = key_file.read()
        cipher = Fernet(key)

        with open(self.credential_file, 'rb') as cred_file:
            encrypted_credentials = cred_file.read()

        decrypted_credentials = cipher.decrypt(encrypted_credentials).decode().split("\n")
        return decrypted_credentials[0], decrypted_credentials[1]


class SpotifyPlayer:
    def __init__(self, credential_manager):
        self.credential_manager = credential_manager
        self.playlist = []
        self.now_playing = None
        self.started = False
        self.allowed_genres = set()
        self.user_history = {}  # Track who added each song
        self.spotify = self._initialize_spotify_client()

    def _initialize_spotify_client(self):
        client_id, client_secret = self.credential_manager.get_credentials()
        return spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://127.0.0.1:6666/",
            scope="user-read-currently-playing user-read-playback-state user-modify-playback-state"
        ))

    def add_to_playlist(self, song, user):
        """Adds a song to the playlist, if genre is allowed."""
        if "-" not in song:
            return "Format: Artist - Songname"

        search_result = self.spotify.search(song, limit=1)
        if not search_result['tracks']['items']:
            return "Song not found on Spotify."

        track = search_result['tracks']['items'][0]
        genre = self.get_genre(track)

        if self.allowed_genres and genre not in self.allowed_genres:
            return f"Genre '{genre}' is not allowed on this server."

        if any(item['id'] == track['id'] for item in self.playlist):
            return "Song is already in the playlist."

        self.playlist.append(track)
        self.user_history[track['id']] = {"user": user, "genre": genre}

        if not self.started:
            self._start_playback(track)
        return f"{track['name']} by {track['artists'][0]['name']} added to playlist."

    def get_genre(self, track):
        """Fetches the genre for the track's artist."""
        artist_id = track['artists'][0]['id']
        artist_info = self.spotify.artist(artist_id)
        return artist_info['genres'][0] if artist_info['genres'] else "Unknown"

    def set_allowed_genres(self, genres):
        """Sets the genres allowed on the server."""
        self.allowed_genres = set(genres)

    def get_user_history(self):
        """Returns the history of users and genres."""
        return self.user_history

    def _start_playback(self, track):
        device_id = self._get_device_id()
        if not device_id:
            return "No active Spotify devices found."

        self.spotify.start_playback(
            device_id=device_id,
            context_uri=track['album']['uri'],
            offset={"position": track['track_number'] - 1},
            position_ms=0
        )
        self.now_playing = track
        self.started = True
        self._set_timer(track['duration_ms'])

    def _set_timer(self, duration_ms):
        seconds = duration_ms / 1000
        Timer(seconds, self.play_next).start()

    def play_next(self):
        if not self.playlist:
            self.started = False
            self.now_playing = None
            return "Playlist is empty."

        next_track = random.choice(self.playlist)
        self._start_playback(next_track)
        self.playlist.remove(next_track)

    def _get_device_id(self):
        devices = self.spotify.devices()
        if devices['devices']:
            return devices['devices'][0]['id']
        return None


class AdminDashboard:
    """Handles admin functionality for managing genres and viewing user activity."""
    def __init__(self, player):
        self.player = player

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def GET(self):
        """Displays user activity and current allowed genres."""
        return {
            "user_history": self.player.get_user_history(),
            "allowed_genres": list(self.player.allowed_genres)
        }

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def POST(self):
        """Updates the allowed genres."""
        input_data = cherrypy.request.json
        genres = input_data.get('genres', [])
        self.player.set_allowed_genres(genres)
        return {"message": f"Allowed genres updated: {genres}"}


class MegahardAPI:
    def __init__(self):
        credential_manager = CredentialManager()
        self.player = SpotifyPlayer(credential_manager)
        self.admin = AdminDashboard(self.player)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def GET(self):
        return self.player.get_playlist()

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def PUT(self):
        input_data = cherrypy.request.json
        song = input_data.get('song')
        user = input_data.get('user', 'anonymous')
        if not song:
            return {"error": "Song is required."}
        return self.player.add_to_playlist(song, user)


if __name__ == '__main__':
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ipaddr = s.getsockname()[0]
    portnr = 6666
    s.close()

    cherrypy.config.update({
        'server.socket_host': ipaddr,
        'server.socket_port': portnr,
    })

    app_config = {
        '/': {'tools.sessions.on': True},
        '/admin': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}
    }

    cherrypy.tree.mount(MegahardAPI(), '/', app_config)
    cherrypy.quickstart()
