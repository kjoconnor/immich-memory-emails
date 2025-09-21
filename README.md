# immich-memory-emails

I used to use Tinybeans and got weekly emails with old photos of my kiddos,
but now they've turned into messy ad riddled ransomware. This recreates their 
"Weekly Flashback" feature.

## Setup

1. Clone the repo, use `uv` to set up your environment.
2. Copy `.env.example` and fill in the values for your environment. You can get person IDs by browsing to the person's page on your Immich server and just grabbing the UUID in the URL bar.
3. Run `python main.py` and check your inbox!