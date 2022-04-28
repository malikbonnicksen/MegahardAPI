import socket
import random
from threading import Timer
import cherrypy
import spotipy
from spotipy.oauth2 import SpotifyOAuth

playlist = []
nowplaying = ""
started = False

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("8.8.8.8", 80))
ipaddr = s.getsockname()[0]
portnr = 6666

# Set IP-address and port of the CherryPy server
cherrypy.config.update({
    'server.socket_host': ipaddr,
    'server.socket_port': portnr,
})
id_and_secret = []
with open('thefile.txt') as file:
    id_and_secret = file.readlines()
id_and_secret[0] = id_and_secret[0].rstrip('\n')
print(id_and_secret)
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=str(id_and_secret[0]),
                                               client_secret=str(id_and_secret[1]),
                                               redirect_uri="http://127.0.0.1:6666/",
                                               scope="user-read-currently-playing user-read-playback-state "
                                                     "user-modify-playback-state"))


# noinspection SpellCheckingInspection
@cherrypy.expose  # Makes every method in the class accessible from the browser
class MegahardAPI(object):

    # This method will get the current playlist
    @cherrypy.tools.json_out()
    def GET(self):
        if len(playlist) == 0:
            return "Playlist empty"
        else:
            pl = Player()
            newplaylist = pl.stripinfo()
            return newplaylist

    # This method will get the request, split it at the dash and call selenium to make a search in various
    # streaming services. It will also add the song to the playlist list-dict.
    @cherrypy.tools.accept(media='text/plain')
    def PUT(self, song=None):
        if song is None:
            return "Artist and/or song needed"
        elif "-" not in song:
            return "Format: Artist - Songname"
        elif "-" in song:
            pl = Player()
            msg = pl.AddToPlaylist(song)
            if msg == 0:
                return "Remember to open Spotify"
            else:
                return song + msg


class Player(object):
    # This method is used to strip the massive amount of info from Spotify
    # and condense the important parts for the app
    def stripinfo(self):
        newplaylist = []
        for entry in playlist:
            duration = entry['tracks']['items'][0]['duration_ms'] / 1000
            newplaylist.append({"Artist": entry['tracks']['items'][0]['artists'][0]['name'],
                                "Song": entry['tracks']['items'][0]['name'],
                                "Duration": str((entry['tracks']['items'][0]['duration_ms'] / 1000) / 60)})
        return newplaylist

    # This method is used to keep track of the songs' duration. When the timer runs out
    # it is time to start a new song
    def timer(self, milliseconds):
        seconds = divmod(milliseconds, 1000)
        t = Timer(seconds[0], self.PlayNext)
        t.start()


    def PlayNext(self):
        global nowplaying
        devicelist = sp.devices()
        for track in playlist:
            if track['tracks']['items'][0]['name'] == nowplaying:
                playlist.remove(track)
        if len(playlist) == 1:
            timeinms = playlist[0]['tracks']['items'][0]['duration_ms']
            sp.start_playback(device_id=devicelist['devices'][0]['id'],
                              context_uri=playlist[0]['tracks']['items'][0]['album']['uri'],
                              offset={"position": playlist[0]['tracks']['items'][0]['track_number'] - 1},
                              position_ms=0)
            self.timer(timeinms)
            nowplaying = playlist[0]['tracks']['items'][0]['name']
        elif len(playlist) > 1:
            next = random.randint(0, (len(playlist) - 1))
            timeinms = playlist[next]['tracks']['items'][0]['duration_ms']
            sp.start_playback(device_id=devicelist['devices'][0]['id'],
                              context_uri=playlist[next]['tracks']['items'][0]['album']['uri'],
                              offset={"position": playlist[next]['tracks']['items'][0]['track_number'] - 1},
                              position_ms=0)
            self.timer(timeinms)
            nowplaying = playlist[next]['tracks']['items'][0]['name']
        else:
            print("DERP")
            # start a playlist the bar has on e.g. Spotify

    # Called everytime a user enters a valid input
    def AddToPlaylist(self, song):
        global started, nowplaying
        item = sp.search(song, 1)
        devicelist = sp.devices()
        if not devicelist:
            return 0
        if item not in playlist:
            playlist.append(item)
            # If no music is playing right now, start the playlist after adding the first track
            if not started:
                sp.start_playback(device_id=devicelist['devices'][0]['id'],
                                  context_uri=playlist[0]['tracks']['items'][0]['album']['uri'],
                                  offset={"position": playlist[0]['tracks']['items'][0]['track_number'] - 1},
                                  position_ms=0)
                mseconds = item['tracks']['items'][0]['duration_ms']
                self.timer(mseconds)
                started = True
                nowplaying = playlist[0]['tracks']['items'][0]['name']
            return " added to playlist"
        elif item in playlist:
            return " is already in playlist"


if __name__ == '__main__':
    # MethodDispatcher makes sure that CherryPy "knows" HTTP-requests (GET, POST osv.)
    conf = {
        '/': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True,
            'tools.response_headers.on': True,
            'tools.response_headers.headers': [('Content-Type', 'text/plain')],
        }
    }
    cherrypy.quickstart(MegahardAPI(), '/', conf)
