#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script de web scraping para Booking.com
Busca automáticamente los dest_id de las ciudades y extrae datos de alojamientos
"""

import time
import sys
import json
import random
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys  # <-- ya lo usabas en buscar_dest_id
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    ElementClickInterceptedException,
    NoSuchElementException
)
from bs4 import BeautifulSoup

# --- Configuración Global ---

# Solo necesitas los nombres de las ciudades
DESTINOS_NOMBRES = [
    "General Villamil",
    "Salinas",
    "Montañita",
    "Puerto López",
    "Ayampe",
    "Manta",
    "Atacames"
]

# Período de búsqueda
FECHA_CHECKIN = "2025-11-11"
FECHA_CHECKOUT = "2025-12-31"

# Constantes de tiempos
ESPERA_INICIAL_PAGINA = 15
ESPERA_SCROLL = 2
ESPERA_PAGINA_DETALLE = 10
ESPERA_MODAL_RESEÑAS = 10

MAX_PAGINAS_RESEÑAS = 5
CARPETA_SALIDA = Path("datos_booking")


def initialize_driver() -> webdriver.Chrome:
    """
    Inicializa y devuelve una instancia del WebDriver de Chrome.
    """
    print("Iniciando el navegador (Chrome)...")
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        # Si quieres headless, descomenta:
        # options.add_argument('--headless=new')

        driver = webdriver.Chrome(options=options)
        driver.maximize_window()
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        print("Navegador iniciado correctamente.")
        return driver
    except Exception as e:
        print(f"Error fatal al iniciar Chrome: {e}")
        print("Asegúrate de que Google Chrome y ChromeDriver estén instalados y en tu PATH.")
        sys.exit(1)


def buscar_dest_id(driver: webdriver.Chrome, ciudad: str, pais: str = "Ecuador") -> tuple:
    """
    Busca automáticamente el dest_id de una ciudad en Booking.com
    """
    print(f"\nBuscando dest_id para: {ciudad}, {pais}")
    try:
        driver.get("https://www.booking.com")
        time.sleep(3)

        # Aceptar cookies (suave)
        for sel in ('button[aria-label="Aceptar"]',
                    'button[aria-label*="Aceptar"]',
                    'button[data-testid="accept-button"]',
                    'button[id*="onetrust-accept-btn"]',
                    'button[aria-label*="Accept"]'):
            try:
                btn = Wait(driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                driver.execute_script("arguments[0].click();", btn)
                break
            except Exception:
                pass

        # Buscar el campo de búsqueda
        search_box = Wait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="ss"]'))
        )

        # Limpiar completamente
        search_box.click()
        search_box.clear()
        time.sleep(0.3)
        search_box.send_keys(Keys.CONTROL + "a")
        search_box.send_keys(Keys.DELETE)
        time.sleep(0.3)

        # Escribir ciudad + país
        search_term = f"{ciudad}, {pais}"
        search_box.send_keys(search_term)
        time.sleep(2)

        # Sugerencias
        try:
            first_suggestion = Wait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'li[data-i="0"]'))
            )
            driver.execute_script("arguments[0].click();", first_suggestion)
            time.sleep(1)
        except Exception:
            search_box.send_keys(Keys.RETURN)
            time.sleep(2)

        # Click buscar
        try:
            search_btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            driver.execute_script("arguments[0].click();", search_btn)
        except Exception:
            pass

        time.sleep(5)

        # Extraer dest_id de la URL
        current_url = driver.current_url
        parsed_url = urlparse(current_url)
        params = parse_qs(parsed_url.query)

        dest_id = params.get('dest_id', [None])[0]
        dest_type = params.get('dest_type', ['city'])[0]

        if dest_id:
            print(f"✓ dest_id encontrado: {dest_id} (tipo: {dest_type})")
            return dest_id, dest_type
        else:
            print(f"✗ No se pudo encontrar dest_id para {ciudad}")
            return None, None

    except Exception as e:
        print(f"Error buscando dest_id: {e}")
        return None, None


def generar_url_busqueda(dest_id: str, dest_type: str, checkin: str, checkout: str) -> str:
    base_url = "https://www.booking.com/searchresults.es.html"
    params = f"?dest_id={dest_id}&dest_type={dest_type}&checkin={checkin}&checkout={checkout}&group_adults=2&no_rooms=1&group_children=0"
    return base_url + params


def scrape_listings_from_search_page(driver: webdriver.Chrome, url: str) -> list:
    """
    Navega a la URL de búsqueda y extrae la información básica de cada propiedad.
    """
    print(f"Navegando a la URL de búsqueda...")
    driver.get(url)

    try:
        Wait(driver, ESPERA_INICIAL_PAGINA).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="property-card"]'))
        )
        print("Página de resultados cargada.")
    except TimeoutException:
        print("La página tardó demasiado en cargar o no se encontraron propiedades.")
        return []

    # Scroll para lazy-load
    print("Haciendo scroll para cargar todos los alojamientos...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(ESPERA_SCROLL)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    print("Extrayendo contenido HTML...")
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    listings = soup.find_all('div', {'data-testid': 'property-card'})
    print(f"--- Se encontraron {len(listings)} propiedades ---")

    properties_data = []
    for listing in listings:
        try:
            # Título
            name_elem = listing.find('div', {'data-testid': 'title'})
            title = name_elem.get_text(strip=True) if name_elem else "Nombre no disponible"

            # Precio
            price_elem = listing.find('span', {'data-testid': 'price-and-discounted-price'}) or listing.select_one('[data-testid="price-for-x-nights"]')
            price = price_elem.get_text(strip=True) if price_elem else "Precio no disponible"

            # URL (prioriza link del título si existe)
            link_elem = listing.find('a', {'data-testid': 'title-link'}) or listing.find('a', {'data-testid': 'availability-cta-btn'})
            detail_url = link_elem.get('href') if link_elem else ""

            # Puntuación
            rating_value = "Sin puntuación"
            score_div = listing.select_one('div[data-testid="review-score"] > div[aria-hidden="true"]')
            if score_div:
                rating_value = score_div.get_text(strip=True)

            # Distancia playa (evita clases ofuscadas frágiles)
            beach_distance = "Sin calificación"
            beach_badge = listing.find(lambda tag: tag.name == "span" and "playa" in tag.get_text(strip=True).lower())
            if beach_badge:
                beach_distance = beach_badge.get_text(strip=True)

            # Distancia del centro
            span_element = listing.find('span', {'data-testid': 'distance'})
            distance = span_element.get_text(strip=True) if span_element else "Distancia no disponible"

            # Características
            features_text = ""
            features_list = listing.select('ul > li > span')
            if features_list:
                features_text = " ".join([s.get_text(strip=True) for s in features_list if s.get_text(strip=True) and '•' not in s.get_text()])

            # Política de pago
            payment_policy = ""
            policy_div = listing.find('div', {'data-testid': 'payment-policy-tags'})
            if policy_div:
                payment_policy = policy_div.get_text(" ", strip=True)

            properties_data.append({
                "title": title,
                "price": price,
                "rating": rating_value,
                "distance": distance,
                "features": features_text,
                "payment_policy": payment_policy,
                "url": detail_url,
                "beach_distance": beach_distance
            })
        except Exception as e:
            print(f"Error extrayendo datos de una propiedad: {e}")
            continue

    return properties_data


def scrape_detail_page_data(driver: webdriver.Chrome) -> dict:
    """
    Extrae datos adicionales desde la página de detalle.
    """
    detail_data = {
        "description": "Descripción no disponible",
        "location": "Ubicación (lat,lng) no disponible",
        "services": []
    }

    try:
        Wait(driver, ESPERA_PAGINA_DETALLE).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'p[data-testid="property-description"]'))
        )

        detail_soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Descripción
        desc_elem_soup = detail_soup.find('p', {'data-testid': 'property-description'})
        if desc_elem_soup:
            detail_data["description"] = desc_elem_soup.get_text(" ", strip=True)

        # Coordenadas
        map_link = detail_soup.select_one('a#map_trigger_header_pin')
        if map_link and map_link.get('data-atlas-latlng'):
            detail_data["location"] = map_link.get('data-atlas-latlng')

        # Servicios (amenities)
        services_wrapper = detail_soup.find('div', {'data-testid': 'property-most-popular-facilities-wrapper'})
        if services_wrapper:
            service_items = services_wrapper.find_all('span')
            detail_data["services"] = [s.get_text(strip=True) for s in service_items if s.get_text(strip=True)]

    except TimeoutException:
        print("  -> No se pudo encontrar la descripción (timeout).")
    except Exception as e:
        print(f"  -> Error extrayendo datos del detalle: {e}")

    return detail_data


# ==========================
# REEMPLAZO: FUNCIÓN DE RESEÑAS
# (Tomada de tu segundo script, con paginación dentro de la modal)
# ==========================
def scrape_reviews_from_modal(driver: webdriver.Chrome, max_pages: int) -> list:
    """
    Abre la modal 'Leer todas las reseñas' y pagina dentro de la modal.
    Devuelve una lista de reseñas con title/date/positive/negative.
    """
    reviews = []

    # 1) Click en 'Leer todas las reseñas'
    try:
        btn_read_reviews = Wait(driver, ESPERA_MODAL_RESEÑAS).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="fr-read-all-reviews"]'))
        )
        driver.execute_script("arguments[0].click();", btn_read_reviews)
    except (TimeoutException, ElementClickInterceptedException):
        print("  -> No se encontró el botón de 'Leer todas las reseñas' o no es clickeable.")
        return reviews

    # 2) Esperar modal
    try:
        modal = Wait(driver, ESPERA_MODAL_RESEÑAS).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                '[data-testid="fr-reviews-modal"], div[role="dialog"]'
            ))
        )
    except TimeoutException:
        print("  -> La modal de reseñas no apareció después de hacer click.")
        return reviews

    def parse_visible_reviews() -> list:
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        containers = soup.select(
            'div[data-testid="fr-reviews-modal"] div[data-testid="review-card"], '
            'div[role="dialog"] div[data-testid="review-card"]'
        )
        parsed_list = []
        for card in containers:
            title_elem = card.find('h4', {'data-testid': 'review-title'})
            date_elem = card.find('span', {'data-testid': 'review-date'})
            review_pos_elem = card.find('div', {'data-testid': 'review-positive-text'})
            review_neg_elem = card.find('div', {'data-testid': 'review-negative-text'})
            parsed_list.append({
                "title": title_elem.get_text(strip=True) if title_elem else "",
                "date": date_elem.get_text(strip=True) if date_elem else "",
                "negative_feedback": review_neg_elem.get_text(strip=True) if review_neg_elem else "",
                "positive_feedback": review_pos_elem.get_text(strip=True) if review_pos_elem else ""
            })
        return parsed_list

    def scroll_modal_completely():
        last_height = -1
        for _ in range(15):
            try:
                current_height = driver.execute_script("return arguments[0].scrollHeight;", modal)
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", modal)
                time.sleep(1.5)
                new_height = driver.execute_script("return arguments[0].scrollHeight;", modal)
                if new_height == last_height or new_height == current_height:
                    break
                last_height = new_height
            except Exception:
                break

    def click_next_page() -> bool:
        """
        Busca el botón 'Página siguiente' y hace clic si existe.
        """
        try:
            # Selector actualizado basado en el HTML proporcionado
            next_button = driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Página siguiente"]')
            
            # Verificar si el botón está habilitado
            if next_button.is_enabled():
                driver.execute_script("arguments[0].click();", next_button)  # Usar JavaScript para hacer clic
                time.sleep(1.5)  # Esperar a que cargue la siguiente página
                return True
        except NoSuchElementException:
            print("  -> No se encontró el botón 'Página siguiente'.")
            return False  # No se encontró el botón, fin de las páginas
        except Exception as e:
            print(f"  -> Error al intentar hacer clic en el botón 'Página siguiente': {e}")
            return False

    collected_titles = set()

    for page in range(1, max_pages + 1):
        print(f"  -> Extrayendo reseñas (Página {page}/{max_pages})...")
        scroll_modal_completely()
        current_page_reviews = parse_visible_reviews()

        for review in current_page_reviews:
            if review['title'] not in collected_titles:
                reviews.append(review)
                collected_titles.add(review['title'])

        if not click_next_page():
            print("  -> No hay más páginas de reseñas.")
            break

    # Cerrar modal (opcional)
    try:
        close_btn = modal.find_element(By.CSS_SELECTOR, 'button[aria-label="Cerrar"]')
        driver.execute_script("arguments[0].click();", close_btn)
    except Exception:
        pass

    return reviews
# ==========================


def save_to_json(data: dict, filename: str):
    """
    Guarda datos en archivo JSON.
    """
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"\nResultados guardados exitosamente en '{filename}'")
    except IOError as e:
        print(f"\nError al guardar el archivo JSON: {e}")


def main():
    """
    Orquesta el proceso: dest_id -> listado -> detalle+reseñas -> JSON por ciudad.
    """
    print("="*60)
    print("SCRAPER BOOKING.COM - BÚSQUEDA AUTOMÁTICA DE DESTINOS")
    print("="*60)

    CARPETA_SALIDA.mkdir(exist_ok=True)
    driver = initialize_driver()
    if not driver:
        return

    try:
        # PASO 1: Buscar IDs de cada destino
        destinos_config = {}
        for ciudad in DESTINOS_NOMBRES:
            dest_id, dest_type = buscar_dest_id(driver, ciudad)
            if dest_id:
                destinos_config[ciudad] = {"dest_id": dest_id, "dest_type": dest_type}
            else:
                print(f"⚠ No se pudo obtener ID para {ciudad}, saltando...")

        # Guardar configuración de IDs
        ids_file = CARPETA_SALIDA / "destinos_ids.json"
        save_to_json(destinos_config, str(ids_file))

        # PASO 2: Procesar cada destino
        for ciudad, config in destinos_config.items():
            print(f"\n{'='*60}")
            print(f"PROCESANDO: {ciudad}")
            print(f"{'='*60}")

            url_busqueda = generar_url_busqueda(
                config['dest_id'],
                config['dest_type'],
                FECHA_CHECKIN,
                FECHA_CHECKOUT
            )

            all_properties_data = scrape_listings_from_search_page(driver, url_busqueda)
            if not all_properties_data:
                print(f"No se encontraron propiedades en {ciudad}.")
                continue

            print(f"\n--- Resumen: {len(all_properties_data)} propiedades encontradas ---")
            print("\nIniciando scraping de páginas de detalle...")

            for i, listing in enumerate(all_properties_data, 1):
                print(f"\n--- [{i}/{len(all_properties_data)}] {listing['title']} ---")
                if not listing['url'] or not listing['url'].startswith("http"):
                    print("  -> URL no válida, saltando.")
                    continue

                try:
                    driver.get(listing['url'])
                    time.sleep(random.uniform(2, 4))

                    detail_data = scrape_detail_page_data(driver)
                    listing.update(detail_data)

                    reviews = scrape_reviews_from_modal(driver, MAX_PAGINAS_RESEÑAS)
                    listing["reviews"] = reviews
                    print(f"  -> {len(reviews)} reseñas encontradas.")

                except Exception as e:
                    print(f"  -> ERROR: {e}")
                    continue

            # PASO 4: Guardar resultados del destino
            resultado = {
                "destino": ciudad,
                "dest_id": config['dest_id'],
                "dest_type": config['dest_type'],
                "fecha_checkin": FECHA_CHECKIN,
                "fecha_checkout": FECHA_CHECKOUT,
                "fecha_scraping": datetime.now().isoformat(),
                "total_alojamientos": len(all_properties_data),
                "alojamientos": all_properties_data
            }

            filename = CARPETA_SALIDA / f"{ciudad.lower().replace(' ', '_')}_data.json"
            save_to_json(resultado, str(filename))

            print(f"\n✓ {ciudad} completado ({len(all_properties_data)} alojamientos)")
            time.sleep(random.uniform(3, 6))

        print("\n" + "="*60)
        print("SCRAPING COMPLETADO EXITOSAMENTE")
        print(f"Archivos guardados en: {CARPETA_SALIDA.absolute()}")
        print("="*60)

    except KeyboardInterrupt:
        print("\n⚠ Scraping interrumpido por el usuario")
    except Exception as e:
        print(f"\n✗ Error crítico: {e}")
    finally:
        print("\nCerrando el navegador...")
        driver.quit()
        print("Proceso finalizado.")


if __name__ == "__main__":  # <-- importante: doble guion bajo
    main()
