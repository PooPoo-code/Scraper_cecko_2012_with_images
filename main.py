import os
import re
import time
import random
import urllib.parse
import requests
import concurrent.futures
import undetected_chromedriver as uc
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

MAX_WORKERS = 8 #Number of concurrent workers (My pc works best at max = 8)

def init_driver():
    """Initialize the Selenium WebDriver. (headless mode gets detected right away)"""
    driver = uc.Chrome()
    driver.set_window_size(1280, 720)
    return driver

def human_delay(min_delay=2, max_delay=6):
    """maybe this is not needed? (kinda slows it down but cloudflare detects it far less with this)  introduce a human-like delay."""
    time.sleep(random.uniform(min_delay, max_delay))

def simulate_scroll(driver):
    """simulate scrolling"""
    actions = ActionChains(driver)
    actions.send_keys(Keys.PAGE_DOWN).perform()

def sanitize_folder_name(name):
    """remove invalid characters."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def ensure_single_extension(filename):
    return filename if filename.endswith('.html') else filename + '.html'


def is_blocked_page(soup):
    blocked_message = "Sorry, you have been blocked"
    return (blocked_message.lower() in soup.get_text().lower() or
            not soup.find('body') or "captcha" in soup.get_text().lower())


def wait_for_image(driver, timeout=60):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, 'img'))
        )
    except Exception as e:
        print(f"Timeout waiting for image to load: {e}")
        return None


def download_image(image_url, base_folder, headers=None):
    """Download the image with shesabamisi headers."""
    headers = headers or {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(image_url, timeout=10, headers=headers)
        response.raise_for_status()
        file_name = sanitize_folder_name(image_url.split('/')[-1])
        file_path = os.path.join(base_folder, file_name)
        with open(file_path, 'wb') as file:
            file.write(response.content)
        print(f"Downloaded image: {file_path}")
        return file_name
    except requests.RequestException as e:
        print(f"Failed to download image: {e}")
        return None


def download_site(driver, url, base_folder):
    year_folder = os.path.join(base_folder, '2012')
    os.makedirs(year_folder, exist_ok=True)
    resources_folder = os.path.join(year_folder, 'resources')
    os.makedirs(resources_folder, exist_ok=True)

    soup = download_page(driver, url, year_folder)
    if soup:
        base_url = url
        links = soup.find_all('a', href=True)
        district_links = []
        other_links = []

        for link in links:
            href = ensure_absolute_url(base_url, link['href'])
            if re.search(r'olq_\d+\.html$', href):
                district_links.append(href)
            else:
                other_links.append(href)

        print(f"Found {len(district_links)} district links and {len(other_links)} other links.")
        update_index_hyperlinks(soup)

        save_page(soup, year_folder, "index.html")

        for href in district_links:
            download_page_and_protocols(driver, href, year_folder)

        for href in other_links:
            if href.endswith(('jpg', 'jpeg', 'png', 'pdf')):
                absolute_href = ensure_absolute_url(base_url, href)
                download_image(absolute_href, resources_folder)


def download_page(driver, url, base_folder, retries=5, is_protocol=False):
    """Download a page and handle retries."""
    delay = 10
    for attempt in range(retries):
        try:
            print(f"Attempting to download page: {url} (Attempt {attempt + 1}/{retries})")
            driver.get(url)
            simulate_scroll(driver)
            human_delay()
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            if is_blocked_page(soup):
                print(f"Blocked! Retrying {attempt + 1}/{retries}...")
                time.sleep(delay)
                delay *= 2
                continue
            file_name = sanitize_folder_name(url.split('/')[-1] or 'index')
            file_name = ensure_single_extension(file_name)
            if is_protocol:
                image_element = wait_for_image(driver, timeout=60)
                if image_element:
                    image_url = urllib.parse.urljoin(url, image_element.get_attribute('src'))
                    images_folder = os.path.join(base_folder, 'images')
                    os.makedirs(images_folder, exist_ok=True)
                    local_image_name = download_image(image_url, images_folder)
                    if local_image_name:
                        img_tag = soup.find('img', {'src': image_element.get_attribute('src')})
                        if img_tag:
                            img_tag['src'] = f"images/{local_image_name}"
                            print(f"Updated img tag to point to local image: {local_image_name}")
            save_page(soup, base_folder, file_name)
            return soup
        except Exception as e:
            print(f"Error on attempt {attempt + 1}/{retries}: {e}")
            time.sleep(delay)
            delay *= 2
    print(f"Failed to download {url} after {retries} retries.")
    return None


def ensure_absolute_url(base_url, link):
    """Ensure absolute URLs."""
    return urllib.parse.urljoin(base_url, link)


def update_hyperlinks(soup, district_number):
    """Update hyperlinks in the soup."""
    print('############################# Updating hyperlinks ################################')
    for link in soup.find_all('a', href=True):
        original_href = link['href']

        if 'prop/' in original_href:
            print(f"Before update: {original_href}")
            original_href = original_href.replace('prop/', '')
            print(f"After update: {original_href}")

        if 'oqmi' in original_href:
            match = re.search(r'oqmi_(\d+)_(\d+)\.html', original_href)
            if match:
                polling_station = match.group(2)
                new_href = f"polling_stations/station_{polling_station}/oqmi_{district_number}_{polling_station}.html"
                link['href'] = new_href
                print(f"Updated polling station hyperlink: {original_href} -> {new_href}")

        elif 'olq' in original_href:
            match = re.search(r'olq_(\d+)\.html', original_href)
            if match:
                district = match.group(1)
                new_href = f"districts/district_{district}/olq_{district}.html"
                link['href'] = new_href
                print(f"Updated district hyperlink: {original_href} -> {new_href}")


def update_index_hyperlinks(soup):
    for link in soup.find_all('a', href=True):
        if 'olq_' in link['href']:
            match = re.search(r'olq_(\d+)\.html', link['href'])
            if match:
                district_number = match.group(1)
                file_name = os.path.basename(link['href'])
                link['href'] = f"districts/district_{district_number}/{file_name.replace('prop/', '')}"
                print(f"Updated index hyperlink: {link['href']}")


def save_page(soup, folder, filename):
    file_path = os.path.join(folder, filename)
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(str(soup))
    print(f"Updated and saved HTML: {file_path}")


def download_protocols_concurrent(driver, soup, district_folder, district_number):
    """Download protocols from the soup concurrently."""
    base_url = driver.current_url
    protocol_links = [ensure_absolute_url(base_url, a_tag['href'])
                      for td in soup.find_all('td', align="center", bgcolor="#EFEFEF")
                      for a_tag in td.find_all('a', href=True, target="_blank")
                      if 'oqmi' in a_tag['href']]

    print(f"Found {len(protocol_links)} protocol links to download.")

    def download_single_protocol(href):
        print(f"Opening protocol page: {href}")
        match = re.search(r'oqmi_(\d+)_(\d+)\.html', href)
        if match:
            polling_station = match.group(2)
            polling_station_folder = os.path.join(district_folder, 'polling_stations', f'station_{polling_station}')
            os.makedirs(polling_station_folder, exist_ok=True)

            protocol_driver = init_driver()
            try:
                protocol_soup = download_page(protocol_driver, href, polling_station_folder, is_protocol=True)

                if protocol_soup:
                    img_tags = protocol_soup.find_all('img')
                    for img in img_tags:
                        if 'src' in img.attrs:
                            img_src = img['src']
                            if not img_src.startswith('images/'):
                                local_img_name = img_src.split('/')[-1]
                                img['src'] = f"images/{local_img_name}"

                    update_hyperlinks(protocol_soup, district_number)

                    file_name = sanitize_folder_name(href.split('/')[-1])
                    file_name = ensure_single_extension(file_name)
                    save_page(protocol_soup, polling_station_folder, file_name)
            finally:
                protocol_driver.quit()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(download_single_protocol, href) for href in protocol_links]
        concurrent.futures.wait(futures)

def download_page_and_protocols(driver, url, year_folder):
    print(f"Processing district page: {url}")
    match = re.search(r'olq_(\d+)\.html', url)
    if match:
        district_number = match.group(1)
        district_name = f"district_{district_number}"
        district_folder = os.path.join(year_folder, 'districts', district_name)
        os.makedirs(district_folder, exist_ok=True)

        soup = download_page(driver, url, district_folder, is_protocol=False)
        if soup:
            before_update_path = os.path.join(district_folder, f"before_update_olq_{district_number}.html")
            save_page(soup, district_folder, f"before_update_olq_{district_number}.html")

            download_protocols_concurrent(driver, soup, district_folder, district_number)
            update_hyperlinks(soup, district_number)
            save_page(soup, district_folder, f"olq_{district_number}.html")

def main():
    base_folder = input("Specify directorty:")
    os.makedirs(base_folder, exist_ok=True)
    driver = init_driver()
    try:
        section_2012_url = 'https://archiveresults.cec.gov.ge/results/2012/index.html'
        download_site(driver, section_2012_url, base_folder)
    finally:
        if driver:
            print("Quitting driver...")
            driver.quit()

if __name__ == "__main__":
    main()