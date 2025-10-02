# Wayfinding Kiosk

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

### server

```
cd server
npm install
npm start
```

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

## Tech Stack

- [Next.js](https://nextjs.org/docs). Understand how [routing](https://nextjs.org/docs/app/getting-started/project-structure) works if you're creating a new screen, we're using App Router.
- [Tailwindcss v3](https://v3.tailwindcss.com/docs/installation). Do note that we're using the older v3, the latest version is v4 so some online documentation will differ a lot.
- Docker

## WebSocket Server

I placed some placeholder videos in `hologram-display/assets`. This is what each video represents:

- `wave.mp4`: avatar is waving (when the kiosk is IDLE)
- `fgh.mp4`: avatar is listening, standing still (when the user is talking so the avatar stands till to listen)
- `xyz.mp4`: avatar is talking (when the avatar is replying to the user)

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

## Icons

You can try to find the icons that you need in the lucide-react library.

https://lucide.dev/icons/

## Viewing Instructions

To view how the app will look like in your browser with the dimensions of an iPad Mini

1. Go to Developer Tools
2. Select iPad Mini under Dimensions
3. Rotate the screen such that it becomes landscape
