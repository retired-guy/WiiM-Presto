from picovector import ANTIALIAS_FAST, PicoVector, Polygon, Transform
#from machine import WDT
from presto import Presto
import utime
import gc
import socket
import jpegdec
import pngdec
import json
import secrets
import urequests as requests
import uasyncio as asyncio
import ntptime
import ssl

# Constants
WIIM_IP = secrets.WIIM_IP
TIMEOUT = 15
TIMEZONE_OFFSET = secrets.TIMEZONE_OFFSET * 3600

# Initialize Presto and Display
presto = Presto(ambient_light=False, full_res=True)
presto.set_backlight(0.2)
display = presto.display

WIDTH, HEIGHT = display.get_bounds()
CX, CY = WIDTH // 2, HEIGHT // 2

# Colors
BLACK = display.create_pen(0, 0, 0)
WHITE = display.create_pen(255, 255, 255)
GRAY = display.create_pen(60, 60, 60)

months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
days = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

display.set_pen(BLACK)
display.clear()

# Initialize PicoVector
vector = PicoVector(display)
vector.set_antialiasing(ANTIALIAS_FAST)
vector.set_font("Roboto-Medium.af", 14)

vector.set_font_letter_spacing(100)
vector.set_font_word_spacing(100)

transform = Transform()
vector.set_transform(transform)

# Initialize JPEG Decoder
jpd = jpegdec.JPEG(display)
pnd = pngdec.PNG(display)

#wdt = WDT(timeout=8000)

ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
#ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

def connect_to_wifi():
    print("Connecting to WiFi")
    status = str(presto.connect())
    print("Connection status: " + status)

    for i in range(5):
        #wdt.feed()
        # Get current time from NTP server
        try:
            #await asyncio.to_thread(ntptime.settime)
            ntptime.settime()
            break
        except Exception as e:
            print("Error updating time from NTP server:", e)
            utime.sleep(2)

async def fetch_data(url):
    body = "{}"
    
    try:
        # Parse the URL
        proto, _, host, path = url.split('/', 3)
        assert proto == 'https:'
        
        addr = socket.getaddrinfo(host, 443)[0][-1]
        s = socket.socket()
        s.connect(addr)

        # Wrap the socket with SSL
        s = ssl.wrap_socket(s, server_hostname=host)
        
        request = f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
        s.write(request.encode('utf-8'))
        
        response = b''
        response = s.read(4096)
        s.close()

        # Split the response into headers and body
        headers, body = response.split(b'\r\n\r\n', 1)
        body = body.decode('utf-8')
    except Exception as e:
        print(e)
    finally:
        return body
    
async def fetch_album_art(art_url):
    error = False
    
    gc.collect()
    if "size=0" in art_url:
        proxy_url = str(art_url[:-1]) + "420X420"
    else:
        proxy_url = f"https://wsrv.nl/?url={art_url}&w=420&h=420"

    try:
        response = requests.get(proxy_url, timeout=TIMEOUT)
        if response.status_code == 200:
            display.set_pen(BLACK)
            display.clear()
            album_art = response.content
            try:
                if ".png" in proxy_url:
                    pnd.open_RAM(memoryview(album_art))
                    pnd.decode(30, 0)
                else:
                    jpd.open_RAM(memoryview(album_art))
                    ret = jpd.decode(30, 0, jpegdec.JPEG_SCALE_FULL)
            except Exception as e:
                print("Fetch Art Error:", e)
                error = True
            finally:
                gc.collect()

            # Round corners of album cover
            try:
                rect = Polygon()
                display.set_pen(BLACK)
                rect.rectangle(20, -10, 440, 440, corners=(15, 15, 15, 15), stroke=10)
                vector.draw(rect)
            except Exception as e:
                print("Rect error:", e)
                error = True
        else:
            print("Failed to fetch album art")
            display.set_pen(BLACK)
            display.clear()
            error = True
    except Exception as e:
        print("Error during album art fetch:", e)
        error = True
        
    return(error)    

async def update_clock():
    display.set_pen(BLACK)
    display.clear()

    timestamp = utime.mktime(utime.localtime()) + TIMEZONE_OFFSET
    tm = utime.localtime(timestamp)

    # Format date and time
    date_str = "{:s} {:02d} {:s} {:d}".format(days[tm[6]], tm[2], months[tm[1]-1], tm[0])
    time_str = "{:02d}:{:02d}".format(tm[3], tm[4])
    display.set_pen(WHITE)
    vector.set_font_size(200)
    vector.text(time_str, 20, 240)
    vector.set_font_size(60)
    vector.text(date_str, 40, 360)
    presto.update()

async def update_display(title, artist):
    display.set_pen(BLACK)
    display.rectangle(0, 420, WIDTH, 60)
    display.set_pen(WHITE)
    vector.set_font_size(30)
    vector.text(artist, 30, CY + 205)
    vector.set_font_size(20)
    vector.text(title, 30, CY + 225)
    presto.update()

async def monitor_playback():
    
    status_url = "https://"+WIIM_IP+"/httpapi.asp?command=getPlayerStatus"
    content_url = "https://"+WIIM_IP+"/httpapi.asp?command=getMetaInfo"
    
    old_album = ""
    Title = ""
    artist = ""
    art_url = ""
    count = 0
    playing = False
    idle = True

    gc.collect()
    print("Free:", gc.mem_free())
    
    while True:
        try:
            #wdt.feed()
            try:
                data = await fetch_data(status_url)
                data = json.loads(data)
            except Exception as e:
                print("Fetch error:",e)
                
            if data["status"] == "play":
                playing = True
                idle = False
                count = 0
                if Title != data["Title"]:
                    Title = data["Title"]
                    try:
                        data = await fetch_data(content_url)
                        data = json.loads(data)
                        meta_data = data["metaData"]
                    except Exception as e:
                        print("Fetch error:",e)
                    if art_url != meta_data["albumArtURI"]:
                        art_url = meta_data["albumArtURI"]
                        await fetch_album_art(art_url)

                    artist = meta_data["artist"]
                    if artist == "unknow":
                        artist = meta_data["subtitle"]

                    title = meta_data["title"]
                    await update_display(artist, title)
            else:
                playing = False
                count += 1
                
                if count > 10:
                    idle = True
                    count = 0
                    art_url = ""
                    Title = ""
        except Exception as e:
            print("Connection error:", e)
            count += 1
            if count > 5:
                art_url = ""
                Title = ""
                count = 0
                connect_to_wifi()

        if idle:
            await update_clock()
        
        utime.sleep(0.5)

async def main():
    connect_to_wifi()
    await update_clock()
    await monitor_playback()


# Start the event loop
asyncio.run(main())
