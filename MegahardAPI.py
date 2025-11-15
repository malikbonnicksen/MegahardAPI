import socket
import random
from threading import Timer
import cherrypy
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from cryptography.fernet import Fernet
import os


# Credential Manager (unchanged from earlier updates)
# Credential Manager (opdateret: tjekker først env-vars, så krypteret fil, ellers prompt)
class CredentialManager:
    def __init__(self, credential_file='credentials.enc', key_file='key.key'):
        self.credential_file = credential_file
        self.key_file = key_file

    def get_credentials(self):
        # 1) Tjek miljøvariabler først (praktisk til servers/containers)
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        if client_id and client_secret:
            return client_id, client_secret

        # 2) Hvis ikke env-vars, prøv de krypterede filer
        if os.path.exists(self.credential_file) and os.path.exists(self.key_file):
            return self._load_credentials()

        # 3) Fald tilbage til prompt som sidste udvej (kun hvis en person kører processen)
        return self._prompt_and_save_credentials()

    def _prompt_and_save_credentials(self):
        # Prompt kun når en bruger aktivt kører serveren lokalt
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
        return client_id, client_secret

    def _load_credentials(self):
        with open(self.key_file, 'rb') as key_file:
            key = key_file.read()
        cipher = Fernet(key)
        with open(self.credential_file, 'rb') as cred_file:
            encrypted_credentials = cred_file.read()
        decrypted_credentials = cipher.decrypt(encrypted_credentials).decode().split("\n")
        return decrypted_credentials[0], decrypted_credentials[1]


# Spotify Player
class SpotifyPlayer:
    def __init__(self, credential_manager):
        self.credential_manager = credential_manager
        self.playlist = []
        self.now_playing = None
        self.started = False
        self.allowed_genres = set()
        self.user_history = {}
        self.spotify = self._initialize_spotify_client()

    def _initialize_spotify_client(self):
        client_id, client_secret = self.credential_manager.get_credentials()
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://127.0.0.1:6666/",
            scope="user-read-currently-playing user-read-playback-state user-modify-playback-state",
            cache_path=".spotify_token_cache"
        )
        return spotipy.Spotify(auth_manager=auth_manager)

    def add_to_playlist(self, song, user):
        if "-" not in song:
            return "Format: Artist - Songname"
        search_result = self.spotify.search(q=song, type='track', limit=1)
        if not search_result.get('tracks') or not search_result['tracks']['items']:
            return "Song not found on Spotify."
        track = search_result['tracks']['items'][0]
        genre = self.get_genre(track)
        if self.allowed_genres and genre not in self.allowed_genres:
            return f"Genre '{genre}' is not allowed on this server."
        if any(item['id'] == track['id'] for item in self.playlist):
            return "Song is already in the playlist."

        # Add to internal playlist + history
        self.playlist.append(track)
        self.user_history[track['id']] = {"user": user, "genre": genre}

        device_id = self._get_device_id()
        if not device_id:
            return "No active Spotify devices found."

        if not self.started:
            # Start playback directly with the track URI (plays only the track)
            try:
                self.spotify.start_playback(device_id=device_id, uris=[track['uri']], position_ms=0)
                self.now_playing = track
                self.started = True
            except Exception as e:
                return f"Failed to start playback: {e}"
        else:
            # Add subsequent tracks to Spotify's queue
            try:
                self.spotify.add_to_queue(track['uri'], device_id=device_id)
            except Exception as e:
                return f"Failed to add to Spotify queue: {e}"

        return f"{track['name']} by {track['artists'][0]['name']} added to playlist."

    def get_genre(self, track):
        try:
            artist_id = track['artists'][0]['id']
            artist_info = self.spotify.artist(artist_id)
            genres = artist_info.get('genres', [])
            return genres[0] if genres else "Unknown"
        except Exception:
            return "Unknown"

    def set_allowed_genres(self, genres):
        self.allowed_genres = set(genres)

    def get_user_history(self):
        return self.user_history

    def get_playlist(self):
        return [
            {"Artist": t['artists'][0]['name'], "Song": t['name'], "Duration": t['duration_ms'], "id": t['id']}
            for t in self.playlist
        ]

    def _get_device_id(self):
        try:
            devices = self.spotify.devices()
            if devices and devices.get('devices'):
                return devices['devices'][0]['id']
        except Exception:
            pass
        return None


# Admin Dashboard
# Admin Dashboard (opdateret: hent admin-creds fra env-vars hvis tilgængeligt)
class AdminDashboard:
    def __init__(self, player):
        self.player = player
        # Hent fra env-vars, fallback til default hvis ikke sat (anbefal ikke at bruge default i produktion)
        admin_user = os.environ.get("ADMIN_USER", "admin")
        admin_pass = os.environ.get("ADMIN_PASS", "password")
        self.admin_credentials = {"username": admin_user, "password": admin_pass}

    @cherrypy.expose
    def index(self):
        with open("admin.html", "r") as f:
            return f.read()

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def login(self):
        input_data = cherrypy.request.json
        username = input_data.get("username")
        password = input_data.get("password")
        # Simpelt check; overvej hashing (bcrypt) hvis du vil være mere sikker
        if username == self.admin_credentials["username"] and password == self.admin_credentials["password"]:
            cherrypy.session['logged_in'] = True
            return {"message": "Login successful."}
        cherrypy.response.status = 401
        return {"error": "Invalid credentials."}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def logout(self):
        cherrypy.session.pop('logged_in', None)
        return {"message": "Logged out successfully."}

    def _require_login(self):
        if not cherrypy.session.get('logged_in'):
            raise cherrypy.HTTPError(401, "Unauthorized access.")

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def GET(self):
        self._require_login()
        return {"user_history": self.player.get_user_history(), "allowed_genres": list(self.player.allowed_genres)}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def POST(self):
        self._require_login()
        input_data = cherrypy.request.json
        genres = input_data.get('genres', [])
        self.player.set_allowed_genres(genres)
        return {"message": f"Allowed genres updated: {genres}"}


# Megahard API
class MegahardAPI:
    def __init__(self, player):
        self.player = player

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def GET(self):
        playlist = self.player.get_playlist()
        return playlist if playlist else {"message": "Playlist is empty."}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def PUT(self):
        input_data = cherrypy.request.json
        song = input_data.get('song')
        user = input_data.get('user', 'anonymous')
        if not song:
            cherrypy.response.status = 400
            return {"error": "Song is required."}
        result = self.player.add_to_playlist(song, user)
        # result can be message or error string
        return {"message": result}


if __name__ == '__main__':
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ipaddr = s.getsockname()[0]
    portnr = 6666
    s.close()

    cherrypy.config.update({
        'server.socket_host': ipaddr,
        'server.socket_port': portnr,
        'tools.sessions.on': True,
        'tools.sessions.storage_type': 'ram'  # kan ændres til 'file' hvis ønsket
    })

    credential_manager = CredentialManager()
    shared_player = SpotifyPlayer(credential_manager)

    cherrypy.tree.mount(MegahardAPI(shared_player), '/')
    cherrypy.tree.mount(AdminDashboard(shared_player), '/admin')
    cherrypy.engine.start()
    cherrypy.engine.block()
