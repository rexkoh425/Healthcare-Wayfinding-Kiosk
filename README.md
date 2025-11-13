# Wayfinding Kiosk

## To run the production build

```
rm -rf .next node_modules
npm install
npm run build
npm run start
```

## Setup & Installation

Clone the repository.

```
git clone https://github.com/CDE3301-IS303/cde3301-wayfinding-kiosk.git
```

### touchscreen-display

```
cd touchscreen-display
npm install
npm run dev
```

Open http://localhost:3000/ for the touchscreen display.

OR

```
node server.js
```

Open https://localhost:3000/ for the touchscreen display.

### server (WebSocket + FastAPI)

```
cd server
npm install
python3 -m pip install -r backend/requirements.txt  # once per machine
# optional: create a venv first
BACKEND_RELOAD=1 npm start
```

By default `npm start` now launches both the WebSocket bridge on port 8080 and the FastAPI backend on port 8000.
Set `BACKEND_RELOAD=0` (or `NODE_ENV=production`) to disable the FastAPI auto-reload watcher.

### hologram-display

Serve the static folder over HTTP (browsers often block autoplay or XHR from `file://`).

```
# from project root
npx http-server hologram-display -p 3001
```

Open http://localhost:3001 for the hologram display.

## To run with Docker Compose

```
docker-compose up --build
```

To run in detached mode

```
docker-compose up -d
```

### Generating local TLS certificates

Most services (Caddy, hologram-display, NFC/RFID) expect to find `/certs/cert.pem` and `/certs/key.pem`.  
The files are gitignored, so create them once per machine before starting Docker Compose:

```
docker run --rm -v "${PWD}/certs:/certs" alpine sh -c "apk add --no-cache openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /certs/key.pem -out /certs/cert.pem -subj '/CN=localhost'"
```

Re-run the command whenever you want to regenerate a fresh self-signed certificate.

## Tech Stack

- [Next.js](https://nextjs.org/docs). Understand how [routing](https://nextjs.org/docs/app/getting-started/project-structure) works if you're creating a new screen, we're using App Router.
- [Tailwindcss v3](https://v3.tailwindcss.com/docs/installation). Do note that we're using the older v3, the latest version is v4 so some online documentation will differ a lot.
- Docker

## WebSocket Server

I placed some placeholder videos in `hologram-display/assets`. This is what each video represents:

- `wave.mp4`: avatar is waving (when the kiosk is IDLE)
- `listen.mp4`: avatar is listening, standing still (when the user is talking so the avatar stands till to listen)
- `reply.mp4`: avatar is talking (when the avatar is replying to the user)

When the chat finishes and you want hologram to revert to IDLE STATE (`wave.mp4`), call:

```ts
send({ type: "action", action: "idle" });
```

### If server is remote

You can ignore this section. I added this section as a reminder if our server needs to be remote.

Add `NEXT_PUBLIC_WS_URL` in `.env.local` if server is remote:

```
NEXT_PUBLIC_WS_URL=ws://your-server-host:8080
```

## How to set up HTTPS for touchscreen display

1. Install OpenSSL
2. Generate a self-signed certificate

```
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365
```

3. Enter a PEM pass phrase (e.g. password)
4. Fill in the fields
5. Remove the passphrase

```
openssl rsa -in key.pem -out key_no_passphrase.pem
```

6. Run the application

```
node server.js
```

## Icons

You can try to find the icons that you need in the lucide-react library.

https://lucide.dev/icons/

## Viewing Instructions

To view how the app will look like in your browser with the dimensions of an iPad Mini

1. Go to Developer Tools
2. Select iPad Mini under Dimensions
3. Rotate the screen such that it becomes landscape

## RFID
> [!NOTE]
> RFID Reader is currently set in USB Mode

# HID Mode
Setup

```bash
cd rfid
sudo apt update
sudo apt install python3-evdev
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
sudo .venv/bin/python rfidv1.py
```

To find the RFID device info:

```bash
cat /proc/bus/input/devices
```

Should look something like this

```bash
I: Bus=0003 Vendor=ffff Product=0035 Version=0110
N: Name="ARM CM0 USB HID Keyboard"
P: Phys=usb-xhci-hcd.0-2/input0
S: Sysfs=/devices/platform/axi/1000120000.pcie/1f00200000.usb/xhci-hcd.0/usb1/1-2/1-2:1.0/0003:FFFF:0035.0001/input/input1
...
```

Running Docker File

```bash
docker build -t rfidimage .
docker run --rm \
    -p 5000:5000 \
    --device /dev/input/event1:/dev/input/event1 \
    rfidimage
```

## Clearing Space in Rpi

```bash
docker compose up --build #build the docker image
docker builder prune --filter "until=2h" #removes previous docker images
```
