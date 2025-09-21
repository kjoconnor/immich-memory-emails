from email.mime.image import MIMEImage
import os
import smtplib
import random

from collections import Counter
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from io import BytesIO
from urllib.parse import urljoin

from dotenv import load_dotenv
from PIL import Image
from jinja2 import Template
from pillow_heif import register_heif_opener

from lib.immich import Immich

register_heif_opener()
load_dotenv()

IMMICH_API_TOKEN = os.getenv("IMMICH_API_TOKEN")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = os.getenv("SMTP_PORT")
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SUBSCRIBERS = os.getenv("SUBSCRIBERS").split(",")
IMMICH_BASE_URL = os.getenv("IMMICH_BASE_URL")
PERSON_IDS = os.getenv("PERSON_IDS").split(",")
EMAIL_IMAGE_LIMIT = int(os.getenv("EMAIL_IMAGE_LIMIT"))

start_time = os.getenv("START_TIME")
year, month, day = start_time.split("-")
START_DT = datetime(year=int(year), month=int(month), day=int(day), tzinfo=timezone.utc)


def generate_dt_ranges(until: datetime, current_dt: datetime | None = None):
    # TODO: Actually maybe start at one year ago instead of now?
    if current_dt is None:
        current_dt = datetime.now(timezone.utc)

    current_dt = current_dt.replace(hour=0, minute=0, second=0, microsecond=000000)

    range_start = current_dt - timedelta(days=7)
    range_end = current_dt
    range_end = range_end.replace(hour=23, minute=59, second=59, microsecond=999999)

    while True:
        if range_end < until:
            break

        yield (range_start, range_end)

        range_start = range_start.replace(year=range_start.year - 1)
        range_end = range_end.replace(year=range_end.year - 1)


def get_candidate_images(immich: Immich) -> list[dict]:
    assets = {}
    for taken_after, taken_before in generate_dt_ranges(START_DT):
        assets[taken_after.year] = []
        for person_id in PERSON_IDS:
            print(f"Searching with {taken_before}, {taken_after}, {person_id}")
            search_results = immich.search_random(
                taken_before=taken_before,
                taken_after=taken_after,
                person_id=person_id,
            )
            assets[taken_before.year].extend(search_results)

    years = [year for year in assets.keys() if len(assets[year]) > 0]
    candidate_images = []

    while len(candidate_images) < EMAIL_IMAGE_LIMIT:
        current_image = random.choice(assets[random.choice(years)])
        current_time = datetime.fromisoformat(
            current_image["fileCreatedAt"].replace("Z", "+00:00")
        )

        too_close = False
        for candidate_image in candidate_images:
            candidate_time = datetime.fromisoformat(
                candidate_image["fileCreatedAt"].replace("Z", "+00:00")
            )
            if abs((current_time - candidate_time).total_seconds()) < 60:
                print("Image was too close to another image, continuing")
                too_close = True
                break

        if not too_close:
            candidate_images.append(current_image)

    current_person_counter = Counter()
    for image in candidate_images:
        for person in image["people"]:
            if person["id"] in PERSON_IDS:
                current_person_counter[person["id"]] += 1

    # We missed one of our target people, let's just pick a random one and add
    # it to the end there.
    if len(current_person_counter) != len(PERSON_IDS):
        print(current_person_counter)
        print(PERSON_IDS)
        missing_id = set(PERSON_IDS) - set(current_person_counter.keys())
        print(f"Missing ID: {missing_id}, will append at the end")
        # Just add one more image to get the missing person in
        candidate_images.append(
            random.choice(filter_by_person_id(assets, missing_id.pop()))
        )

    random.shuffle(candidate_images)

    return candidate_images


def filter_by_person_id(assets, person_id):
    return [
        asset
        for year_assets in assets.values()
        for asset in year_assets
        if any(person["id"] == person_id for person in asset["people"])
    ]


def create_email_html(
    immich: Immich, candidate_images: list[dict]
) -> tuple[str, list[dict]]:
    """
    Create email HTML with CID image references and return image data for inline attachments.

    Returns:
        tuple: (html_content, inline_images_data)
        inline_images_data format: [{'cid': str, 'data': bytes, 'filename': str}, ...]
    """
    images = []
    inline_images_data = []

    for i, candidate_image in enumerate(candidate_images):
        image_content = immich.download_asset(candidate_image["id"])
        source_image_bytes = BytesIO(image_content)

        image = Image.open(source_image_bytes)

        # Process image
        image.thumbnail((1024, 768), Image.Resampling.LANCZOS)
        image_bytes = BytesIO()
        image.save(image_bytes, format="JPEG", quality=85)
        image_bytes.seek(0)

        # Generate unique CID for this image
        cid = f"image_{i}_{candidate_image['id']}"

        people_tagged = [
            x["name"].split(" ")[0]
            for x in candidate_image["people"]
            if x["id"] in PERSON_IDS
        ]

        # For template: use CID reference instead of base64
        images.append(
            {
                "date_taken": candidate_image["fileCreatedAt"].split("T")[0],
                "cid": cid,  # Changed from image_data to cid
                "people_tagged": people_tagged,
                "original_url": urljoin(
                    f"{IMMICH_BASE_URL}/photos/", candidate_image["id"]
                ),
            }
        )

        # For email attachments: store image data
        inline_images_data.append(
            {"cid": cid, "data": image_bytes.getvalue(), "filename": f"image_{i}.jpg"}
        )

    template_data = {
        "email_title": "Weekly Flashback",
        "images": images,
    }

    with open("email_template.html", "r") as fh:
        template_str = fh.read()

    template = Template(template_str)
    email_html = template.render(template_data)

    with open("email.html", "w") as fh:
        fh.write(email_html)

    return email_html, inline_images_data


def send_immich_email(
    immich: Immich, candidate_images: list[dict], to_emails: list[str]
):
    """Send email with Immich images as inline attachments."""
    html_content, inline_images_data = create_email_html(immich, candidate_images)

    # Mailgun SMTP setup
    msg = MIMEMultipart("related")
    msg["From"] = f"Weekly Flashbacks <{SMTP_USERNAME}>"
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = "Weekly Flashback"

    # Attach HTML content
    msg.attach(MIMEText(html_content, "html"))

    # Attach inline images
    for img_data in inline_images_data:
        mime_img = MIMEImage(img_data["data"])
        mime_img.add_header("Content-ID", f"<{img_data['cid']}>")
        mime_img.add_header(
            "Content-Disposition", "inline", filename=img_data["filename"]
        )
        msg.attach(mime_img)

    # Send via SMTP
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False


if __name__ == "__main__":
    immich = Immich(immich_base_url=IMMICH_BASE_URL, api_token=IMMICH_API_TOKEN)
    candidate_images = get_candidate_images(immich)
    send_immich_email(immich, candidate_images, SUBSCRIBERS)
