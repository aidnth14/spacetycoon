with open("README.md", "r") as f:
    src = f.read()

src = src.replace("server/            relay server (deployed on Fly.io)", "server/            relay server (deployed on Render.com)")
src = src.replace("  fly.toml", "  render.yaml")
src = src.replace("  assets/          synthesized lobby soundtrack (.wav) + icons", "  assets/          synthesized lobby soundtrack (.mp3) + icons")
src = src.replace("cd server\nfly deploy\n```\n\nLive instance: `wss://spacetycoon-relay.fly.dev`", "The server is deployed via Render Blueprint (`render.yaml`). Every push to the `master` branch auto-deploys.\n\nLive instance: `wss://spacetycoon-relay.onrender.com`")

with open("README.md", "w") as f:
    f.write(src)
