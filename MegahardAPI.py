import socket
import random
from threading import Timer
import cherrypy
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from cryptography.fernet import Fernet
import os


class CredentialManager:
    def __init__(self, credential_file='credentials.enc', key_file='key.key'):
        self.credential_file = credential_file
        self.key_file = key_file

    def get_credentials(self):
        """Retrieves Spotify credentials, prompting the user if not already stored."""
        if not os.path.exists(self.credential_file) or not os.path.exists(self.key_file):
            return self._prompt_and_save_credentials()
        return self._load_credentials()

    def _prompt_and_save_credentials(self):
        """Prompts the user for Spotify credentials and saves them encrypted."""
        client_id = input("Enter your Spotify Client ID: ").strip()
        client_secret = input("Enter your Spotify Client Secret: ").strip()

        # Generate a Fernet encryption key
        key = Fernet.generate_key()
        cipher = Fernet(key)

        # Save the key to a file
        with open(self.key_file, 'wb') as key_file:
            key_file.write(key)

        # Encrypt credentials
        credentials = f"{client_id}\n{client_secret}".encode()
        encrypted_credentials = cipher.encrypt(credentials)

        # Save encrypted credentials to a file
        with open(self.credential_file, 'wb') as cred_file:
            cred_file.write(encrypted_credentials)

        print("Credentials saved securely.")
        return client_id, client_secret

    def _load_credentials(self):
        """Loads and decrypts Spotify credentials from the file."""
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
        self.spotify = self._initialize_spotify_client()

    def _initialize_spotify_client(self):
        """Initializes the Spotify client using encrypted credentials."""
        client_id, client_secret = self.credential_manager.get_credentials()
        return spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://127.0.0.1:6666/",
            scope="user-read-currently-playing user-read-playback-state user-modify-playback-state"
        ))

    def add_to_playlist(self, song):
        """Adds a song to the playlist and starts playback if not already started."""
        if "-" not in song:
            return "Format: Artist - Songname"

        search_result = self.spotify.search(song, limit=1)
        if not search_result['tracks']['items']:
            return "Song not found on Spotify."

        track = search_result['tracks']['items'][0]
        if any(item['id'] == track['id'] for item in self.playlist):
            return "Song is already in the playlist."

        self.playlist.append(track)
        if not self.started:
            self._start_playback(track)
        return f"{track['name']} by {track['artists'][0]['name']} added to playlist."

    def _start_playback(self, track):
        """Starts playback for the given track."""
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
        """Starts a timer to play the next song when the current one ends."""
        seconds = duration_ms / 1000
        Timer(seconds, self.play_next).start()

    def play_next(self):
        """Plays the next song in the playlist."""
        if not self.playlist:
            self.started = False
            self.now_playing = None
            return "Playlist is empty."

        next_track = random.choice(self.playlist)
        self._start_playback(next_track)
        self.playlist.remove(next_track)

    def _get_device_id(self):
        """Returns the ID of the first active device."""
        devices = self.spotify.devices()
        if devices['devices']:
            return devices['devices'][0]['id']
        return None

    def get_playlist(self):
        """Returns the current playlist in a simplified format."""
        return [
            {
                "Artist": track['artists'][0]['name'],
                "Song": track['name'],
                "Duration": f"{track['duration_ms'] // 60000}:{(track['duration_ms'] // 1000) % 60:02}"
            }
            for track in self.playlist
        ]


class MegahardAPI:
    def __init__(self):
        self.player = SpotifyPlayer(CredentialManager())

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def GET(self):
        """Returns the current playlist."""
        playlist = self.player.get_playlist()
        return playlist if playlist else {"message": "Playlist is empty."}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def PUT(self):
        """Adds a song to the playlist."""
        input_data = cherrypy.request.json
        song = input_data.get('song') if input_data else None
        if not song:
            return "Error: 'song' field is required."
        return self.player.add_to_playlist(song)


if __name__ == '__main__':
    # Get IP and port dynamically or default to 127.0.0.1:6666
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ipaddr = s.getsockname()[0]
    portnr = 6666
    s.close()

    cherrypy.config.update({
        'server.socket_host': ipaddr,
        'server.socket_port': portnr,
    })

    config = {
        '/': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True,
            'tools.response_headers.on': True,
            'tools.response_headers.headers': [('Content-Type', 'application/json')],
        }
    }
    cherrypy.quickstart(MegahardAPI(), '/', config)
